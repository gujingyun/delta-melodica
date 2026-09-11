"""Windows 输入、窗口识别与本地 MIDI 试听。"""
from __future__ import annotations

import ctypes as ct
from ctypes import wintypes as wt
import os
from pathlib import Path
import subprocess
import sys
import threading

user32 = ct.WinDLL("user32", use_last_error=True)
winmm = ct.WinDLL("winmm", use_last_error=True)
kernel32 = ct.WinDLL("kernel32", use_last_error=True)
advapi32 = ct.WinDLL("advapi32", use_last_error=True)
shell32 = ct.WinDLL("shell32", use_last_error=True)


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
user32.IsWindowVisible.argtypes = (wt.HWND,)
WNDENUMPROC = ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = (WNDENUMPROC, wt.LPARAM)
user32.GetAncestor.argtypes = (wt.HWND, wt.UINT)
user32.GetAncestor.restype = wt.HWND
user32.IsWindow.argtypes = (wt.HWND,)
user32.IsIconic.argtypes = (wt.HWND,)
user32.ShowWindow.argtypes = (wt.HWND, ct.c_int)
user32.SetForegroundWindow.argtypes = (wt.HWND,)
user32.SetWindowPos.argtypes = (wt.HWND, wt.HWND, ct.c_int, ct.c_int, ct.c_int, ct.c_int, wt.UINT)
_get_window_long = user32.GetWindowLongPtrW if ct.sizeof(ct.c_void_p) == 8 else user32.GetWindowLongW
_set_window_long = user32.SetWindowLongPtrW if ct.sizeof(ct.c_void_p) == 8 else user32.SetWindowLongW
_get_window_long.argtypes = (wt.HWND, ct.c_int)
_get_window_long.restype = ct.c_ssize_t
_set_window_long.argtypes = (wt.HWND, ct.c_int, ct.c_ssize_t)
_set_window_long.restype = ct.c_ssize_t
kernel32.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = (wt.HANDLE,)
advapi32.OpenProcessToken.argtypes = (wt.HANDLE, wt.DWORD, ct.POINTER(wt.HANDLE))
advapi32.GetTokenInformation.argtypes = (wt.HANDLE, ct.c_int, wt.LPVOID, wt.DWORD, ct.POINTER(wt.DWORD))
shell32.ShellExecuteW.argtypes = (wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ct.c_int)
shell32.ShellExecuteW.restype = ct.c_void_p
winmm.midiOutOpen.argtypes = (ct.POINTER(ct.c_void_p), wt.UINT, ct.c_size_t, ct.c_size_t, wt.DWORD)
winmm.midiOutShortMsg.argtypes = (ct.c_void_p, wt.DWORD)
winmm.midiOutReset.argtypes = (ct.c_void_p,)
winmm.midiOutClose.argtypes = (ct.c_void_p,)

SCAN_CODES = {"z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30,
              "n": 0x31, "m": 0x32, ",": 0x33, ".": 0x34, "/": 0x35,
              ";": 0x27, "[": 0x1A, "]": 0x1B, "-": 0x0C, "=": 0x0D}
MOUSE_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}


def window_info(hwnd) -> tuple[int, int, str]:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ct.byref(pid))
    size = user32.GetWindowTextLengthW(hwnd) + 1
    buffer = ct.create_unicode_buffer(max(1, size))
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return hwnd or 0, pid.value, buffer.value


def foreground() -> tuple[int, int, str]:
    return window_info(user32.GetForegroundWindow())


def root_window(hwnd):
    return user32.GetAncestor(hwnd, 2) or hwnd


def overlay_style(hwnd, interactive=False):
    # 观看状态不激活且鼠标穿透，避免演奏时的鼠标变音误触悬浮窗。
    style = _get_window_long(hwnd, -20)
    style |= 0x00080000 | 0x00000080
    style &= ~0x00040000
    if interactive:
        style &= ~(0x00000020 | 0x08000000)
    else:
        style |= 0x00000020 | 0x08000000
    ct.set_last_error(0)
    result = _set_window_long(hwnd, -20, style)
    error = ct.get_last_error()
    if not result and error:
        raise OSError(error, "无法设置悬浮窗样式")
    user32.SetWindowPos(hwnd, wt.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0020)


