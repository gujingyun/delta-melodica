"""公开线上曲库的后台上传 API。

接口只监听本机，由 Nginx 负责反向代理；上传请求还必须携带服务端配置的
Bearer 管理令牌。曲目先在临时文件中完成校验，再以原子方式写入静态曲库。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import urllib.parse

from cloud_score import MAX_SCORE_BYTES, from_song
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from music import read_midi
from online_library import MAX_CATALOG_BYTES, MAX_ONLINE_SONG_BYTES, parse_catalog
from score_file import read_score_data, validate_score_file


DEFAULT_CATALOG_URL = "https://aiygzn.top/melodica/songs.json"
DEFAULT_LIBRARY_ROOT = "/usr/share/nginx/html/melodica"
DEFAULT_LOCK_FILE = "/var/lib/delta-melodica-public-library/publish.lock"
MAX_UPLOAD_BYTES = MAX_ONLINE_SONG_BYTES
# multipart 的字段和边界会额外占用少量空间；Nginx 也应使用同一上限。
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 128 * 1024
MAX_UPLOADS_PER_HOUR = 30


class UploadError(ValueError):
    """客户端上传内容不符合公开曲库格式。"""


class CatalogError(RuntimeError):
    """服务器上的公开目录或静态目录不可用。"""


class PublishConflict(RuntimeError):
    """上传内容与线上已有编号或内容冲突。"""


@dataclass(frozen=True)
class Config:
    """公开曲库服务配置；令牌只从受限环境变量读取。"""

    library_root: Path
    catalog_url: str = DEFAULT_CATALOG_URL
    lock_file: Path = Path(DEFAULT_LOCK_FILE)
    admin_token: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("MELODICA_PUBLIC_LIBRARY_TOKEN", "").strip()
        if len(token) < 32:
            raise RuntimeError("未配置有效的公开曲库后台令牌")
        root = os.environ.get("MELODICA_PUBLIC_LIBRARY_ROOT", "").strip()
        lock_file = os.environ.get("MELODICA_PUBLIC_LIBRARY_LOCK", "").strip()
        if not root or not lock_file:
            raise RuntimeError("未配置公开曲库目录或发布锁路径")
        catalog_url = _catalog_url(os.environ.get("MELODICA_PUBLIC_LIBRARY_CATALOG_URL", DEFAULT_CATALOG_URL))
        return cls(
            Path(root),
            catalog_url,
            Path(lock_file),
            token,
        )


def _text(value, field: str, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise UploadError(f"{field}必须是文本")
    value = value.strip()
    if required and not value:
        raise UploadError(f"{field}不能为空")
    if len(value) > maximum or any(ord(char) < 32 for char in value):
        raise UploadError(f"{field}格式不正确，最多 {maximum} 个字符")
    return value


def _catalog_url(value: str) -> str:
    value = _text(value, "目录地址", 500, True)
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
        raise RuntimeError("目录地址必须是没有查询参数的 HTTP 或 HTTPS 地址")
    return value.rstrip("/")


def _filename(value: str) -> str:
    value = _text(value, "文件名", 255, True)
    # 只使用文件名后缀和默认曲名，不把客户端提供的路径写入服务器。
    return value.replace("\\", "/").rsplit("/", 1)[-1]


def _editor_for_publication(source: dict) -> dict | None:
    """只保留可编辑原谱字段，避免发布本地路径和源站信息。"""
    editor = source.get("editor")
    if editor is None and "version" not in source and "score" in source:
        return {"score": source["score"], "bpm": source.get("bpm", 120), "style": "original"}
    if editor is None:
        return None
    if not isinstance(editor, dict):
        raise UploadError("曲谱编辑信息格式不正确")
    allowed = ("format", "mode", "score", "bpm", "style")
    public = {key: editor[key] for key in allowed if key in editor}
    return public or None


@contextmanager
def _temporary_payload(suffix: str, body: bytes):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".public-library-", suffix=suffix, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(body)
        yield temporary
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def build_public_plan(filename: str, body: bytes, *, title=None, artist=None,
                      description=None, song_id=None, catalog_url: str = DEFAULT_CATALOG_URL) -> dict:
    """校验上传内容并生成不含本地隐私的公开曲目计划。"""
    if not isinstance(body, bytes):
        raise UploadError("上传内容格式不正确")
    filename = _filename(filename)
    catalog_url = _catalog_url(catalog_url)
    suffix = Path(filename).suffix.lower()

    if suffix == ".json":
        if len(body) > MAX_SCORE_BYTES:
            raise UploadError("曲谱 JSON 不能超过 2 MB")
        try:
            with _temporary_payload(".json", body) as temporary:
                source = read_score_data(temporary, MAX_SCORE_BYTES)
                song = validate_score_file(temporary)
        except UploadError:
            raise
        except (OSError, ValueError, TypeError, EOFError, IndexError):
            raise UploadError("上传曲谱内容无法解析") from None
        public_score = from_song(song)
        if title is not None:
            public_score["title"] = _text(title, "曲名", 100, True)
        editor = _editor_for_publication(source)
        if editor:
            public_score["editor"] = editor
        public_body = json.dumps(public_score, ensure_ascii=False, indent=2).encode("utf-8")
        if len(public_body) > MAX_SCORE_BYTES:
            raise UploadError("发布曲谱不能超过 2 MB")
        format_name = "score"
        default_title = public_score["title"]
        image_meta = source.get("image_score", {})
        if not isinstance(image_meta, dict):
            image_meta = {}
        default_artist = image_meta.get("artist", "")
        default_description = image_meta.get("description", "")
    elif suffix in (".mid", ".midi"):
        if len(body) > MAX_ONLINE_SONG_BYTES:
            raise UploadError("MIDI 不能超过 10 MB")
        try:
            with _temporary_payload(".mid", body) as temporary:
                read_midi(temporary)
        except (OSError, ValueError, TypeError, EOFError, IndexError):
            raise UploadError("上传 MIDI 内容无法解析") from None
        public_body = body
        format_name = "midi"
        default_title = Path(filename).stem
        default_artist = ""
        default_description = ""
    else:
        raise UploadError("只支持 .json、.mid 或 .midi 文件")

    public_title = _text(title if title is not None else default_title, "曲名", 100, True)
    public_artist = _text(artist if artist is not None else default_artist, "作者", 100)
    public_description = _text(description if description is not None else default_description, "说明", 300)
    digest = hashlib.sha256(public_body).hexdigest()
    if song_id is None:
        song_id = ("score-" if format_name == "score" else "midi-") + digest[:40]
    song_id = _text(song_id, "曲目编号", 80, True)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", song_id):
        raise UploadError("曲目编号只能包含字母、数字、点、下划线和短横线")

    extension = ".json" if format_name == "score" else ".mid"
    entry = {
        "id": song_id,
        "title": public_title,
        "url": f"songs/{song_id}{extension}",
        "format": format_name,
        "size": len(public_body),
        "sha256": digest,
    }
    if public_artist:
        entry["artist"] = public_artist
    if public_description:
        entry["description"] = public_description
    try:
        parse_catalog({"songs": [entry]}, catalog_url)
    except ValueError as error:
        raise UploadError(str(error)) from None
    return {"entry": entry, "body": public_body}


def _read_limited(path: Path, maximum: int) -> bytes:
    try:
        with path.open("rb") as stream:
            body = stream.read(maximum + 1)
    except FileNotFoundError:
        raise
    except OSError as error:
        raise CatalogError("线上曲库文件无法读取") from error
    if len(body) > maximum:
        raise CatalogError("线上曲库文件超过大小限制")
    return body


def _atomic_write(path: Path, body: bytes, mode: int = 0o644) -> None:
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(handle, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        temporary = None
    except OSError as error:
        raise CatalogError("线上曲库文件写入失败") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


try:
    import fcntl
except ImportError:  # Windows 本地测试没有 fcntl，生产 Linux 会使用文件锁。
    fcntl = None

_fallback_lock = threading.Lock()


@contextmanager
def _file_lock(path: Path):
    """跨进程锁住发布事务；Linux 生产环境使用 flock。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            else:
                _fallback_lock.acquire()
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                else:
                    _fallback_lock.release()
    except OSError as error:
        raise CatalogError("线上曲库发布锁不可用") from error


