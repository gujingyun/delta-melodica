"""只对自建测试窗口验证悬浮窗，不向真实游戏发送输入。"""
import ctypes as ct
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App
from win_input import (Hotkeys, INPUT, WindowsOutput, activate_window, foreground, mouse_event,
                       root_window, window_info, _get_window_long, user32)

FIXTURE = r'''
import json, sys, tkinter as tk
from pathlib import Path
from win_input import root_window, window_info
root = tk.Tk()
root.title("悬浮窗集成靶窗口")
root.geometry("1000x700+20+20")
root.configure(bg="#334652")
canvas = tk.Canvas(root, bg="#334652", highlightthickness=0)
canvas.pack(fill="both", expand=True)
canvas.create_text(650, 300, text="本地悬浮窗测试\n\n检查焦点与鼠标穿透", font=("Microsoft YaHei UI", 20), fill="#c5d7d5")
root.update()
Path(sys.argv[1]).write_text(json.dumps(window_info(root_window(root.winfo_id()))), encoding="utf-8")
root.bind("<ButtonPress-1>", lambda e: Path(sys.argv[2]).write_text("clicked", encoding="utf-8"))
root.after(60000, root.destroy)
root.mainloop()
'''


class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work_dir = Path(__file__).resolve().parent / "work"
        work_dir.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="overlay-test-", dir=work_dir)
        cls.folder = Path(cls.temp.name)
        info, cls.clicked = cls.folder / "window.json", cls.folder / "clicked.txt"
        cls.fixture = subprocess.Popen([sys.executable, "-c", FIXTURE, str(info), str(cls.clicked)], cwd=Path(__file__).parent)
        deadline = time.monotonic()+5
        while not info.exists() and time.monotonic() < deadline:
            time.sleep(0.03)
        cls.target = tuple(json.loads(info.read_text(encoding="utf-8")))
        cls.root = tk.Tk()
        cls.app = App(cls.root, cls.folder / "data", smoke=True)
        cls.app.settings["target"] = "悬浮窗集成靶窗口"
        cls.overlay = cls.app.overlay
        cls.root.withdraw()
        cls.overlay.target = cls.target
        cls.overlay.x, cls.overlay.y = 80, 90
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.close()
        cls.fixture.terminate()
        cls.fixture.wait(timeout=3)
        cls.temp.cleanup()

    def pump(self, duration=0.2):
        deadline = time.monotonic()+duration
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)

    def setUp(self):
        self.app.busy = False
        self.overlay.enabled = True
        self.overlay.editing = False
        self.overlay.window.geometry(f"440x186+80+90")
        self.root.deiconify()
        self.root.focus_force()
        self.pump(0.05)
        activate_window(self.target)
        self.root.withdraw()
        self.pump()

    def test_01_hud_visible_without_taking_game_focus(self):
        self.assertTrue(self.overlay.visible)
        self.assertEqual(foreground()[:2], self.target[:2])
        style = _get_window_long(self.overlay.hwnd, -20)
        self.assertTrue(style & 0x20)
        self.assertTrue(style & 0x08000000)
        self.assertAlmostEqual(float(self.overlay.window.attributes("-alpha")), 0.82, places=2)

    def test_02_actual_mouse_click_passes_through_hud(self):
        user32.GetCursorPos.argtypes = (ct.POINTER(wt.POINT),)
        user32.SetCursorPos.argtypes = (ct.c_int, ct.c_int)
        previous = wt.POINT()
        user32.GetCursorPos(ct.byref(previous))
        try:
            self.assertEqual(foreground()[:2], self.target[:2])
            user32.SetCursorPos(200, 160)
            WindowsOutput._native_send([mouse_event("left", True), mouse_event("left", False)])
            self.pump()
            self.assertTrue(self.clicked.exists(), "点击必须落到自建靶窗口")
            self.assertEqual(foreground()[:2], self.target[:2])
        finally:
            user32.SetCursorPos(previous.x, previous.y)

    def test_03_edit_panel_selects_song_and_returns_focus(self):
        self.overlay.begin_edit()
        self.pump()
        self.assertTrue(self.overlay.editing)
        self.assertEqual(foreground()[0], self.overlay.hwnd)
        self.assertFalse(_get_window_long(self.overlay.hwnd, -20) & 0x20)
        self.overlay.select(1)
        self.assertEqual(self.app.song.title, "欢乐颂")
        self.overlay.return_to_game()
        self.pump()
        self.assertEqual(foreground()[:2], self.target[:2])
        self.assertTrue(_get_window_long(self.overlay.hwnd, -20) & 0x20)

    def test_04_play_only_after_focus_and_passthrough_restored(self):
        calls = []
        original = self.app.play
        self.app.play = lambda preview=False: calls.append((foreground()[:2], _get_window_long(self.overlay.hwnd, -20)))
        try:
            self.overlay.begin_edit()
            self.pump()
            self.overlay.return_to_game(start=True)
            self.pump(0.3)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], self.target[:2])
            self.assertTrue(calls[0][1] & 0x20)
        finally:
            self.app.play = original

    def test_05_opacity_saved_and_busy_selection_ignored(self):
        self.overlay.begin_edit()
        self.pump()
        self.overlay.change_alpha()
        data = json.loads(self.overlay.config_path.read_text(encoding="utf-8"))
        self.assertAlmostEqual(data["alpha"], 0.96)
        previous = self.app.song.title
        self.app.busy = True
        self.overlay.select(2)
        self.assertEqual(self.app.song.title, previous)
        self.app.busy = False
        self.overlay.alpha = 0.82
        self.overlay.window.attributes("-alpha", 0.82)

    def test_06_hides_when_leaving_game(self):
        self.root.deiconify()
        self.root.update()
        activate_window(window_info(root_window(self.root.winfo_id())))
        self.pump()
        self.assertFalse(self.overlay.visible)
        self.root.withdraw()

    def test_07_close_main_keeps_real_f6_hotkey_and_f7_panel(self):
        states = []
        hotkeys = Hotkeys(lambda: None, lambda: None, lambda text: None, states.append,
                          visibility=lambda: self.app.events.put(("overlay_visibility", None)))
        try:
            deadline = time.monotonic()+3
            while not states and time.monotonic() < deadline:
                self.pump(0.03)
            self.assertTrue(states and "F6 就绪" in states[0], "测试前请关闭其他注册 F6 的程序")
            self.root.tk.call(self.root.protocol("WM_DELETE_WINDOW"))
            self.assertEqual(self.root.state(), "withdrawn")
            self.assertFalse(self.app.closing)
            # 真实注册的全局热键由 Windows 分发，只在自建靶窗口前发送。
            for visible in (False, True):
                self.assertEqual(foreground()[:2], self.target[:2])
                down, up = INPUT(type=1), INPUT(type=1)
                down.ki.wVk = up.ki.wVk = 0x75
                up.ki.dwFlags = 2
                WindowsOutput._native_send([down, up])
                self.pump(0.3)
                self.assertEqual(self.overlay.visible, visible)
                self.assertEqual(foreground()[:2], self.target[:2])
                self.assertEqual(self.root.state(), "withdrawn")
                saved = json.loads(self.overlay.config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["enabled"], visible)
            self.app.events.put(("overlay", None))
            self.pump()
            self.assertTrue(self.overlay.editing)
            self.assertTrue(self.overlay.visible)
            self.assertEqual(self.root.state(), "withdrawn")
            self.overlay.return_to_game()
        finally:
            hotkeys.close()
        self.assertFalse(hotkeys.thread.is_alive())
        self.assertTrue(user32.RegisterHotKey(None, 904, 0x4000, 0x75), "退出后应释放 F6")
        user32.UnregisterHotKey(None, 904)

    def test_08_desktop_toggle_does_not_require_a_game(self):
        original = self.app.settings["target"]
        try:
            self.app.settings["target"] = "不存在的悬浮窗测试游戏"
            self.overlay.target = None
            self.root.deiconify()
            self.root.update()
            activate_window(window_info(root_window(self.root.winfo_id())))
            self.pump()
            self.app.hide_main()
            self.app.events.put(("overlay_visibility", None))
            self.pump()
            self.assertTrue(self.overlay.visible)
            self.assertTrue(self.overlay.editing)
            self.app.events.put(("overlay_visibility", None))
            self.pump()
            self.assertFalse(self.overlay.visible)
            self.assertFalse(self.overlay.enabled)
            self.assertFalse(self.overlay.editing)
            self.assertNotEqual(self.app.status.get(), "请先进入游戏")
        finally:
            self.app.settings["target"] = original

    def test_09_hud_visibility_does_not_stop_playback(self):
        with patch.object(self.app, "stop") as stop:
            self.app.busy = True
            try:
                self.overlay.toggle_visibility()
                self.assertFalse(self.overlay.visible)
                self.overlay.toggle_visibility()
                self.assertTrue(self.overlay.visible)
                self.assertFalse(self.overlay.editing)
                self.assertEqual(foreground()[:2], self.target[:2])
                stop.assert_not_called()
            finally:
                self.app.busy = False


if __name__ == "__main__":
    unittest.main(verbosity=2)
