"""验证在线文字简谱的音高、节奏、搜索与原子导入，不访问外网。"""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from cloud_score import from_song, to_song
from music import Mapping, compile_plan, parse_jianpu, parse_jianpu_space
from resource_search import SearchCancelled, SearchSong, download_resource, search_jianpu, search_source


def score_page(text):
    return f'<html><div id="jianpuOut">{text}</div><script>unrelated123()</script></html>'


class JianpuNotationTests(unittest.TestCase):
    def test_repeated_notes_rhythm_dots_rests_and_octaves(self):
        song, warnings = parse_jianpu_space("1_1_2=3=.4_.. | 0- 5, 1' #4 bb7 n3", "测试")
        self.assertEqual([n.pitch for n in song.notes], [60, 60, 62, 64, 65, 55, 72, 66, 69, 64])
        self.assertEqual([n.end - n.start for n in song.notes[:5]], [.25, .25, .125, .1875, .4375])
        self.assertEqual(song.notes[5].start - song.notes[4].end, 1)
        self.assertEqual(len(warnings), 2)
        plan = compile_plan(song, Mapping(), style="original")
        self.assertEqual(len(plan.notes), len(song.notes))

    def test_ties_across_bar_and_rest_extension_do_not_retrigger(self):
        song, _ = parse_jianpu_space("1- | -_ 0 | - 2 2", "延音")
        self.assertEqual([(n.start, n.end, n.pitch) for n in song.notes],
                         [(0, 1.25, 60), (2.25, 2.75, 62), (2.75, 3.25, 62)])

    def test_fullwidth_tempo_changes_key_and_lyrics_are_preserved(self):
        song, warnings = parse_jianpu_space("/key(D4)\nｂｐｍ６０\n1 0 2\nL:歌词12345\nｂｐｍ１２０\n3-", "变速")
        self.assertEqual(warnings, [])
        self.assertEqual([(n.start, n.end, n.pitch) for n in song.notes], [(0, 1, 62), (2, 3, 64), (3, 4, 66)])

    def test_key_default_octave_and_double_accidentals(self):
        song, warnings = parse_jianpu_space("bpm 120\n/key(Bb)\n1 ##4 7'", "调号")
        self.assertEqual([n.pitch for n in song.notes], [58, 65, 81])
        self.assertEqual(warnings, [])

    def test_late_tempo_warns_about_initial_default(self):
        song, warnings = parse_jianpu_space("/key(C)\n1\nbpm 60\n2", "速度")
        self.assertEqual([n.end for n in song.notes], [.5, 1.5])
        self.assertEqual(len(warnings), 1)
        self.assertIn("120 BPM", warnings[0])

    def test_standalone_chords_are_not_misread_as_numbered_notes(self):
        song, warnings = parse_jianpu_space("C Em7 F C\n1 2 3\nAm F Dm G7\n4 5", "和弦标记")
        self.assertEqual([n.pitch for n in song.notes], [60, 62, 64, 65, 67])
        self.assertEqual(song.duration, 2.5)
        self.assertTrue(any("和弦" in warning for warning in warnings))

    def test_lyric_transposition_starts_on_matched_note_after_intro_and_rests(self):
        text = '/key(A3)\nbpm108\n1_2_3_\nL:"(前奏)"**\n0 1 2 | - 0 3 4\nL:"(+1key)甲"乙丙丁'
        song, warnings = parse_jianpu_space(text, "转调")
        self.assertEqual([n.pitch for n in song.notes], [57, 59, 61, 58, 60, 62, 63])
        self.assertAlmostEqual(song.notes[4].end - song.notes[4].start, 120 / 108)
        self.assertAlmostEqual(song.duration, 8.5 * 60 / 108)
        self.assertTrue(any("转调" in warning for warning in warnings))

    def test_lyric_placeholders_quotes_and_accumulated_key_changes(self):
        text = '/key(C4)\nbpm120\n11111\nL:"合唱"*甲_"(升2key)乙"\n111\nL:"(降1key)丙"丁"(-1key)戊"'
        song, _ = parse_jianpu_space(text, "连续转调")
        self.assertEqual([n.pitch for n in song.notes], [60, 60, 60, 60, 62, 61, 61, 60])

    def test_transposition_rejects_unmatched_instruction_and_pitch_overflow(self):
        for text in ('1\nL:甲"(+1key)乙"', '/key(C9)\n7\nL:"(+12key)甲"',
                     '1\nL:"(+1key)(+2key)甲"', '1\nL:"(+1key)甲'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_jianpu_space(text, "转调无效")

    def test_stray_lowercase_annotation_warns_without_losing_notes_or_rhythm(self):
        original, _ = parse_jianpu_space("bpm108\n1--1_2_|3", "原谱")
        annotated, warnings = parse_jianpu_space("bpm108\n1--ji1_2_|3", "含杂字")
        self.assertEqual(annotated.notes, original.notes)
        self.assertEqual(annotated.duration, original.duration)
        self.assertTrue(any("ji" in warning and "第 2 行" in warning for warning in warnings))

    def test_unsupported_notation_and_invalid_values_fail_instead_of_skipping(self):
        for text in ("1 & 3", "1 /unknown(2)", "1__", "- 1", "#0 1",
                     "1 b-", "1 n", "1 jnb1", "1 8", "bpm 0\n1",
                     "bpm 501\n1", "/key(C9)7'", "1" + "=" * 6, "1" + "-" * 64, "0 0"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_jianpu_space(text, "无效")

    def test_score_limits(self):
        for text in ("1" * 30001, "1" * 200001, "bpm 20\n" + "1--- " * 151):
            with self.subTest(length=len(text)), self.assertRaises(ValueError):
                parse_jianpu_space(text, "超限")


class JianpuSearchTests(unittest.TestCase):
    def song(self):
        return SearchSong("jianpu", "自编测试曲", "https://jianpu.space/songList/42")

    def test_catalog_matches_simplified_traditional_artist_and_fullwidth(self):
        html = '''<table><tr><td><a href="/songList/42">測試樂曲</a></td><td>測試歌手</td></tr>
            <tr><td><a href="/songList/43">ＡＢＣ</a></td><td>None</td></tr>
            <tr><td><a href="/songList/42">測試樂曲</a></td><td>測試歌手</td></tr>
            <tr><td><a href="https://evil.test/songList/12">測試</a></td><td>歌手</td></tr>
            <tr><td><a href="/songList/42/edit">測試</a></td><td>歌手</td></tr></table>'''
        songs = search_jianpu(html, "测试 乐曲 歌手").songs
        self.assertEqual([(s.title, s.artist) for s in songs], [("測試樂曲", "測試歌手")])
        self.assertEqual(search_jianpu(html, "abc").songs[0].artist, "")
        self.assertEqual(search_jianpu(html, "不存在").songs, [])
        with patch("resource_search._fetch_html", return_value=html) as fetch:
            self.assertEqual(len(search_source("jianpu", "測試").songs), 1)
            self.assertEqual(search_source("jianpu", "測試", 2).songs, [])
            fetch.assert_called_once_with("https://jianpu.space/songList")

    def test_challenge_is_not_reported_as_no_matches(self):
        with self.assertRaisesRegex(ValueError, "验证"):
            search_jianpu("<html>Checking your browser</html>", "曲名")

    def test_import_is_editable_retains_source_and_deduplicates(self):
        text = "/key(D)\nｂｐｍ90\n1_1_2- | 0 3'\nｂｐｍ120\n4=5=. 0-"
        with tempfile.TemporaryDirectory() as folder, patch("resource_search._fetch_html", return_value=score_page(text)):
            first = download_resource(self.song(), Path(folder), Mapping(), threading.Event())
            second = download_resource(self.song(), Path(folder), Mapping(), threading.Event())
            self.assertEqual(first, second)
            self.assertEqual(list(Path(folder).iterdir()), [first])
            data = json.loads(first.read_text(encoding="utf-8"))
            self.assertEqual(data["jianpu_source"]["text"], text)
            self.assertEqual(data["jianpu_source"]["url"], self.song().page_url)
            self.assertEqual(data["jianpu_source"]["warnings"], [])
            self.assertEqual(data["editor"]["style"], "original")
            edited = parse_jianpu(data["editor"]["score"], data["editor"]["bpm"], data["title"], precise=True)
            self.assertEqual(from_song(edited), from_song(to_song(data)))
            self.assertTrue(compile_plan(to_song(data), Mapping(), style="original").notes)

    def test_invalid_page_score_and_mapping_leave_library_empty(self):
        for page, mapping in (("<html>Login</html>", Mapping()), ('<div id="jianpuOut">123', Mapping()),
                              (score_page("1 |: 2"), Mapping()), (score_page("1 2"), Mapping(keys="bad"))):
            with self.subTest(page=page), tempfile.TemporaryDirectory() as folder, \
                    patch("resource_search._fetch_html", return_value=page):
                with self.assertRaises(ValueError):
                    download_resource(self.song(), Path(folder), mapping, threading.Event())
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_cancel_before_and_during_fetch_does_not_save(self):
        cancel = threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            cancel.set()
            with patch("resource_search._fetch_html") as fetch, self.assertRaises(SearchCancelled):
                download_resource(self.song(), Path(folder), Mapping(), cancel)
            fetch.assert_not_called()
            cancel.clear()
            def fetch_page(url):
                cancel.set()
                return score_page("1 2 3")
            with patch("resource_search._fetch_html", side_effect=fetch_page), self.assertRaises(SearchCancelled):
                download_resource(self.song(), Path(folder), Mapping(), cancel)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_write_failure_cleans_staging(self):
        with tempfile.TemporaryDirectory() as folder, patch("resource_search._fetch_html", return_value=score_page("1 2")), \
                patch.object(Path, "replace", side_effect=OSError("磁盘错误")):
            with self.assertRaisesRegex(OSError, "磁盘"):
                download_resource(self.song(), Path(folder), Mapping(), threading.Event())
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