class LibraryStore:
    """负责目录校验、去重和静态文件的原子发布。"""

    def __init__(self, config: Config):
        self.root = Path(config.library_root).expanduser()
        self.catalog_url = config.catalog_url
        self.catalog_path = self.root / "songs.json"
        self.songs_dir = self.root / "songs"
        self.lock_path = Path(config.lock_file).expanduser()

    def ready(self) -> bool:
        return self.root.is_dir() and self.songs_dir.is_dir() and self.catalog_path.is_file()

    def _load_catalog(self):
        if not self.ready():
            raise CatalogError("线上曲库目录尚未配置完成")
        try:
            payload = json.loads(_read_limited(self.catalog_path, MAX_CATALOG_BYTES).decode("utf-8-sig"))
            songs = parse_catalog(payload, self.catalog_url)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise CatalogError("线上曲库目录格式无效") from error
        return payload, songs

    def publish(self, plan: dict) -> dict:
        entry, body = plan["entry"], plan["body"]
        sid = entry["id"]
        extension = ".json" if entry["format"] == "score" else ".mid"
        destination = self.songs_dir / f"{sid}{extension}"
        public_url = urllib.parse.urljoin(self.catalog_url, entry["url"])

        with _file_lock(self.lock_path):
            catalog, songs = self._load_catalog()
            for song in songs:
                if song.sha256 == entry["sha256"]:
                    if song.url != public_url:
                        raise PublishConflict("线上已有相同内容但路径不同的曲目")
                    try:
                        existing = _read_limited(destination, MAX_UPLOAD_BYTES)
                    except FileNotFoundError as error:
                        raise CatalogError("线上目录已有曲目记录，但对应文件不存在") from error
                    if existing != body:
                        raise CatalogError("线上目录已有曲目记录，但文件内容不一致")
                    return self._result({
                        "id": song.song_id,
                        "title": song.title,
                        "format": song.format,
                        "size": song.size or len(body),
                        "sha256": song.sha256 or entry["sha256"],
                    }, public_url, True)
                if song.song_id == sid:
                    raise PublishConflict("线上存在相同编号但内容不同的曲目")

            try:
                existing = _read_limited(destination, MAX_UPLOAD_BYTES)
            except FileNotFoundError:
                existing = None
            if existing is not None and existing != body:
                raise PublishConflict("目标曲目文件已存在但内容不同")

            updated = dict(catalog)
            updated["songs"] = list(catalog["songs"]) + [entry]
            updated["updated_at"] = time.strftime("%Y-%m-%d", time.gmtime())
            try:
                parse_catalog(updated, self.catalog_url)
            except ValueError as error:
                raise CatalogError("更新后的线上曲库目录无效") from error
            catalog_body = json.dumps(updated, ensure_ascii=False, indent=2).encode("utf-8")
            if len(catalog_body) > MAX_CATALOG_BYTES:
                raise CatalogError("更新后的线上曲库目录超过 1 MB")

            created_file = existing is None
            if created_file:
                _atomic_write(destination, body)
            try:
                _atomic_write(self.catalog_path, catalog_body)
            except Exception:
                # 目录替换失败时清理本次新文件；即便进程中途退出，孤立文件也不会进入目录。
                if created_file:
                    try:
                        destination.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise
            return self._result(entry, public_url, False)

    @staticmethod
    def _result(entry: dict, public_url: str, already_exists: bool) -> dict:
        return {
            "id": entry["id"],
            "title": entry["title"],
            "url": public_url,
            "format": entry["format"],
            "size": entry["size"],
            "sha256": entry["sha256"],
            "already_exists": already_exists,
        }

    def list_songs(self) -> list[dict]:
        with _file_lock(self.lock_path):
            _, songs = self._load_catalog()
            return [
                {
                    "id": song.song_id,
                    "title": song.title,
                    "artist": song.artist,
                    "description": song.description,
                    "url": song.url,
                    "format": song.format,
                    "size": song.size,
                    "sha256": song.sha256,
                }
                for song in songs
            ]


