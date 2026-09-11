"""可取消的节奏调度器；界面与 Windows 输入通过回调隔离。"""
from __future__ import annotations

import math
import threading
import time


class Cancelled(Exception):
    pass


def release_time(note, next_note=None, gate=0.85, legato=False):
    """连奏按完整时值吹奏，只在衔接处留出最多 25 毫秒重新触发。"""
    if not legato:
        return note.start+(note.end-note.start)*gate
    if next_note is None:
        return note.end
    gap = min(0.025, (note.end-note.start)*0.25)
    return min(note.end, next_note.start-gap)


class Player:
    def __init__(self, notify):
        self.notify = notify
        self.cancel = threading.Event()
        self.thread = None

    @property
    def active(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self, plan, output_factory, countdown=0, gate=0.85):
        if self.active:
            raise RuntimeError("请先停止当前演奏。")
        if not 0.1 <= gate <= 0.98:
            raise ValueError("按住比例需在 10%～98% 之间。")
        self.cancel.clear()
        self.thread = threading.Thread(target=self._run, args=(plan, output_factory, countdown, gate), daemon=True)
        self.thread.start()

    def stop(self):
        self.cancel.set()

    def _wait(self, deadline, output=None):
        while True:
            if self.cancel.is_set():
                raise Cancelled()
            if output:
                output.check()
            remaining = deadline-time.perf_counter()
            if remaining <= 0:
                return
            self.cancel.wait(min(remaining, 0.008))

    def _run(self, plan, output_factory, countdown, gate):
        output, status, error = None, "演奏完成", None
        try:
            deadline = time.perf_counter() + countdown
            previous = None
            while time.perf_counter() < deadline:
                left = math.ceil(deadline-time.perf_counter())
                if previous != left:
                    self.notify("countdown", left)
                    previous = left
                self._wait(min(deadline, time.perf_counter()+0.05))
            if self.cancel.is_set():
                raise Cancelled()
            output = output_factory()
            self.notify("started", None)
            origin = time.perf_counter()
            for index, note in enumerate(plan.notes):
                self._wait(origin+note.start, output)
                # 系统短暂卡顿时丢弃已过时的音符，避免恢复后瞬间连发。
                if time.perf_counter() >= origin+note.end:
                    continue
                output.begin(note.fingering)
                self.notify("note", (index, note))
                next_note = plan.notes[index+1] if index+1 < len(plan.notes) else None
                self._wait(origin+release_time(note, next_note, gate, plan.style == "piano"), output)
                output.release()
                self.notify("release", None)
            self._wait(origin+plan.duration, output)
        except Cancelled:
            status = "已停止"
        except Exception as exc:
            status, error = "演奏已停止", str(exc)
        finally:
            if output:
                try:
                    output.close()
                except Exception as exc:
                    error = (error + "；" if error else "") + str(exc)
            self.notify("done", (status, error))

    def close(self):
        self.stop()
        if self.thread:
            self.thread.join(timeout=2)
