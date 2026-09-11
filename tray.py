"""Windows 系统托盘；后台回调只投递事件，不直接操作 Tk 窗口。"""
from __future__ import annotations

import threading

from PIL import Image, ImageDraw
import pystray


def tray_image():
    image = Image.new("RGBA", (64, 64))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 62, 62), radius=14, fill="#122125")
    draw.rounded_rectangle((10, 17, 54, 48), radius=5, fill="#b7f17c")
    for x in (19, 28, 37, 46):
        draw.line((x, 19, x, 46), fill="#122125", width=2)
    for x in (17, 26, 44):
        draw.rectangle((x, 18, x+4, 32), fill="#122125")
    return image


class Tray:
    def __init__(self, notify):
        self.notify = notify
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.icon = pystray.Icon("DeltaMelodica", tray_image(), "三角洲口风琴 · F6 显示 / 隐藏悬浮窗", pystray.Menu(
            pystray.MenuItem("打开主窗口", self._action("show_main"), default=True),
            pystray.MenuItem("显示 / 隐藏悬浮窗  F6", self._action("overlay_visibility")),
            pystray.MenuItem("悬浮窗操作面板  F7", self._action("overlay")),
            pystray.MenuItem("停止演奏  F9", self._action("stop")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._action("exit")),
        ))
        self.thread = threading.Thread(target=self._run, name="系统托盘", daemon=True)
        self.thread.start()

    @property
    def available(self):
        return self.ready.is_set() and self.thread.is_alive()

    def _action(self, kind):
        def invoke(icon, item):
            if not self.closed.is_set():
                self.notify(kind, None)
        return invoke

    def _setup(self, icon):
        try:
            if self.closed.is_set():
                icon.stop()
                return
            icon.visible = True
            self.ready.set()
            self.notify("tray_ready", None)
        except Exception as error:
            self.notify("tray_error", str(error))
            icon.stop()

    def _run(self):
        error = "系统托盘已停止"
        try:
            self.icon.run(self._setup)
        except Exception as failure:
            error = str(failure)
        finally:
            self.ready.clear()
            if not self.closed.is_set():
                self.notify("tray_error", error)

    def close(self):
        self.closed.set()
        self.icon.stop()
        self.thread.join(timeout=2)
