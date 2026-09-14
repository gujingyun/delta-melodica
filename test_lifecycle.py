"""验证托盘入口、窗口隐藏与彻底退出时的资源清理。"""
import gc
import json
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App
from music import Mapping, compile_plan, parse_jianpu
from test_music import FakeOutput
from tray import Tray


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.app = App(self.root, self.folder.name, smoke=True)
        self.root.update()

    def tearDown(self):
        if self.app.score_editor:
            self.app.score_editor.close(force=True)
        self.app.close()
        self.folder.cleanup()
        # Tk 对象必须由主线程回收，避免下一项托盘测试在线程中触发循环回收。
        self.app = self.root = None
        gc.collect()

    def pump(self, condition, timeout=3):
        deadline = time.monotonic()+timeout
        while not condition() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(condition(), "等待界面事件超时")

    def test_tray_restores_main_and_exit_releases_player(self):
        self.app.tray = Tray(lambda kind, value: self.app.events.put((kind, value)))
        tray = self.app.tray
        self.pump(lambda: tray.available)
        self.app.smoke = False
        self.root.tk.call(self.root.protocol("WM_DELETE_WINDOW"))
        self.assertEqual(self.root.state(), "withdrawn")
        self.assertTrue(tray.available)
        # 使用托盘公开菜单的真实回调，验证后台事件到 Tk 主线程的完整路径。
        next(item for item in tray.icon.menu.items if item.text == "打开主窗口")(tray.icon)
        self.pump(lambda: self.root.state() == "normal")
        self.assertFalse(self.app.closing)

        output = FakeOutput()
        plan = compile_plan(parse_jianpu("1:8", 60), Mapping())
        self.app.player.start(plan, lambda: output)
        self.assertTrue(output.started.wait(1))
        self.root.tk.call(self.root.protocol("WM_DELETE_WINDOW"))
        self.assertTrue(self.app.player.active, "隐藏主窗口不能结束后台播放")
        next(item for item in tray.icon.menu.items if item.text == "退出")(tray.icon)
        self.pump(lambda: self.app.closing)
        self.assertFalse(self.app.player.active)
        self.assertTrue(output.closed)
        self.assertFalse(output.held)
        self.assertFalse(tray.thread.is_alive())
        self.assertTrue(self.app.overlay.closed)
        with self.assertRaises(tk.TclError):
            self.root.winfo_exists()
        self.app.close()

    def test_tray_unavailable_keeps_main_and_offers_exit(self):
        self.app.smoke = False
        self.app.hide_main()
        self.assertEqual(self.root.state(), "normal")
        self.root.withdraw()
        self.app.events.put(("tray_error", "模拟托盘故障"))
        self.pump(lambda: self.app.exit_button.winfo_ismapped())
        self.assertEqual(self.root.state(), "normal")
        self.assertIn("模拟托盘故障", self.app.detail.get())
        self.assertFalse(self.app.closing)

    def test_cancel_tray_exit_preserves_draft_releases_preview_and_keeps_polling(self):
        self.app.edit_song()
        editor = self.app.score_editor
        editor.name.set("未保存的草稿")
        output = FakeOutput()
        editor.player.start(compile_plan(parse_jianpu("1:8", 60), Mapping()), lambda: output)
        self.assertTrue(output.started.wait(1))
        def cancel(*args, **kwargs):
            self.assertTrue(output.closed)
            self.assertFalse(output.held)
            self.assertFalse(self.app.close(), "重复退出不能绕过当前确认框")
            with patch("app.PreviewOutput") as preview:
                self.app.play(preview=True)
                preview.assert_not_called()
            return None
        with patch("score_editor.messagebox.askyesnocancel", side_effect=cancel) as question:
            self.app.events.put(("exit", None))
            self.pump(lambda: question.called)
        self.assertFalse(self.app.closing)
        self.assertIs(self.app.score_editor, editor)
        self.assertEqual(editor.name.get(), "未保存的草稿")
        question.assert_called_once()
        self.app.events.put(("warning", "取消退出后仍在处理事件"))
        self.pump(lambda: self.app.detail.get() == "取消退出后仍在处理事件")
        self.assertFalse(self.app.player.active)

    def test_tray_exit_can_save_draft_before_closing(self):
        self.app.edit_song()
        editor = self.app.score_editor
        editor.name.set("退出前保存")
        with patch("score_editor.messagebox.askyesnocancel", return_value=True):
            self.app.events.put(("exit", None))
            self.pump(lambda: self.app.closing)
        self.assertTrue(self.app.closing)
        self.assertIsNotNone(editor.saved_path)
        data = json.loads(editor.saved_path.read_text(encoding="utf-8"))
        self.assertEqual(data["title"], "退出前保存")
        self.assertTrue(data["notes"])

    def test_exit_save_failure_keeps_window_and_draft(self):
        self.app.edit_song()
        editor = self.app.score_editor
        editor.name.set("不能丢失的草稿")
        with patch("score_editor.messagebox.askyesnocancel", return_value=True), \
                patch("score_editor.atomic_json", side_effect=OSError("测试磁盘写入失败")), \
                patch("score_editor.messagebox.showerror") as error:
            self.app.close()
        self.assertFalse(self.app.closing)
        self.assertIs(self.app.score_editor, editor)
        self.assertEqual(editor.name.get(), "不能丢失的草稿")
        error.assert_called_once()

    def test_fallback_exit_button_uses_same_unsaved_confirmation(self):
        self.app.events.put(("tray_error", "模拟托盘故障"))
        self.pump(lambda: self.app.exit_button.winfo_ismapped())
        self.app.edit_song()
        self.app.score_editor.name.set("待放弃的草稿")
        with patch("score_editor.messagebox.askyesnocancel", return_value=None):
            self.app.exit_button.invoke()
        self.assertFalse(self.app.closing)
        with patch("score_editor.messagebox.askyesnocancel", return_value=False) as question:
            self.app.exit_button.invoke()
        question.assert_called_once()
        self.assertTrue(self.app.closing)
        self.assertFalse(list(self.app.library_dir.glob("*.json")))

    def test_modal_form_is_not_stranded_by_main_close(self):
        dialog = self.app._dialog("测试设置", "300x150")
        self.root.update()
        self.app.hide_main()
        self.assertEqual(self.root.state(), "normal")
        self.assertEqual(self.root.grab_current(), dialog)
        dialog.destroy()
        self.app.hide_main()
        self.assertEqual(self.root.state(), "withdrawn")

    def test_tray_immediate_shutdown_does_not_leave_thread(self):
        tray = Tray(lambda kind, value: None)
        tray.close()
        self.assertFalse(tray.thread.is_alive())
        self.assertFalse(tray.available)

    def test_main_layout_keeps_preview_and_controls_visible(self):
        """默认和最小窗口均保留旋律空间，参数和停止入口不会被挤出。"""
        for size in ("1180x840", "1040x780"):
            with self.subTest(size=size):
                self.root.geometry(size)
                self.root.update()
                self.assertGreaterEqual(self.app.roll.winfo_height(), 40)
                for widget in (self.app.track_combo, self.app.speed_combo,
                               self.app.transpose_combo, self.app.style_combo,
                               self.app.play_button, self.app.stop_button, self.app.footer):
                    self.assertTrue(widget.winfo_ismapped())
                    right = widget.winfo_rootx() + widget.winfo_width()
                    bottom = widget.winfo_rooty() + widget.winfo_height()
                    self.assertLessEqual(right, self.root.winfo_rootx() + self.root.winfo_width())
                    self.assertLessEqual(bottom, self.root.winfo_rooty() + self.root.winfo_height())


if __name__ == "__main__":
    unittest.main(verbosity=2)
