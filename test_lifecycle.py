"""验证托盘入口、窗口隐藏与彻底退出时的资源清理。"""
import gc
import tempfile
import time
import tkinter as tk
import unittest

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