def activate_window(window):
    hwnd, pid, _ = window
    if not user32.IsWindow(hwnd) or window_info(hwnd)[1] != pid:
        raise RuntimeError("目标窗口已经关闭，请重新进入游戏。")
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    if foreground()[:2] != window[:2] and not user32.SetForegroundWindow(hwnd):
        raise RuntimeError("Windows 没有切回目标窗口，请点击游戏后按 F8。")


def matching_windows(keywords):
    windows = []

    @WNDENUMPROC
    def collect(hwnd, unused):
        if user32.IsWindowVisible(hwnd):
            window = window_info(hwnd)
            if target_matches(window, keywords):
                windows.append(window)
        return True

    user32.EnumWindows(collect, 0)
    return windows


def process_elevated(pid=None) -> bool | None:
    # 仅读取进程权限标志；无法查询时保留“未知”，不猜测游戏状态。
    process = kernel32.OpenProcess(0x1000, False, os.getpid() if pid is None else pid)
    if not process:
        return None
    token = wt.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, 0x0008, ct.byref(token)):
            return None
        value, size = wt.DWORD(), wt.DWORD()
        if not advapi32.GetTokenInformation(token, 20, ct.byref(value), ct.sizeof(value), ct.byref(size)):
            return None
        return bool(value.value)
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(process)


def permission_problem(target_pid, query=process_elevated):
    if query() is False and query(target_pid) is True:
        return "游戏以管理员权限运行，助手当前是普通权限。请点击「以管理员身份重启」，在 Windows 弹窗中确认后再试。"
    return None


def restart_as_admin(data_dir, extra_args=None):
    # 用户点击按钮后才调用系统提权弹窗，取消时保持当前软件运行。
    arguments = ["--data-dir", str(data_dir), *(extra_args or [])]
    if not getattr(sys, "frozen", False):
        arguments.insert(0, str(Path(__file__).with_name("app.py")))
    result = shell32.ShellExecuteW(None, "runas", sys.executable, subprocess.list2cmdline(arguments), str(Path(sys.executable).parent), 1)
    if not result or result <= 32:
        raise OSError("管理员启动被取消或失败，当前助手仍可使用；请重新点击按钮后在 Windows 弹窗中确认。")


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
        ct.set_last_error(0)
        sent = user32.SendInput(len(array), array, ct.sizeof(INPUT))
        if sent != len(array):
            error = ct.get_last_error()
            raise OSError(f"Windows 未接收模拟输入（{sent}/{len(array)}，错误码 {error}）。请确认助手和游戏的权限一致；可点击「以管理员身份重启」后再试。")

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
    def __init__(self, toggle, stop, report, status=None, overlay=None, visibility=None):
        self.toggle, self.stop, self.report = toggle, stop, report
        self.status = status or (lambda text: None)
        self.overlay = overlay
        self.visibility = visibility
        self.exit = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        registered = []
        states = []
        try:
            # 提前建立线程消息队列，热键消息始终在注册它的线程中读取。
            message = wt.MSG()
            user32.PeekMessageW(ct.byref(message), None, 0, 0, 0)
            bindings = [(801, 0x77, "F8"), (802, 0x78, "F9")]
            if self.overlay:
                bindings.insert(0, (803, 0x76, "F7"))
            if self.visibility:
                bindings.insert(0, (804, 0x75, "F6"))
            for identity, vk, name in bindings:
                if user32.RegisterHotKey(None, identity, 0x4000, vk):
                    registered.append(identity)
                    states.append(f"{name} 就绪")
                else:
                    error = ct.get_last_error()
                    states.append(f"{name} 不可用")
                    self.report(f"{name} 注册失败（错误码 {error}），可能被旧版助手或其他程序占用。请关闭其他助手窗口后重启；也可用界面上的播放和停止按钮。")
            self.status(" · ".join(states))
            while not self.exit.wait(0.015):
                while user32.PeekMessageW(ct.byref(message), None, 0, 0, 1):
                    if message.message == 0x0312 and message.wParam in registered:
                        {801: self.toggle, 802: self.stop, 803: self.overlay, 804: self.visibility}[message.wParam]()
        finally:
            for identity in registered:
                user32.UnregisterHotKey(None, identity)

    def close(self):
        self.exit.set()
        self.thread.join(timeout=1)
