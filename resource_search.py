"""聚合公开 MIDI 搜索，按来源解析结果并验证下载后的演奏曲谱。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser
import hashlib
from pathlib import Path
import re
import tempfile
import threading
import urllib.parse
import urllib.request

from music import Mapping, compile_plan, read_midi
from online_library import (ONLINE_CATALOG_URL, USER_AGENT, OnlineSong, _safe_title,
                            download_online_song, fetch_catalog)


SOURCES = {"official": "官网曲库", "bitmidi": "BitMidi", "midiworld": "MidiWorld", "midishow": "MidiShow"}
MAX_PAGE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class SearchSong:
    source: str
    title: str
    page_url: str
    download_url: str = ""
    artist: str = ""
    size: int | None = None
    sha256: str | None = None

    @property
    def key(self):
        return self.source, self.download_url or self.page_url

    @property
    def downloadable(self):
        return self.source != "midishow"


@dataclass
class SearchPage:
    songs: list[SearchSong]
    has_more: bool = False


class SearchCancelled(Exception):
    """搜索窗口关闭或请求被替换。"""


def search_url(source: str, query: str, page: int = 1) -> str:
    if source not in SOURCES or not 1 <= page <= 1000:
        raise ValueError("资源来源或页码不正确")
    query = urllib.parse.urlencode({"q": query})
    if source == "official":
        return ONLINE_CATALOG_URL
    if source == "bitmidi":
        return f"https://bitmidi.com/search?{query}&page={page - 1}"
    if source == "midiworld":
        return f"https://www.midiworld.com/search/{str(page) + '/' if page > 1 else ''}?{query}"
    return f"https://www.midishow.com/search/result?{query}&page={page}"


def _site_url(base: str, href: str) -> str:
    """解析站内链接，拒绝页面中混入的外站及非网页协议。"""
    url = urllib.parse.urljoin(base, href)
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme not in ("http", "https") or parsed.username or parsed.password
            or parsed.hostname != urllib.parse.urlsplit(base).hostname or parsed.port not in (None, 80, 443)):
        return ""
    return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))


class _Links(HTMLParser):
    """保留链接标题、嵌套标题和列表前缀，避免依赖网页样式类名。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.link = None
        self.list_text = []
        self.in_heading = False
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self.ignored += 1
        if tag == "li":
            self.list_text = []
        if tag == "a":
            self.link = {"href": attrs.get("href", ""), "title": attrs.get("title", ""),
                         "text": [], "heading": [], "prefix": "".join(self.list_text)}
        if tag in ("h2", "h3", "h4"):
            self.in_heading = True

    def handle_data(self, data):
        if self.ignored:
            return
        self.list_text.append(data)
        if self.link is not None:
            self.link["text"].append(data)
            if self.in_heading:
                self.link["heading"].append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.ignored = max(0, self.ignored - 1)
        if tag in ("h2", "h3", "h4"):
            self.in_heading = False
        if tag == "a" and self.link is not None:
            for field in ("text", "heading"):
                self.link[field] = " ".join("".join(self.link[field]).split())
            self.links.append(self.link)
            self.link = None


def parse_search_page(source: str, html: str, url: str, page: int = 1) -> SearchPage:
    parser = _Links()
    parser.feed(html)
    songs, seen, has_more = [], set(), False
    for link in parser.links:
        target = _site_url(url, link["href"])
        if not target:
            continue
        parsed = urllib.parse.urlsplit(target)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        if "search" in path:
            next_page = params.get("page", ["0"])[0]
            if source == "midiworld":
                match = re.fullmatch(r"/search/(\d+)/", path)
                next_page = match[1] if match else "1"
            if next_page.isdigit() and int(next_page) > (page - 1 if source == "bitmidi" else page):
                has_more = True
        title, download = "", ""
        if source == "bitmidi" and re.fullmatch(r"/[^/]+-midi?", path):
            title = link["title"] or link["text"]
        elif source == "midiworld" and re.fullmatch(r"/download/\d+/?", path):
            title = " ".join(link["prefix"].split()).rstrip(" -")
            download = target
        elif source == "midishow" and re.fullmatch(r"/midi/(?:\d+\.html|[^/]+-\d+)", path):
            title = link["heading"] or link["title"]
        title = re.sub(r"\.(mid|midi)$", "", title, flags=re.IGNORECASE).strip()
        if not title or target in seen:
            continue
        seen.add(target)
        songs.append(SearchSong(source, title[:180], target if not download else url, download))
    if not songs and not any(marker in html.casefold() for marker in
                             ("0 results", "no results", "found nothing", "共找到 0", "没有找到", "未找到")):
        raise ValueError("网站未返回可识别的结果，可能需要验证或页面结构已变化；可打开源站搜索。")
    return SearchPage(songs, has_more)


