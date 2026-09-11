"""通过真实 Tk 事件验证暂停续播和进度拖动，播放输出全部使用模拟后端。"""
from contextlib import ExitStack
import gc
import tempfile
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import App
from music import parse_jianpu
from test_music import FakeOutput


class RecordedOutput(FakeOutput):
    def __init__(self):
        super().__init__()
        self.pitches = []

    def begin(self, fingering):
        self.pitches.append(fingering.pitch)
        super().begin(fingering)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.app = App(self.root, self.folder.name, smoke=True)
        self.app.overlay.enabled = False
        self.app.song = parse_jianpu("1:4 0 2:4 3:4", 60)
        self.app.rebuild_plan()
        self.app.settings["target"], self.app.settings["countdown"] = "测试游戏", 0
        self.outputs = []
        self.patches = ExitStack()
        self.patches.enter_context(patch("app.foreground", return_value=(123, 456, "测试游戏")))
        self.patches.enter_context(patch("app.process_elevated", return_value=True))
        self.patches.enter_context(patch("app.permission_problem", return_value=None))
        self.patches.enter_context(patch("app.WindowsOutput", side_effect=lambda target: self.output()))
        self.patches.enter_context(patch("app.PreviewOutput", side_effect=self.output))
        self.root.update()

    def tearDown(self):
        self.app.close()
        self.patches.close()
        self.folder.cleanup()
        self.app = self.root = None
        gc.collect()

    def output(self):
        output = RecordedOutput()
        self.outputs.append(output)
        return output

    def pump(self, condition, timeout=2):
        deadline = time.monotonic()+timeout
        while not condition() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.005)
        self.assertTrue(condition(), "等待播放界面状态超时")

    def f8(self):
        self.app.events.put(("toggle", None))

    def wait_playing(self, count=1):
        self.pump(lambda: len(self.outputs) >= count and self.outputs[-1].held and self.app.busy)

    def test_f8_pauses_and_resumes_from_the_frozen_position(self):
        self.f8()
        self.wait_playing()
        self.f8()
        self.pump(lambda: self.app.player.paused and not self.app.busy)
        position = self.app.player.position
        self.assertGreater(position, 0)
        self.assertTrue(self.outputs[0].closed)
        self.assertIn("继续", self.app.play_button["text"])
        self.f8()
        self.wait_playing(2)
        self.assertGreaterEqual(self.app.player.position, position)
        self.assertLess(self.app.player.position, position+0.5)
        self.assertIn("暂停", self.app.play_button["text"])

    def test_main_slider_drag_pauses_and_resumes_at_the_selected_note(self):
        self.app.play(True)
        self.wait_playing()
        widget = self.app.progress
        width = widget.winfo_width()-16
        widget.event_generate("<ButtonPress-1>", x=round(8+width*0.25), y=8)
        widget.event_generate("<B1-Motion>", x=round(8+width*0.75), y=8)
        widget.event_generate("<ButtonRelease-1>", x=round(8+width*0.75), y=8)
        self.pump(lambda: not self.app.busy)
        position = self.app.player.position
        self.assertAlmostEqual(position, self.app.plan.duration*0.75, delta=0.05)
        self.assertTrue(self.outputs[0].closed)
        self.assertTrue(self.app.player.paused)
        self.assertFalse(self.app.seeking)
        self.app.play(True)
        self.wait_playing(2)
        self.assertEqual(self.outputs[-1].pitches[0], 64)
        self.assertGreaterEqual(self.app.player.position, position)

    def test_overlay_progress_drag_updates_the_same_cursor(self):
        overlay = self.app.overlay
        overlay.editing = True
        overlay._press(SimpleNamespace(x=118, y=105))
        overlay._drag(SimpleNamespace(x=322, y=105))
        overlay._release(SimpleNamespace(x=322, y=105))
        self.assertAlmostEqual(self.app.player.position, self.app.plan.duration*0.75)
        self.assertAlmostEqual(float(self.app.progress["value"]), 75)
        self.assertTrue(self.app.player.paused)
        self.assertFalse(self.app.seeking)
        self.assertFalse(overlay.seek_drag)

    def test_f9_during_drag_wins_over_mouse_release(self):
        self.app.begin_seek()
        self.app.seek_fraction(0.4)
        self.app.stop("F9")
        self.app.seek_fraction(0.8)
        self.app.end_seek()
        self.pump(lambda: "回到曲首" in self.app.status.get())
        self.assertEqual(self.app.player.position, 0)
        self.assertFalse(self.app.player.paused)
        self.assertEqual(float(self.app.progress["value"]), 0)

    def test_new_seek_is_not_overwritten_by_an_older_stop_event(self):
        self.app.stop("F9")
        self.app.begin_seek()
        self.app.seek_fraction(0.5)
        self.app.end_seek()
        self.root.update()
        self.assertEqual(self.app.player.position, self.app.plan.duration*0.5)
        self.assertTrue(self.app.player.paused)

    def test_fast_resume_ignores_previous_run_completion(self):
        self.app.play(True)
        self.wait_playing()
        old_run = self.app.player.run_id
        self.app.pause()
        self.app.play(True)
        self.wait_playing(2)
        self.app.events.put(("player", (old_run, "done", ("已暂停", None))))
        self.app.events.put(("warning", "旧事件已处理"))
        self.pump(lambda: self.app.detail.get() == "旧事件已处理")
        self.assertTrue(self.app.busy)
        self.assertTrue(self.app.player.active)

    def test_f9_cancels_delayed_overlay_start(self):
        with patch.object(self.app.overlay, "game_window", return_value=(123, 456, "测试游戏")), \
                patch("overlay.activate_window"), patch.object(self.app, "play") as play:
            self.app.overlay.return_to_game(start=True)
            self.app.stop("F9")
            complete = []
            self.root.after(200, lambda: complete.append(True))
            self.pump(lambda: bool(complete))
            play.assert_not_called()

    def test_changing_song_parameters_resets_the_cursor(self):
        self.app.begin_seek()
        self.app.seek_fraction(0.5)
        self.app.end_seek()
        self.app.arrangement.set("钢琴适配 · 连奏")
        self.app.rebuild_plan()
        self.assertEqual(self.app.player.position, 0)
        self.assertFalse(self.app.player.paused)
        self.assertEqual(float(self.app.progress["value"]), 0)

    def test_live_combobox_changes_keep_run_and_update_current_pitch(self):
        self.app.play(True)
        self.wait_playing()
        run_id = self.app.player.run_id
        original = self.app.plan
        self.assertEqual(str(self.app.speed_combo["state"]), "readonly")
        self.assertEqual(str(self.app.transpose_combo["state"]), "readonly")
        self.assertEqual(str(self.app.track_combo["state"]), "disabled")
        self.assertEqual(str(self.app.style_combo["state"]), "disabled")
        self.app.speed.set("2.00")
        self.app.speed_combo.event_generate("<<ComboboxSelected>>")
        self.app.transpose.set("1")
        self.app.transpose_combo.event_generate("<<ComboboxSelected>>")
        self.pump(lambda: self.outputs[0].pitches[-1] == 61 and self.app.current_note is self.app.plan.notes[0])
        self.assertEqual(self.app.plan.duration, original.duration/2)
        self.assertEqual(self.app.player.run_id, run_id)
        self.assertEqual(len(self.outputs), 1)
        self.assertFalse(self.outputs[0].closed)
        self.assertTrue(self.app.busy)
        self.app.events.put(("player", (run_id, "note", (0, original.notes[0]))))
        self.app.events.put(("warning", "旧音符已处理"))
        self.pump(lambda: self.app.detail.get() == "旧音符已处理")
        self.assertEqual(self.app.current_note.fingering.pitch, 61)

    def test_paused_adjustments_preserve_fraction_and_resume_new_pitch(self):
        self.app.begin_seek()
        self.app.seek_fraction(0.5)
        self.app.end_seek()
        self.app.change_speed(3)
        self.app.change_transpose(1)
        self.assertTrue(self.app.player.paused)
        self.assertEqual(self.app.player.position, self.app.plan.duration/2)
        self.assertEqual(float(self.app.progress["value"]), 50)
        self.app.play(True)
        self.wait_playing()
        self.assertEqual(self.outputs[0].pitches[0], 63)

    def test_hotkey_events_and_overlay_share_controls_without_restarting(self):
        self.app.play(False)
        self.wait_playing()
        run_id = self.app.player.run_id
        self.app.events.put(("speed", 1))
        self.app.events.put(("transpose", -1))
        self.pump(lambda: self.app.speed.get() == "1.25" and self.outputs[0].pitches[-1] == 59)
        self.app.overlay.change_speed(-1)
        self.assertEqual(self.app.speed.get(), "1.00")
        self.assertEqual(self.app.player.run_id, run_id)
        self.assertTrue(self.app.busy)
        self.app.stop("F9")
        self.app.events.put(("speed", 1))
        self.pump(lambda: not self.app.busy and self.app.speed.get() == "1.25")
        self.assertEqual(self.app.player.position, 0)
        self.assertFalse(self.app.player.paused)
        self.assertTrue(self.outputs[0].closed)

    def test_parameter_limits_and_invalid_change_preserve_current_plan(self):
        self.app.change_speed(100)
        self.app.change_transpose(100)
        self.assertEqual((self.app.speed.get(), self.app.transpose.get()), ("2.00", "24"))
        self.app.change_speed(-100)
        self.app.change_transpose(-100)
        self.assertEqual((self.app.speed.get(), self.app.transpose.get()), ("0.25", "-24"))
        plan = self.app.plan
        self.app.speed.set("nan")
        self.app.rebuild_plan(preserve_position=True)
        self.assertIs(self.app.plan, plan)
        self.assertEqual(self.app.speed.get(), "0.25")
        self.assertIn("速度倍率", self.app.detail.get())

    def test_resizing_paused_window_keeps_the_preview_at_the_cursor(self):
        self.app.begin_seek()
        self.app.seek_fraction(0.5)
        self.app.end_seek()
        position = self.app.player.position
        self.root.geometry("1200x850")
        self.root.update()
        cursor = self.app.roll.find_all()[-1]
        self.assertGreater(self.app.roll.coords(cursor)[0], 50)
        self.assertEqual(self.app.player.position, position)
        self.assertEqual(float(self.app.progress["value"]), 50)


if __name__ == "__main__":
    unittest.main(verbosity=2)
