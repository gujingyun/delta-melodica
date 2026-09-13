"""验证聚合窗口的异步结果、下载试听与账号生命周期。"""
import gc
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App
from resource_search import SearchPage, SearchSong
from test_online_library import midi_bytes


class ResourceSearchDialogTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.app = App(self.root, self.folder.name, smoke=True)
        self.app.overlay.enabled = False
        self.dialog = self.app.resource_search_dialog()
        for source, enabled in self.dialog.enabled.items():
            enabled.set(source == "midiworld")
        self.root.update()

    def tearDown(self):
        self.app.close()
        self.folder.cleanup()
        self.dialog = self.app = self.root = None
        gc.collect()

    def wait_until(self, condition):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                return
            time.sleep(0.01)
        self.fail("等待聚合窗口事件超时")

    def search(self, songs, more=False):
        with patch("resource_search.search_source", return_value=SearchPage(songs, more)):
            self.dialog.query.set("测试")
            self.dialog.search()
            self.wait_until(lambda: not self.dialog.pending)

    def song(self, title="测试曲"):
        return SearchSong("midiworld", title, "https://www.midiworld.com/search/?q=test",
                          "https://www.midiworld.com/download/1")

    def test_results_allow_download_and_convert_to_existing_plan(self):
        self.search([self.song()])
        with patch("online_library.urllib.request.urlopen") as urlopen:
            from test_online_library import Response
            urlopen.return_value = Response(midi_bytes())
            self.dialog.download()
            self.wait_until(lambda: not self.dialog.downloading)
        self.assertEqual(self.app.title.get(), "测试曲")
        self.assertTrue(self.app.plan.notes)
        self.assertEqual(self.app.plan.style, "piano")
        self.assertIn("已下载并转换", self.dialog.status.get())
        self.assertFalse(self.app.player.active)

    def test_jianpu_import_uses_original_rhythm_and_remains_editable_after_reload(self):
        from test_jianpu_search import score_page
        from cloud_score import from_song
        from music import parse_jianpu
        song = SearchSong("jianpu", "文字简谱", "https://jianpu.space/songList/42")
        self.search([song])
        self.assertEqual(self.dialog.download_button["text"], "导入简谱")
        with patch("resource_search._fetch_html", return_value=score_page("1_1_0 2-")):
            self.dialog.download()
            self.wait_until(lambda: not self.dialog.downloading)
        self.assertEqual(self.app.title.get(), "文字简谱")
        self.assertEqual(self.app.plan.style, "original")
        self.assertEqual(len(self.app.plan.notes), 3)
        self.assertIn("120 BPM", self.dialog.detail.get())
        self.assertIn("1=C4", self.app.subtitle.get())
        self.assertFalse(self.app.player.active)
        path = self.app.current_source[1]
        self.dialog.close()
        self.app._load_library(path)
        self.assertIn("120 BPM", self.app.subtitle.get())
        self.app.edit_song()
        editor = self.app.score_editor
        self.assertTrue(editor.is_source)
        self.assertEqual(editor.text.get("1.0", "end-1c"), "1_1_0 2-")
        self.assertEqual(from_song(editor.parsed()), {**from_song(self.app.song), "title": editor.name.get()})
        editor.close(force=True)

    def test_default_search_focuses_on_jianpu(self):
        self.dialog.close()
        self.dialog = self.app.resource_search_dialog()
        self.assertEqual([source for source, enabled in self.dialog.enabled.items() if enabled.get()], ["jianpu"])
        self.assertEqual(self.dialog.rule_mode.get(), "按谱面规则")

    def test_selected_rule_mode_is_used_for_import(self):
        import json
        from test_jianpu_search import score_page
        song = SearchSong("jianpu", "规则选择", "https://jianpu.space/songList/42")
        self.search([song])
        self.dialog.rule_mode.set("跟随源站播放")
        self.dialog.select()
        self.assertIn("最后一个调号", self.dialog.detail.get())
        with patch("resource_search._fetch_html", return_value=score_page("/key(C4)\n|:1/key(D4)2:|")):
            self.dialog.download()
            self.assertEqual(str(self.dialog.rule_combo["state"]), "disabled")
            self.wait_until(lambda: not self.dialog.downloading)
        self.assertEqual([n.pitch for n in self.app.song.notes], [62, 64])
        self.assertIn("跟随源站播放", self.app.subtitle.get())
        data = json.loads(self.app.current_source[1].read_text(encoding="utf-8"))
        self.assertEqual(data["jianpu_source"]["mode"], "source")

    def test_rule_import_editor_save_and_reopen_preserve_note_holds(self):
        from test_jianpu_search import score_page
        from cloud_score import from_song
        self.search([SearchSong("jianpu", "反复连奏", "https://jianpu.space/songList/42")])
        with patch("resource_search._fetch_html", return_value=score_page("|:1~1 (2 3)[1 4:|[2 5")):
            self.dialog.download()
            self.wait_until(lambda: not self.dialog.downloading)
        self.assertEqual([n.pitch for n in self.app.song.notes], [60, 62, 64, 65, 60, 62, 64, 67])
        expected = from_song(self.app.song)
        original_path = self.app.current_source[1]
        self.dialog.close()
        self.app.edit_song()
        editor = self.app.score_editor
        editor.name.set(self.app.song.title)
        self.assertEqual(from_song(editor.parsed()), expected)
        editor.save()
        self.assertNotEqual(editor.saved_path, original_path)
        self.assertEqual(from_song(self.app.song), expected)
        self.app.edit_song()
        self.assertEqual(from_song(self.app.score_editor.parsed()), {**expected, "title": "反复连奏 · 修改版"})
        self.assertEqual([n.legato for n in self.app.plan.notes], [True, True, True, False] * 2)
        self.app.score_editor.close(force=True)

    def test_invalid_jianpu_does_not_replace_current_song_or_preview(self):
        from test_jianpu_search import score_page
        self.search([SearchSong("jianpu", "无法识别", "https://jianpu.space/songList/42")])
        original = self.app.current_source
        with patch("resource_search._fetch_html", return_value=score_page("1 & 2")), patch.object(self.app, "play") as play:
            self.dialog.download(True)
            self.wait_until(lambda: not self.dialog.downloading)
        self.assertEqual(self.app.current_source, original)
        play.assert_not_called()
        self.assertFalse(self.dialog.closed)
        self.assertIn("暂不支持", self.dialog.status.get())

    def test_jianpu_preview_closes_dialog_before_local_play(self):
        from test_jianpu_search import score_page
        self.search([SearchSong("jianpu", "试听简谱", "https://jianpu.space/songList/42")])
        def play(*, preview):
            self.assertTrue(preview)
            self.assertIsNone(self.root.grab_current())
            self.assertEqual(self.app.title.get(), "试听简谱")
            self.assertEqual(self.app.plan.style, "original")
        with patch("resource_search._fetch_html", return_value=score_page("1_1_0 2-")), \
                patch.object(self.app, "play", side_effect=play) as start:
            self.dialog.download(True)
            self.wait_until(lambda: self.dialog.closed)
        start.assert_called_once_with(preview=True)

    def test_jianpu_with_lyric_key_change_imports_and_keeps_review_warning(self):
        from test_jianpu_search import score_page
        self.search([SearchSong("jianpu", "转调简谱", "https://jianpu.space/songList/42")])
        text = '/key(A3)\nbpm108\n1_2_\nL:**\n0 1--ji1_2_\nL:"(+1key)甲"乙丙'
        with patch("resource_search._fetch_html", return_value=score_page(text)):
            self.dialog.download()
            self.wait_until(lambda: not self.dialog.downloading)
        self.assertEqual([n.pitch for n in self.app.song.notes], [57, 59, 58, 58, 60])
        self.assertIn("转调", self.dialog.detail.get())
        self.assertIn("ji", self.dialog.detail.get())
        self.assertFalse(self.app.player.active)
        path = self.app.current_source[1]
        self.dialog.close()
        self.app._load_library(path)
        self.assertIn("转调", self.app.subtitle.get())
        self.app.edit_song()
        edited = self.app.score_editor.parsed()
        self.assertEqual([n.pitch for n in edited.notes], [n.pitch for n in self.app.song.notes])
        self.assertAlmostEqual(edited.duration, self.app.song.duration, places=3)
        self.app.score_editor.close(force=True)

    def test_download_result_does_not_replace_an_active_performance(self):
        self.search([self.song()])
        original = self.app.current_source
        self.app.busy = True
        self.dialog.events.put(("download", (self.song(), Path("later.mid"), True, None)))
        with patch.object(self.app, "play") as play:
            self.dialog._poll()
        self.app.busy = False
        self.assertEqual(self.app.current_source, original)
        play.assert_not_called()
        self.assertIn("结束当前演奏", self.dialog.status.get())

    def test_preview_closes_modal_before_playing_and_does_not_start_game_output(self):
        self.search([self.song()])
        destination = self.app.library_dir / "test__试听曲.mid"
        destination.write_bytes(midi_bytes())
        def play(*, preview):
            self.assertTrue(preview)
            self.assertIsNone(self.root.grab_current())
        with patch("resource_search_ui.download_resource", return_value=destination), \
                patch.object(self.app, "play", side_effect=play) as start:
            self.dialog.download(True)
            self.wait_until(lambda: self.dialog.closed)
            start.assert_called_once_with(preview=True)

    def test_new_query_discards_late_results(self):
        release, completed = threading.Event(), threading.Event()
        def search(source, query, page):
            if query == "旧曲":
                release.wait(2)
                completed.set()
            return SearchPage([self.song(query)])
        with patch("resource_search.search_source", side_effect=search):
            self.dialog.query.set("旧曲")
            self.dialog.search()
            self.dialog.query.set("新曲")
            self.dialog.search()
            self.wait_until(lambda: not self.dialog.pending)
            release.set()
            self.wait_until(completed.is_set)
        self.assertEqual([s.title for s in self.dialog.songs.values()], ["新曲"])

    def test_load_more_deduplicates_and_keeps_previous_selection(self):
        self.search([self.song()], more=True)
        previous = self.dialog.tree.selection()
        second = SearchSong("midiworld", "第二首", self.song().page_url, "https://www.midiworld.com/download/2")
        with patch("resource_search.search_source", return_value=SearchPage([self.song(), second])) as search:
            self.dialog.load_more()
            self.wait_until(lambda: not self.dialog.pending)
        search.assert_called_once_with("midiworld", "测试", 2)
        self.assertEqual(len(self.dialog.songs), 2)
        self.assertEqual(self.dialog.tree.selection(), previous)
        self.assertFalse(self.dialog.more)

    def test_login_source_disables_direct_download_and_opens_real_page(self):
        song = SearchSong("midishow", "稻香", "https://www.midishow.com/midi/42895.html")
        self.search([song])
        self.assertEqual(str(self.dialog.download_button["state"]), "disabled")
        with patch("resource_search_ui.webbrowser.open") as open_page:
            self.dialog.open_source()
        open_page.assert_called_once_with(song.page_url)

    def test_close_and_account_switch_cancel_work_and_ignore_late_download(self):
        self.search([self.song()])
        old_queue = self.dialog.events
        original = self.app.current_source
        self.app._close_online_library_dialog()
        self.assertTrue(self.dialog.download_cancel.is_set())
        old_queue.put(("download", (self.song(), Path("wrong.mid"), True, None)))
        self.root.update()
        self.assertEqual(self.app.current_source, original)
        self.assertIsNone(self.app.resource_search)

    def test_actual_profile_change_closes_dialog(self):
        self.app.library_dir = Path(self.folder.name) / "another-account"
        self.wait_until(lambda: self.dialog.closed)
        self.assertTrue(self.dialog.search_cancel.is_set())

    def test_error_state_keeps_result_list_and_controls_visible_at_minimum_size(self):
        self.search([self.song()])
        for source in self.dialog.enabled:
            self.dialog.source_status[source] = "不可用：HTTP Error 403: Forbidden，请在源站完成验证后重试"
        self.dialog._summary()
        for size in ("960x680", "860x630"):
            self.dialog.dialog.geometry(size)
            self.root.update()
            self.assertGreaterEqual(self.dialog.tree.winfo_height(), 80)
            for button in (self.dialog.search_button, self.dialog.download_button, self.dialog.preview_button):
                bottom = button.winfo_rooty() + button.winfo_height() - self.dialog.dialog.winfo_rooty()
                self.assertLessEqual(bottom, self.dialog.dialog.winfo_height())


if __name__ == "__main__":
    unittest.main(verbosity=2)