def _fetch_html(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=12) as response:
        body = response.read(MAX_PAGE_BYTES + 1)
    if len(body) > MAX_PAGE_BYTES:
        raise ValueError("资源网站页面超过 2 MB")
    return body.decode("utf-8", errors="replace")


def search_source(source: str, query: str, page: int = 1) -> SearchPage:
    query = query.strip()
    if not query or len(query) > 100:
        raise ValueError("请填写 1～100 个字符的曲名或作者")
    url = search_url(source, query, page)
    if source == "official":
        if page > 1:
            return SearchPage([])
        songs = fetch_catalog()
        terms = query.casefold().split()
        return SearchPage([
            SearchSong(source, song.title, "https://aiygzn.top/melodica/", song.url,
                       song.artist, song.size, song.sha256)
            for song in songs if all(term in f"{song.title} {song.artist} {song.description}".casefold()
                                     for term in terms)])
    return parse_search_page(source, _fetch_html(url), url, page)


def search_all(query: str, pages: dict[str, int], cancel: threading.Event, results):
    """每个来源完成即投递结果，慢站点和失败站点不阻塞其他结果展示。"""
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="midi-search") as pool:
        futures = {pool.submit(search_source, source, query, page): source for source, page in pages.items()}
        for future in as_completed(futures):
            if cancel.is_set():
                return
            source = futures[future]
            try:
                results.put(("source", (source, future.result(), None)))
            except Exception as error:
                results.put(("source", (source, None, str(error))))


def resolve_download(song: SearchSong) -> str:
    if not song.downloadable:
        raise ValueError("MidiShow 需在源站按账号与积分规则下载，之后导入 MIDI。")
    if song.download_url:
        return song.download_url
    if song.source == "bitmidi":
        parser = _Links()
        parser.feed(_fetch_html(song.page_url))
        for link in parser.links:
            target = _site_url(song.page_url, link["href"])
            if target and re.fullmatch(r"/uploads/[^/]+\.midi?", urllib.parse.urlsplit(target).path, re.IGNORECASE):
                return target
    raise ValueError("未找到公开 MIDI 下载链接，请打开源站查看。")


def download_resource(song: SearchSong, library_dir: Path, mapping: Mapping,
                      cancel: threading.Event) -> Path:
    """先验证下载与八键转换，成功后才把完整 MIDI 放入曲库。"""
    if cancel.is_set():
        raise SearchCancelled()
    url = resolve_download(song)
    library_dir = Path(library_dir)
    library_dir.mkdir(parents=True, exist_ok=True)
    # 中间文件放入独立子目录，取消或转换失败时不会留下半首曲目。
    with tempfile.TemporaryDirectory(prefix=".resource-", dir=library_dir) as staging:
        downloaded = download_online_song(OnlineSong("resource", song.title, url,
                                                    size=song.size, sha256=song.sha256), staging)
        if cancel.is_set():
            raise SearchCancelled()
        parsed = read_midi(downloaded)
        if not compile_plan(parsed, mapping, track="auto", style="piano").notes:
            raise ValueError("此 MIDI 没有可转换的旋律音符")
        digest = hashlib.sha256(downloaded.read_bytes()).hexdigest()[:24]
        if cancel.is_set():
            raise SearchCancelled()
        existing = next(library_dir.glob(f"search-{digest}__*.mid"), None)
        if existing and hashlib.sha256(existing.read_bytes()).hexdigest()[:24] == digest:
            return existing
        destination = library_dir / f"search-{digest}__{_safe_title(song.title)}.mid"
        downloaded.replace(destination)
        return destination
