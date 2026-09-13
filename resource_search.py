"""聚合公开简谱与 MIDI 搜索，按来源解析并验证可演奏曲谱。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import tempfile
import threading
import unicodedata
import urllib.parse
import urllib.request

from cloud_score import from_song
from music import Mapping, compile_plan, parse_jianpu_space, read_midi, song_to_jianpu
from online_library import (ONLINE_CATALOG_URL, USER_AGENT, OnlineSong, _safe_title,
                            download_online_song, fetch_catalog)


SOURCES = {"jianpu": "简谱空间", "official": "官网曲库", "bitmidi": "BitMidi", "midiworld": "MidiWorld", "midishow": "MidiShow"}
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
    if source == "jianpu":
        return "https://jianpu.space/songList"
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


class _JianpuCatalog(HTMLParser):
    """读取公开曲目表的曲名和歌手，不把编辑、历史等导航当成曲目。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.cells, self.cell, self.href = [], [], None, ""

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells, self.href = [], ""
        elif tag == "td":
            self.cell = []
        elif tag == "a" and self.cell is not None and not self.cells:
            self.href = dict(attrs).get("href", "")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.cells.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and len(self.cells) >= 2 and self.href:
            self.rows.append((self.href, self.cells[0], self.cells[1]))


class _JianpuText(HTMLParser):
    """只提取页面明确标记的谱文，不执行网页脚本。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.parts, self.found = 0, [], False

    def handle_starttag(self, tag, attrs):
        if tag == "div":
            if self.depth:
                self.depth += 1
            elif dict(attrs).get("id") == "jianpuOut":
                self.depth, self.found = 1, True
        if self.depth and tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "div" and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


def search_jianpu(html: str, query: str) -> SearchPage:
    from win_input import simplified_chinese
    parser = _JianpuCatalog()
    parser.feed(html)
    terms = simplified_chinese(unicodedata.normalize("NFKC", query)).casefold().split()
    songs, seen, valid_rows = [], set(), 0
    for href, title, artist in parser.rows:
        url = _site_url("https://jianpu.space/songList", href)
        if not title or not re.fullmatch(r"/songList/(?:\d+|[a-f0-9]{24})", urllib.parse.urlsplit(url).path):
            continue
        valid_rows += 1
        artist = "" if artist == "None" else artist
        haystack = simplified_chinese(unicodedata.normalize("NFKC", f"{title} {artist}")).casefold()
        if url not in seen and all(term in haystack for term in terms):
            songs.append(SearchSong("jianpu", title[:100], url, artist=artist[:180]))
            seen.add(url)
    if not valid_rows:
        raise ValueError("简谱空间未返回可识别的曲目目录，可能需要验证或页面结构已变化。")
    return SearchPage(songs)


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
    if source == "jianpu":
        return search_jianpu(_fetch_html(url), query) if page == 1 else SearchPage([])
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
    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="score-search") as pool:
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
    if song.source == "jianpu":
        return _download_jianpu(song, Path(library_dir), mapping, cancel)
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


def _download_jianpu(song: SearchSong, library_dir: Path, mapping: Mapping,
                     cancel: threading.Event) -> Path:
    parser = _JianpuText()
    parser.feed(_fetch_html(song.page_url))
    if cancel.is_set():
        raise SearchCancelled()
    if not parser.found or parser.depth:
        raise ValueError("未找到完整简谱文字；此页面可能需要验证或不支持直接导入。")
    source_text = "".join(parser.parts)
    parsed, warnings = parse_jianpu_space(source_text, song.title)
    if not compile_plan(parsed, mapping, track="auto", style="original").notes:
        raise ValueError("此简谱没有可演奏的音符。")
    data = from_song(parsed)
    # 精确拍数保存源谱变速，编辑器直接复用既有格式；原谱文字另存供核对。
    data["editor"] = {"score": song_to_jianpu(parsed), "bpm": 120, "style": "original"}
    data["jianpu_source"] = {"url": song.page_url, "text": source_text, "warnings": warnings}
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    if len(body) > MAX_PAGE_BYTES:
        raise ValueError("转换后的简谱超过 2 MB。")
    digest = hashlib.sha256(body).hexdigest()[:24]
    if cancel.is_set():
        raise SearchCancelled()
    library_dir.mkdir(parents=True, exist_ok=True)
    destination = library_dir / f"search-{digest}__{_safe_title(song.title)}.json"
    with tempfile.TemporaryDirectory(prefix=".resource-", dir=library_dir) as staging:
        downloaded = Path(staging) / "score.json"
        downloaded.write_bytes(body)
        if cancel.is_set():
            raise SearchCancelled()
        if not destination.exists() or destination.read_bytes() != body:
            downloaded.replace(destination)
    return destination
