"""验证跨站搜索、失败隔离与下载转换，不依赖外部网络。"""
from pathlib import Path
import io
import queue
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch

from music import Mapping, compile_plan, read_midi
from resource_search import (SearchCancelled, SearchPage, SearchProblem, SearchSong, SiteAccessError, download_resource,
                             parse_search_page, resolve_download, search_all, search_source, search_url)
from test_online_library import Response, midi_bytes


class ResourceSearchTests(unittest.TestCase):
    def test_search_urls_encode_chinese_and_source_page_numbers(self):
        self.assertIn("q=%E7%A8%BB%E9%A6%99", search_url("midishow", "稻香"))
        self.assertTrue(search_url("bitmidi", "A & B", 2).endswith("q=A+%26+B&page=1"))
        self.assertIn("/search/2/", search_url("midiworld", "river", 2))
        with self.assertRaises(ValueError):
            search_source("bitmidi", "  ")

    def test_bitmidi_results_ignore_navigation_duplicates_and_external_urls(self):
        html = '''<a href="/river-mid" title="River.mid">River</a>
            <a href="/river-mid">重复</a><a href="https://evil.test/fake-mid">假曲目</a>
            <a href="javascript:alert(1)">坏链接</a><a href="/search?q=river&page=1">Next ›</a>'''
        page = parse_search_page("bitmidi", html, search_url("bitmidi", "river"))
        self.assertEqual([s.title for s in page.songs], ["River"])
        self.assertTrue(page.has_more)
        self.assertTrue(page.songs[0].downloadable)

    def test_midiworld_preserves_title_and_download(self):
        page = parse_search_page("midiworld", '''<ul><li>River of Dreams (Billy Joel) -
            <a href="/download/159" target="_blank">download</a><script>bad()</script></li></ul>
            <a href="/search/2/?q=river">next »</a>''', search_url("midiworld", "river"))
        self.assertEqual(page.songs[0].title, "River of Dreams (Billy Joel)")
        self.assertEqual(page.songs[0].download_url, "https://www.midiworld.com/download/159")
        self.assertTrue(page.has_more)

    def test_midishow_uses_heading_and_requires_source_download(self):
        html = '''<a href="/midi/42895.html"><h3><em>稻</em>香</h3><p>其他简介</p></a>
            <a href="/midi/vocal-midi-download-222280"><h3>稻香 vocal</h3></a>'''
        page = parse_search_page("midishow", html, search_url("midishow", "稻香"))
        self.assertEqual([s.title for s in page.songs], ["稻香", "稻香 vocal"])
        with self.assertRaisesRegex(ValueError, "积分"):
            resolve_download(page.songs[0])

    def test_empty_results_are_distinguished_from_challenge_page(self):
        self.assertEqual(parse_search_page("bitmidi", "0 results", search_url("bitmidi", "none")).songs, [])
        with self.assertRaisesRegex(ValueError, "验证"):
            parse_search_page("bitmidi", "<html>Checking your browser</html>", search_url("bitmidi", "river"))

    def test_partial_failure_does_not_hide_success(self):
        results = queue.Queue()
        def search(source, query, page):
            if source == "bitmidi":
                raise TimeoutError("超时")
            return SearchPage([SearchSong(source, "测试曲", "https://www.midiworld.com/search/")])
        with patch("resource_search.search_source", side_effect=search):
            search_all("测试", {"bitmidi": 1, "midiworld": 1}, threading.Event(), results)
        returned = dict((value[0], value[1:]) for _, value in (results.get(), results.get()))
        self.assertEqual(returned["bitmidi"], (None, SearchProblem("超时")))
        self.assertEqual(returned["midiworld"][0].songs[0].title, "测试曲")

    def test_http_challenge_reports_browser_requirement_without_retry_or_empty_results(self):
        body = io.BytesIO(b'<title>Just a moment...</title><script src="/cdn-cgi/challenge-platform/x"></script>')
        error = urllib.error.HTTPError(search_url("midishow", "父亲"), 403, "Forbidden",
                                       {"cf-mitigated": "challenge"}, body)
        results = queue.Queue()
        with patch("resource_search.urllib.request.urlopen", side_effect=error) as request:
            search_all("父亲", {"midishow": 1}, threading.Event(), results)
        request.assert_called_once()
        _, (source, page, problem) = results.get_nowait()
        self.assertEqual(source, "midishow")
        self.assertIsNone(page)
        self.assertTrue(problem.browser_required)
        self.assertIn("人机验证", problem.message)
        self.assertTrue(body.closed)

    def test_http_200_verification_page_is_not_parsed_as_a_song_list(self):
        for html, headers in ((b'<title>Just a moment...</title>cloudflare', {}),
                              (b'Checking', {"cf-mitigated": "challenge"})):
            with self.subTest(html=html), patch("resource_search.urllib.request.urlopen", return_value=Response(html, headers)):
                with self.assertRaisesRegex(SiteAccessError, "人机验证"):
                    search_source("midishow", "父亲")

    def test_regular_page_with_cloudflare_script_is_still_searchable(self):
        html = b'<title>Search</title><script src="/cdn-cgi/challenge-platform/x"></script><a href="/midi/1.html"><h3>Song</h3></a>'
        with patch("resource_search.urllib.request.urlopen", return_value=Response(html)):
            page = search_source("midishow", "Song")
        self.assertEqual([song.title for song in page.songs], ["Song"])

    def test_forbidden_and_rate_limit_have_different_actions(self):
        for code, browser, message in ((403, True, "拒绝后台访问"), (429, False, "过于频繁"), (503, False, "HTTP 503")):
            with self.subTest(code=code):
                error = urllib.error.HTTPError(search_url("midishow", "父亲"), code, "Error", {}, io.BytesIO(b'Unavailable'))
                results = queue.Queue()
                with patch("resource_search.urllib.request.urlopen", side_effect=error):
                    search_all("父亲", {"midishow": 1}, threading.Event(), results)
                problem = results.get_nowait()[1][2]
                self.assertEqual(problem.browser_required, browser)
                self.assertIn(message, problem.message)

    def test_cancelled_search_does_not_post_old_results(self):
        cancel, results = threading.Event(), queue.Queue()
        cancel.set()
        with patch("resource_search.search_source", return_value=SearchPage([])):
            search_all("旧搜索", {"bitmidi": 1}, cancel, results)
        self.assertTrue(results.empty())

    def test_bitmidi_resolves_public_file_and_ignores_external_link(self):
        song = SearchSong("bitmidi", "测试", "https://bitmidi.com/test-mid")
        html = '<a href="https://evil.test/uploads/2.mid">假</a><a href="/uploads/1.mid" download>下载</a>'
        with patch("resource_search._fetch_html", return_value=html):
            self.assertEqual(resolve_download(song), "https://bitmidi.com/uploads/1.mid")

    def test_download_converts_and_deduplicates_same_content(self):
        song = SearchSong("midiworld", "测试/曲目", "https://www.midiworld.com/", "https://www.midiworld.com/download/1")
        with tempfile.TemporaryDirectory() as folder, patch("online_library.urllib.request.urlopen",
                                                            side_effect=lambda *a, **kw: Response(midi_bytes())):
            first = download_resource(song, Path(folder), Mapping(), threading.Event())
            second = download_resource(song, Path(folder), Mapping(), threading.Event())
            self.assertEqual(first, second)
            self.assertTrue(compile_plan(read_midi(first), Mapping(), track="auto", style="piano").notes)
            self.assertEqual(list(Path(folder).iterdir()), [first])

    def test_invalid_download_and_conversion_failure_leave_no_files(self):
        song = SearchSong("midiworld", "坏曲目", "https://www.midiworld.com/", "https://www.midiworld.com/download/1")
        for body, mapping in ((b'<html>Login required</html>', Mapping()), (midi_bytes(), Mapping(keys="bad"))):
            with self.subTest(body=body[:10]), tempfile.TemporaryDirectory() as folder, \
                    patch("online_library.urllib.request.urlopen", return_value=Response(body)):
                with self.assertRaises(Exception):
                    download_resource(song, Path(folder), mapping, threading.Event())
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_cancel_during_download_cleans_staging(self):
        cancel = threading.Event()
        def response(*args, **kwargs):
            cancel.set()
            return Response(midi_bytes())
        song = SearchSong("midiworld", "取消", "https://www.midiworld.com/", "https://www.midiworld.com/download/1")
        with tempfile.TemporaryDirectory() as folder, patch("online_library.urllib.request.urlopen", side_effect=response):
            with self.assertRaises(SearchCancelled):
                download_resource(song, Path(folder), Mapping(), cancel)
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
