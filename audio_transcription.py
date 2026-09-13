"""桌面与独立扒谱引擎之间的可取消任务和曲库落盘。"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from cloud_score import from_song
from music import compile_plan, transcribed_melody
from online_library import _safe_title
from win_input import terminate_process_tree


@dataclass(frozen=True)
class AudioOptions:
    mode: str = "vocal"
    start: float = 0
    duration: float | None = 30

    def validate(self):
        if self.mode not in ("vocal", "solo"):
            raise ValueError("请选择人声歌曲或独奏模式。")
        if not math.isfinite(self.start) or not 0 <= self.start <= 86400:
            raise ValueError("起点需为 0～86400 秒。")
        if self.duration is not None and (not math.isfinite(self.duration) or not 1 <= self.duration <= 600):
            raise ValueError("片段时长需为 1～600 秒，或选择整首。")


def engine_command():
    """成品使用相邻引擎目录，源码开发使用隔离的 Python 3.10 环境。"""
    if getattr(sys, "frozen", False):
        folder = Path(sys.executable).parent / "audio-engine"
        command = [str(folder / "audio_worker.exe")]
        models = folder / "models"
    else:
        root = Path(__file__).resolve().parent
        command = [str(root / "work/transcription-runtime/Scripts/python.exe"), str(root / "audio_worker.py")]
        models = root / "work/audio-models"
    if not Path(command[0]).is_file():
        raise ValueError("未找到扒谱引擎。请解压完整扒谱版，保留程序旁的 audio-engine 文件夹。")
    return command, models


class AudioTranscription:
    def __init__(self, path, library_dir, mapping, options, runtime=None):
        self.path, self.library_dir = Path(path), Path(library_dir)
        self.mapping, self.options = mapping, options
        self.runtime = runtime
        self.events = queue.Queue()
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.process = None
        self.thread = None

    @property
    def active(self):
        return bool(self.thread and self.thread.is_alive())

    def start(self):
        if self.active:
            raise ValueError("已有扒谱任务正在运行。")
        self.options.validate()
        if not self.path.is_file() or self.path.suffix.lower() not in (".mp3", ".wav", ".flac", ".ogg"):
            raise ValueError("请选择 MP3、WAV、FLAC 或 OGG 音频文件。")
        if not 0 < self.path.stat().st_size <= 200 * 1024 * 1024:
            raise ValueError("音频文件需小于 200 MB，且不能为空。")
        self.runtime = self.runtime or engine_command()
        self.thread = threading.Thread(target=self._run, name="audio-transcription")
        self.thread.start()

    def cancel(self):
        with self.lock:
            self.cancelled.set()

    def _run(self):
        try:
            self.library_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".audio-", dir=self.library_dir) as temporary:
                folder = Path(temporary)
                command, models = self.runtime
                job = {"input": str(self.path.resolve()), "folder": str(folder.resolve()), "models": str(models),
                       "mode": self.options.mode, "start": self.options.start, "duration": self.options.duration}
                job_path = folder / "job.json"
                job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
                with (folder / "engine.log").open("wb") as log:
                    with self.lock:
                        if self.cancelled.is_set():
                            return
                        self.process = subprocess.Popen([*command, str(job_path.resolve())], stdout=log, stderr=log,
                            stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            env={**os.environ, "PYTHONUTF8": "1", "NUMBA_CACHE_DIR": str(folder / "numba"),
                                 "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4"})
                    message, deadline, timed_out = "", time.monotonic() + 3600, False
                    while self.process.poll() is None:
                        if self.cancelled.wait(0.15):
                            terminate_process_tree(self.process)
                            break
                        if time.monotonic() > deadline:
                            terminate_process_tree(self.process)
                            timed_out = True
                            break
                        try:
                            progress = json.loads((folder / "progress.json").read_text(encoding="utf-8"))["message"]
                            if progress != message:
                                message = progress
                                self.events.put(("progress", message))
                        except (OSError, ValueError, KeyError):
                            pass
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        terminate_process_tree(self.process)
                if timed_out:
                    raise ValueError("扒谱超过一小时，请缩短片段后重试。")
                if self.cancelled.is_set():
                    return
                if self.process.returncode:
                    error_path = folder / "error.json"
                    error = json.loads(error_path.read_text(encoding="utf-8"))["message"] if error_path.exists() else "扒谱引擎退出异常，请确认使用完整安装包。"
                    raise ValueError(error)
                result_path = folder / "result.json"
                if result_path.stat().st_size > 4 * 1024 * 1024:
                    raise ValueError("扒谱结果过大，请缩短片段。")
                result = json.loads(result_path.read_text(encoding="utf-8"))
                title = self.path.stem[:75] + " · AI扒谱"
                song = transcribed_melody(result["notes"], result["duration"], title, trim_leading=True)
                compile_plan(song, self.mapping, track="auto", style="original")
                score = from_song(song)
                score["transcription"] = {"source": self.path.name, "mode": self.options.mode,
                                           "start": self.options.start, "trim_start": result["duration"] - song.duration,
                                           "model": "basic-pitch-0.4.0"}
                staging = folder / "score.json"
                staging.write_text(json.dumps(score, ensure_ascii=False), encoding="utf-8")
                destination = self.library_dir / f"{uuid.uuid4().hex[:8]}__{_safe_title(title)}.json"
                with self.lock:
                    if self.cancelled.is_set():
                        return
                    staging.replace(destination)
                self.events.put(("done", (destination, len(song.notes), song.duration)))
        except Exception as error:
            if not self.cancelled.is_set():
                self.events.put(("error", str(error)))
        finally:
            if self.process and self.process.poll() is None:
                terminate_process_tree(self.process)
            if self.cancelled.is_set():
                self.events.put(("cancelled", None))
