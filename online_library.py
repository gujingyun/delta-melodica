"""线上曲库目录读取，以及 MIDI／可编辑曲谱 JSON 下载。"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile
import urllib.parse
import urllib.request
import uuid

from music import read_midi
from cloud_score import MAX_SCORE_BYTES, to_song


ONLINE_CATALOG_URL = "https://aiygzn.top/melodica/songs.json"
MAX_CATALOG_BYTES = 1024 * 1024
MAX_ONLINE_SONG_BYTES = 10 * 1024 * 1024
USER_AGENT = "DeltaMelodica/0.15"


@dataclass(frozen=True)
class OnlineSong:
    """线上曲目的展示信息和下载校验信息。"""

    song_id: str
    title: str
    url: str
    artist: str = ""
    description: str = ""
    size: int | None = None
    sha256: str | None = None
    format: str = ""

    @property
    def is_score(self):
        return self.format == "score" or (not self.format and
            urllib.parse.urlsplit(self.url).path.lower().endswith(".json"))


def _text(value, field: str, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"线上曲库字段“{field}”必须是文本")
    value = value.strip()
    if required and not value:
        raise ValueError(f"线上曲库字段“{field}”不能为空")
    if len(value) > maximum:
        raise ValueError(f"线上曲库字段“{field}”过长")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"线上曲库字段“{field}”包含无效字符")
    return value


def parse_catalog(payload, base_url: str) -> list[OnlineSong]:
    """校验线上目录，只保留客户端下载所需字段。"""
    if not isinstance(payload, dict) or not isinstance(payload.get("songs"), list):
        raise ValueError("线上曲库格式不正确")
    if len(payload["songs"]) > 500:
        raise ValueError("线上曲库曲目不能超过 500 首")
    parsed_base = urllib.parse.urlparse(base_url)
    if parsed_base.scheme not in ("http", "https") or not parsed_base.netloc:
        raise ValueError("线上曲库地址必须使用 HTTP 或 HTTPS")

    songs, song_ids = [], set()
    for index, item in enumerate(payload["songs"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"线上曲库第 {index} 项格式不正确")
        song_id = _text(item.get("id"), "id", 80, required=True)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", song_id):
            raise ValueError(f"线上曲库第 {index} 项的 id 格式不正确")
        if song_id in song_ids:
            raise ValueError(f"线上曲库包含重复 id：{song_id}")
        song_ids.add(song_id)
        title = _text(item.get("title"), "title", 100, required=True)
        raw_url = _text(item.get("url"), "url", 500, required=True)
        url = urllib.parse.urljoin(base_url, raw_url)
        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise ValueError(f"线上曲库第 {index} 项的下载地址不正确")
        artist = _text(item.get("artist", ""), "artist", 100)
        description = _text(item.get("description", ""), "description", 300)
        size = item.get("size")
        if size is not None and (type(size) is not int or not 0 < size <= MAX_ONLINE_SONG_BYTES):
            raise ValueError(f"线上曲库第 {index} 项的文件大小不正确")
        sha256 = item.get("sha256")
        if sha256 is not None:
            sha256 = _text(sha256, "sha256", 64).lower()
            if not re.fullmatch(r"[0-9a-f]{64}", sha256):
                raise ValueError(f"线上曲库第 {index} 项的 SHA-256 不正确")
        score_format = item.get("format", "score" if parsed_url.path.lower().endswith(".json") else "midi")
        if score_format not in ("midi", "score"):
            raise ValueError(f"线上曲库第 {index} 项的曲谱格式不受支持")
        if score_format == "score" and size is not None and size > MAX_SCORE_BYTES:
            raise ValueError("线上曲谱 JSON 不能超过 2 MB")
        songs.append(OnlineSong(song_id, title, url, artist, description, size, sha256, score_format))
    return songs


def fetch_catalog(url: str = ONLINE_CATALOG_URL) -> list[OnlineSong]:
    """在线程中读取并解析线上曲库目录。"""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=8) as response:
        body = response.read(MAX_CATALOG_BYTES + 1)
    if len(body) > MAX_CATALOG_BYTES:
        raise ValueError("线上曲库目录超过 1 MB")
    return parse_catalog(json.loads(body.decode("utf-8")), url)


def _safe_title(title: str) -> str:
    """把线上曲名转换为 Windows 文件名的一部分。"""
    safe = "".join(char for char in title if char not in '<>:"/\\|?*' and ord(char) >= 32)
    return safe.rstrip(" .")[:70] or "线上曲目"


def download_online_song(song: OnlineSong, library_dir: str | Path) -> Path:
    """校验下载内容后原子加入曲库；JSON 保留原谱及编辑信息。"""
    library_dir = Path(library_dir)
    library_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    suffix = ".json" if song.is_score else ".mid"
    maximum = MAX_SCORE_BYTES if song.is_score else MAX_ONLINE_SONG_BYTES
    destination = library_dir / f"{uuid.uuid4().hex[:8]}__{_safe_title(song.title)}{suffix}"
    try:
        with tempfile.NamedTemporaryFile(prefix=".online-", suffix=".tmp", dir=library_dir,
                                          delete=False) as temporary:
            temporary_path = Path(temporary.name)
            digest = hashlib.sha256()
            total = 0
            request = urllib.request.Request(song.url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=15) as response:
                headers = getattr(response, "headers", {})
                content_length = headers.get("Content-Length")
                if content_length and int(content_length) > maximum:
                    raise ValueError("线上文件超过大小限制（曲谱 2 MB，MIDI 10 MB）")
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > maximum:
                        raise ValueError("线上文件超过大小限制（曲谱 2 MB，MIDI 10 MB）")
                    temporary.write(chunk)
                    digest.update(chunk)
        if song.size is not None and total != song.size:
            raise ValueError("线上曲目文件大小校验失败")
        if song.sha256 and digest.hexdigest() != song.sha256:
            raise ValueError("线上曲目文件 SHA-256 校验失败")
        if song.is_score:
            validate_score_file(temporary_path)
        else:
            read_midi(temporary_path)
        temporary_path.replace(destination)
        return destination
    except Exception:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        raise


def validate_score_file(path):
    """核对交换音符与可编辑原谱一致，拒绝损坏的编辑附注。"""
    from cloud_score import from_song
    from music import parse_jianpu, parse_jianpu_space
    if Path(path).stat().st_size > MAX_SCORE_BYTES:
        raise ValueError("曲谱 JSON 不能超过 2 MB")
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    song = to_song(data)
    editor = data.get("editor")
    if editor is not None:
        if not isinstance(editor, dict) or editor.get("style", "original") not in ("original", "piano"):
            raise ValueError("曲谱编辑信息格式不正确")
        try:
            if editor.get("format") == "jianpu_space":
                parsed = parse_jianpu_space(editor["score"], song.title, mode=editor.get("mode", "score"))[0]
            else:
                parsed = parse_jianpu(editor["score"], float(editor["bpm"]), song.title, precise=True)
            if from_song(parsed) != from_song(song):
                raise ValueError("曲谱的原谱文字与音符不一致")
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("曲谱编辑信息缺少有效的谱文或速度") from error
    return song