class RateLimiter:
    """单进程后台限流；服务保持单 worker 时即可覆盖暴力上传。"""

    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self._items = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            started, count = self._items.get(key, (now, 0))
            if now - started >= self.window:
                started, count = now, 0
            if count >= self.limit:
                raise HTTPException(429, "后台上传过于频繁，请稍后再试")
            self._items[key] = (started, count + 1)


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config.from_env()
    if len(config.admin_token) < 32:
        raise RuntimeError("公开曲库后台令牌至少需要 32 个字符")
    config = replace(config, catalog_url=_catalog_url(config.catalog_url))
    store = LibraryStore(config)
    limiter = RateLimiter(MAX_UPLOADS_PER_HOUR, 3600)
    app = FastAPI(title="三角洲口风琴公开曲库后台 API", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # 不把文件名、表单值或底层解析内容回显给后台客户端。
        return JSONResponse({"detail": "上传请求格式不正确；请使用 multipart/form-data 并提供 file 文件"}, status_code=422)

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.method == "POST" and request.url.path == "/library/songs":
            raw_length = request.headers.get("content-length")
            try:
                content_length = int(raw_length) if raw_length is not None else 0
            except ValueError:
                return JSONResponse({"detail": "请求大小无效"}, status_code=400)
            if content_length > MAX_REQUEST_BYTES:
                return JSONResponse({"detail": "上传文件不能超过 10 MB"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def require_admin(request: Request) -> None:
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not hmac.compare_digest(token.strip(), config.admin_token):
            raise HTTPException(401, "后台授权无效", headers={"WWW-Authenticate": "Bearer"})

    def client_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    @app.get("/health")
    def health():
        return {"status": "ok", "catalog_ready": store.ready()}

    @app.get("/library/songs")
    def list_library(request: Request):
        require_admin(request)
        try:
            return {"songs": store.list_songs()}
        except CatalogError as error:
            raise HTTPException(503, str(error)) from None

    @app.post("/library/songs")
    async def upload_library_song(
        request: Request,
        file: UploadFile = File(...),
        title: str | None = Form(None),
        artist: str | None = Form(None),
        description: str | None = Form(None),
        song_id: str | None = Form(None, alias="id"),
    ):
        require_admin(request)
        limiter.check(client_key(request))
        try:
            body = await file.read(MAX_UPLOAD_BYTES + 1)
            if len(body) > MAX_UPLOAD_BYTES:
                raise UploadError("上传文件不能超过 10 MB")
            plan = build_public_plan(
                file.filename or "",
                body,
                title=title,
                artist=artist,
                description=description,
                song_id=song_id,
                catalog_url=config.catalog_url,
            )
            result = store.publish(plan)
        except UploadError as error:
            raise HTTPException(400, str(error)) from None
        except PublishConflict as error:
            raise HTTPException(409, str(error)) from None
        except CatalogError as error:
            raise HTTPException(503, str(error)) from None
        finally:
            await file.close()
        return JSONResponse(result, status_code=200 if result["already_exists"] else 201)

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.public_library:create_app", factory=True, host="127.0.0.1", port=3004)
