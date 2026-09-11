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
        self.lock = threading.RLock()
        self.run_id = 0
        self.duration, self._position, self._origin = 0.0, 0.0, None
        self.paused = False
        self.cancel_status = "已停止"

    @property
    def active(self):
        return bool(self.thread and self.thread.is_alive())

    @property
    def position(self):
        with self.lock:
            value = time.perf_counter()-self._origin if self._origin is not None else self._position
            return min(self.duration, max(0.0, value))

    def start(self, plan, output_factory, countdown=0, gate=0.85, start_at=0):
        if self.active:
            raise RuntimeError("请先停止当前演奏。")
        if not 0.1 <= gate <= 0.98:
            raise ValueError("按住比例需在 10%～98% 之间。")
        if not math.isfinite(start_at) or not 0 <= start_at <= plan.duration:
            raise ValueError("播放位置必须在曲目范围内。")
        with self.lock:
            self.duration, self._position, self._origin = plan.duration, start_at, None
            self.paused, self.cancel_status = False, "已停止"
            self.cancel.clear()
            self.run_id += 1
        self.thread = threading.Thread(target=self._run, args=(plan, output_factory, countdown, gate, start_at, self.run_id), daemon=True)
        self.thread.start()

    def stop(self):
        with self.lock:
            self._position, self._origin, self.paused = 0.0, None, False
            self.cancel_status = "已停止"
            self.cancel.set()

    def pause(self):
        with self.lock:
            if not self.active or self.cancel.is_set():
                return
            self._position = self.position
            self._origin, self.paused = None, True
            self.cancel_status = "已暂停"
            self.cancel.set()

    def seek(self, position, duration):
        if not math.isfinite(position):
            raise ValueError("进度位置必须是有效数字。")
        with self.lock:
            self.pause()
            self.duration = duration
            self._position = min(duration, max(0.0, position))
            self._origin, self.paused = None, True

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

    def _run(self, plan, output_factory, countdown, gate, start_at=0, run_id=None):
        output, status, error = None, "演奏完成", None
        run_id = self.run_id if run_id is None else run_id
        notify = lambda kind, value: self.notify(run_id, kind, value)
        try:
            deadline = time.perf_counter() + countdown
            previous = None
            while time.perf_counter() < deadline:
                left = math.ceil(deadline-time.perf_counter())
                if previous != left:
                    notify("countdown", left)
                    previous = left
                self._wait(min(deadline, time.perf_counter()+0.05))
            if self.cancel.is_set():
                raise Cancelled()
            if start_at < plan.duration:
                output = output_factory()
            with self.lock:
                if self.cancel.is_set():
                    raise Cancelled()
                self.duration = plan.duration
                origin = self._origin = time.perf_counter()-start_at
            notify("started", None)
            for index, note in enumerate(plan.notes):
                next_note = plan.notes[index+1] if index+1 < len(plan.notes) else None
                end = release_time(note, next_note, gate, plan.style == "piano")
                if end <= start_at:
                    continue
                self._wait(origin+max(note.start, start_at), output)
                # 系统短暂卡顿时丢弃已过时的音符，避免恢复后瞬间连发。
                if time.perf_counter() >= origin+end:
                    continue
                output.begin(note.fingering)
                notify("note", (index, note))
                self._wait(origin+end, output)
                output.release()
                notify("release", None)
            self._wait(origin+plan.duration, output)
            with self.lock:
                if self.cancel.is_set():
                    raise Cancelled()
                self._position, self._origin, self.paused = plan.duration, None, False
        except Cancelled:
            status = self.cancel_status
        except Exception as exc:
            status, error = "演奏已停止", str(exc)
            with self.lock:
                self._position = self.position
                self._origin = None
                self.paused = not self.cancel.is_set()
        finally:
            if output:
                try:
                    output.close()
                except Exception as exc:
                    error = (error + "；" if error else "") + str(exc)
            if self.cancel.is_set():
                status = self.cancel_status
            notify("done", (status, error))

    def close(self):
        self.stop()
        if self.thread:
            self.thread.join(timeout=2)
