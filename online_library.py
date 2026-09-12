"""线上曲库目录读取和 MIDI 下载。"""
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


ONLINE_CATALOG_URL = "https://aiygzn.top/melodica/songs.json"
MAX_CATALOG_BYTES = 1024 * 1024
MAX_ONLINE_SONG_BYTES = 10 * 1024 * 1024
USER_AGENT = "DeltaMelodica/0.13"


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
        songs.append(OnlineSong(song_id, title, url, artist, description, size, sha256))
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
    """下载、校验并把线上 MIDI 原子写入本地曲库。"""
    library_dir = Path(library_dir)
    library_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    destination = library_dir / f"{uuid.uuid4().hex[:8]}__{_safe_title(song.title)}.mid"
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
                if content_length and int(content_length) > MAX_ONLINE_SONG_BYTES:
                    raise ValueError("线上 MIDI 文件超过 10 MB")
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ONLINE_SONG_BYTES:
                        raise ValueError("线上 MIDI 文件超过 10 MB")
                    temporary.write(chunk)
                    digest.update(chunk)
        if song.size is not None and total != song.size:
            raise ValueError("线上 MIDI 文件大小校验失败")
        if song.sha256 and digest.hexdigest() != song.sha256:
            raise ValueError("线上 MIDI 文件 SHA-256 校验失败")
        read_midi(temporary_path)
        temporary_path.replace(destination)
        return destination
    except Exception:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        raise
