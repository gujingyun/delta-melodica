"""验证音频扒谱结果与桌面曲库、试听、编辑和退出的衔接。"""
import gc
import json
from pathlib import Path
import queue
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from app import App
from cloud_score import from_song
from music import parse_jianpu


class AudioDialogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.app = App(self.root, self.temp.name, smoke=True)
        self.app.overlay.enabled = False
        self.dialog = self.app.audio_transcription_dialog()
        self.root.update()
        self.result = self.app.library_dir / "audio__测试扒谱.json"
        data = from_song(parse_jianpu("1 2 3", 120, "测试扒谱"))
        data["transcription"] = {"mode": "vocal", "start": 0}
        self.result.write_text(json.dumps(data), encoding="utf-8")

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()
        self.dialog = self.app = self.root = None
        gc.collect()

    def pump(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(.01)
        self.fail("等待扒谱界面事件超时")

    def fake_job(self):
        job = Mock(active=False, events=queue.Queue(), cancelled=threading.Event())
        job.cancel.side_effect = job.cancelled.set
        return job

    def complete(self):
        job = self.fake_job()
        self.dialog.job = job
        job.events.put(("done", (self.result, 3, 1.5)))
        self.pump(lambda: self.dialog.result_path == self.result)

    def test_start_passes_selected_file_mode_and_clip_and_disables_duplicate_actions(self):
        job = self.fake_job()
        self.dialog.path.set("C:/测试.mp3")
        self.dialog.mode.set("solo")
        self.dialog.start_seconds.set("12.5")
        self.dialog.duration.set("整首")
        with patch("audio_transcription_ui.AudioTranscription", return_value=job) as factory:
            self.dialog.run()
        options = factory.call_args.args[3]
        self.assertEqual((options.mode, options.start, options.duration), ("solo", 12.5, None))
        job.start.assert_called_once()
        self.assertEqual(str(self.dialog.browse_button["state"]), "disabled")
        self.assertEqual(str(self.dialog.cancel_button["state"]), "normal")

    def test_result_enters_library_and_enables_preview_without_game_output(self):
        self.complete()
        self.assertEqual(self.app.current_source, ("file", self.result))
        self.assertIn("AI 音频扒谱", self.app.subtitle.get())
        self.assertTrue(self.app.plan.notes)
        self.assertFalse(self.app.player.active)
        self.assertEqual(str(self.dialog.preview_button["state"]), "normal")
        self.assertIn("[扒谱]", self.app.library.get(self.app.library.curselection()[0]))

    def test_preview_releases_modal_before_play_and_editor_can_open_same_result(self):
        self.complete()
        def preview(**kwargs):
            self.assertIsNone(self.root.grab_current())
            self.assertEqual(kwargs, {"preview": True})
        with patch.object(self.app, "play", side_effect=preview) as play:
            self.dialog.preview()
        play.assert_called_once()
        self.dialog = self.app.audio_transcription_dialog()
        self.dialog.result_path = self.result
        with patch.object(self.app, "edit_song") as edit:
            self.dialog.edit()
        edit.assert_called_once()

    def test_close_cancels_engine_and_late_result_cannot_change_song(self):
        job = self.fake_job()
        self.dialog.job = job
        original = self.app.current_source
        self.dialog.close()
        job.events.put(("done", (self.result, 3, 1.5)))
        self.root.update()
        self.assertTrue(job.cancelled.is_set())
        self.assertEqual(self.app.current_source, original)
        self.assertIsNone(self.app.audio_dialog)

    def test_profile_switch_closes_old_job(self):
        self.dialog.job = self.fake_job()
        self.app.library_dir = Path(self.temp.name) / "other-account"
        self.pump(lambda: self.dialog.closed)
        self.assertTrue(self.dialog.job.cancelled.is_set())

    def test_worker_error_can_retry_without_losing_previous_library(self):
        self.dialog.job = self.fake_job()
        original = self.app.current_source
        self.dialog.job.events.put(("error", "没有清晰人声"))
        self.pump(lambda: "没有清晰人声" in self.dialog.status.get())
        self.assertEqual(str(self.dialog.run_button["state"]), "normal")
        self.assertEqual(self.app.current_source, original)

    def test_small_window_keeps_cancel_and_preview_visible(self):
        self.dialog.dialog.geometry("740x510")
        self.root.update()
        for button in (self.dialog.run_button, self.dialog.cancel_button, self.dialog.preview_button, self.dialog.edit_button):
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                 self.dialog.dialog.winfo_rooty() + self.dialog.dialog.winfo_height())


if __name__ == "__main__":
    unittest.main()
