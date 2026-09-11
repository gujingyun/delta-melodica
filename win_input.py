"""Windows 输入、窗口识别与本地 MIDI 试听。"""
from __future__ import annotations

import ctypes as ct
from ctypes import wintypes as wt
import os
import threading

user32 = ct.WinDLL("user32", use_last_error=True)
winmm = ct.WinDLL("winmm", use_last_error=True)


class MOUSEINPUT(ct.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ct.c_size_t)]


class KEYBDINPUT(ct.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ct.c_size_t)]


class HARDWAREINPUT(ct.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class INPUTUNION(ct.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ct.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", wt.DWORD), ("value", INPUTUNION)]


user32.SendInput.argtypes = (wt.UINT, ct.POINTER(INPUT), ct.c_int)
user32.SendInput.restype = wt.UINT
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowTextLengthW.argtypes = (wt.HWND,)
user32.GetWindowTextW.argtypes = (wt.HWND, wt.LPWSTR, ct.c_int)
user32.GetWindowThreadProcessId.argtypes = (wt.HWND, ct.POINTER(wt.DWORD))
user32.MapVirtualKeyW.argtypes = (wt.UINT, wt.UINT)
user32.MapVirtualKeyW.restype = wt.UINT
user32.RegisterHotKey.argtypes = (wt.HWND, ct.c_int, wt.UINT, wt.UINT)
user32.UnregisterHotKey.argtypes = (wt.HWND, ct.c_int)
user32.PeekMessageW.argtypes = (ct.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT)
winmm.midiOutOpen.argtypes = (ct.POINTER(ct.c_void_p), wt.UINT, ct.c_size_t, ct.c_size_t, wt.DWORD)
winmm.midiOutShortMsg.argtypes = (ct.c_void_p, wt.DWORD)
winmm.midiOutReset.argtypes = (ct.c_void_p,)
winmm.midiOutClose.argtypes = (ct.c_void_p,)

SCAN_CODES = {"z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30,
              "n": 0x31, "m": 0x32, ",": 0x33, ".": 0x34, "/": 0x35,
              ";": 0x27, "[": 0x1A, "]": 0x1B, "-": 0x0C, "=": 0x0D}
MOUSE_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}


def foreground() -> tuple[int, int, str]:
    hwnd = user32.GetForegroundWindow()
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ct.byref(pid))
    size = user32.GetWindowTextLengthW(hwnd) + 1
    buffer = ct.create_unicode_buffer(max(1, size))
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return hwnd or 0, pid.value, buffer.value


def target_matches(window: tuple[int, int, str], keywords: str) -> bool:
    hwnd, pid, title = window
    words = [s.strip().casefold() for s in keywords.split("|") if s.strip()]
    return bool(hwnd and pid != os.getpid() and words and any(w in title.casefold() for w in words))


def keyboard_event(key: str, down: bool) -> INPUT:
    scan = SCAN_CODES.get(key.lower())
    if scan is None:
        scan = user32.MapVirtualKeyW(ord(key.upper()), 0)
    if not scan:
        raise ValueError(f"无法映射按键：{key}")
    return INPUT(type=1, ki=KEYBDINPUT(0, scan, 0x0008 | (0 if down else 0x0002), 0, 0))


def mouse_event(button: str, down: bool) -> INPUT:
    return INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, MOUSE_FLAGS[button][0 if down else 1], 0, 0))


class WindowsOutput:
    def __init__(self, target: tuple[int, int, str], send=None, get_foreground=foreground):
        self.target = target
        self._foreground = get_foreground
        self._send = send or self._native_send
        self.held: list[tuple[str, str]] = []

    @staticmethod
    def _native_send(events):
        array = (INPUT * len(events))(*events)
        sent = user32.SendInput(len(array), array, ct.sizeof(INPUT))
        if sent != len(array):
            raise OSError(f"Windows 未完整接收模拟输入（{sent}/{len(array)}），请检查窗口权限。")

    def check(self):
        if self._foreground()[:2] != self.target[:2]:
            raise RuntimeError("已切出目标窗口，演奏自动停止。")

    def begin(self, fingering):
        self.check()
        # 发送前记录可能按下的键，部分发送失败时也能可靠执行释放。
        for button in fingering.buttons:
            self.held.append(("mouse", button))
            self._send([mouse_event(button, True)])
        self.check()
        self.held.append(("key", fingering.key))
        self._send([keyboard_event(fingering.key, True)])

    def release(self):
        errors = []
        # 先松开音符，再松开鼠标修饰键；每个释放独立尝试。
        for kind, value in list(reversed(self.held)):
            event = keyboard_event(value, False) if kind == "key" else mouse_event(value, False)
            try:
                self._send([event])
                self.held.remove((kind, value))
            except Exception as error:
                errors.append(str(error))
        if errors:
            raise OSError("释放输入失败：" + "；".join(errors))

    def close(self):
        self.release()


class PreviewOutput:
    def __init__(self):
        self.handle = ct.c_void_p()
        result = winmm.midiOutOpen(ct.byref(self.handle), 0xFFFFFFFF, 0, 0, 0)
        if result:
            raise RuntimeError(f"本机 MIDI 合成器无法打开（错误 {result}）。")
        self.pitch = None
        self._message(0xC0 | (22 << 8))

    def _message(self, value):
        if winmm.midiOutShortMsg(self.handle, value):
            raise RuntimeError("本机 MIDI 试听输出失败。")

    def check(self):
        pass

    def begin(self, fingering):
        self.pitch = fingering.pitch
        self._message(0x90 | (self.pitch << 8) | (95 << 16))

    def release(self):
        if self.pitch is not None:
            self._message(0x80 | (self.pitch << 8))
            self.pitch = None

    def close(self):
        if self.handle:
            winmm.midiOutReset(self.handle)
            winmm.midiOutClose(self.handle)
            self.handle = ct.c_void_p()


class Hotkeys:
    def __init__(self, toggle, stop, report):
        self.toggle, self.stop, self.report = toggle, stop, report
        self.exit = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        registered = []
        try:
            for identity, vk, name in ((801, 0x77, "F8"), (802, 0x78, "F9")):
                if user32.RegisterHotKey(None, identity, 0x4000, vk):
                    registered.append(identity)
                else:
                    self.report(f"{name} 被其他程序占用，请关闭占用程序后重启助手。")
            message = wt.MSG()
            while not self.exit.wait(0.015):
                while user32.PeekMessageW(ct.byref(message), None, 0, 0, 1):
                    if message.message == 0x0312:
                        (self.toggle if message.wParam == 801 else self.stop)()
        finally:
            for identity in registered:
                user32.UnregisterHotKey(None, identity)

    def close(self):
        self.exit.set()
        self.thread.join(timeout=1)
