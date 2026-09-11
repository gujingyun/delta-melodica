"""口风琴助手：曲库、音轨选择、试听与游戏演奏界面。"""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import shutil
import sys
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import uuid

from music import DEMO_SCORES, Mapping, compile_plan, parse_jianpu, pitch_name, read_midi
from player import Player
from overlay import Overlay
from win_input import (Hotkeys, PreviewOutput, WindowsOutput, foreground, target_matches,
                       matching_windows, process_elevated, permission_problem, restart_as_admin)

BG = "#11191d"
CARD = "#1b272d"
DEEP = "#152126"
TEXT = "#e9f0ec"
MUTED = "#96a9aa"
ACCENT = "#b7f17c"
LINE = "#304249"
ORANGE = "#f1c077"

DEFAULTS = {"keys": "zxcvbnm,", "base": 60, "low": -12, "high": 12, "half": 1,
            "target": "三角洲|Delta Force|DeltaForce", "countdown": 5, "gate": 85}


def clock_label(seconds):
    return f"{int(max(0, seconds)) // 60:02d}:{int(max(0, seconds)) % 60:02d}"


class App:
    def __init__(self, root, data_dir, smoke=False, game_test=False):
        self.root, self.data_dir, self.smoke = root, Path(data_dir), smoke
        self.game_test_pending = game_test
        self.library_dir = self.data_dir / "songs"
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.log = logging.getLogger(f"melodica.{id(self)}")
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        self.log_handler = RotatingFileHandler(self.data_dir / "diagnostic.log", maxBytes=300000, backupCount=2, encoding="utf-8")
        self.log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.log.addHandler(self.log_handler)
        self.elevated = process_elevated()
        self.log.info("启动 v0.3；PID=%s；管理员权限=%s", os.getpid(), self.elevated)
        self.settings = DEFAULTS.copy()
        self.load_error = None
        try:
            saved = json.loads((self.data_dir / "settings.json").read_text(encoding="utf-8"))
            candidate = {k: saved.get(k, v) for k, v in DEFAULTS.items()}
            Mapping(**{k: candidate[k] for k in ("keys", "base", "low", "high", "half")}).validate()
            if not isinstance(candidate["target"], str) or not candidate["target"].strip():
                raise ValueError("目标窗口不能为空")
            if not 2 <= candidate["countdown"] <= 15 or not 10 <= candidate["gate"] <= 98:
                raise ValueError("倒计时或按住比例超出范围")
            self.settings = candidate
        except FileNotFoundError:
            pass
        except (ValueError, TypeError, AttributeError, OSError) as error:
            self.load_error = f"设置读取失败，已使用默认值：{error}"
        self.events = queue.Queue()
        self.player = Player(lambda kind, value: self.events.put((kind, value)))
        self.song, self.plan, self.current_source = None, None, None
        self.entries, self.track_ids, self.locked_widgets = [], [], []
        self.started_at, self.playing_mode, self.current_note = None, "", None
        self.busy, self.closing = False, False
        self.speed = tk.StringVar(value="1.00")
        self.transpose = tk.StringVar(value="0")
        self.track = tk.StringVar()
        self.title = tk.StringVar(value="选择一首音乐")
        self.subtitle = tk.StringVar(value="从曲库开始，或导入你的 MIDI")
        self.status = tk.StringVar(value="准备就绪")
        self.detail = tk.StringVar(value="先试听，再进入游戏取出口风琴。")
        self.elapsed = tk.StringVar(value="00:00 / 00:00")
        self.stats = tk.StringVar(value="")
        self.hotkey_status = tk.StringVar(value="热键正在初始化")
        self._build()
        self._load_library()
        self.overlay = Overlay(self)
        self.hotkeys = None if smoke else Hotkeys(
            lambda: self.events.put(("toggle", None)),
            lambda: self.stop("F9"),
            lambda text: self.events.put(("warning", text)),
            lambda text: self.events.put(("hotkeys", text)),
            lambda: self.events.put(("overlay", None)),
        )
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(40, self._poll)
        if not smoke:
            self.root.after(300, self.check_permissions)
        if game_test:
            self.root.after(1000, lambda: self.play(False))
        if self.load_error:
            self.detail.set(self.load_error)

    def mapping(self):
        return Mapping(**{k: self.settings[k] for k in ("keys", "base", "low", "high", "half")})

    def _build(self):
        root = self.root
        root.title("口风琴助手 v0.3 · MIDI 自动演奏")
        root.geometry("1120x850")
        root.minsize(1000, 830)
        root.configure(bg=BG)
        root.option_add("*Font", ("Microsoft YaHei UI", 10))
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=CARD, foreground=TEXT)
        style.configure("TButton", background=LINE, foreground=TEXT, borderwidth=0, padding=(14, 10), font=("Microsoft YaHei UI", 10))
        style.map("TButton", background=[("active", "#41575d"), ("disabled", "#25343a")], foreground=[("disabled", "#64777c")])
        style.configure("Accent.TButton", background=ACCENT, foreground=BG, font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#d3ffaa"), ("disabled", "#50663f")], foreground=[("disabled", "#a1b098")])
        style.configure("TCombobox", fieldbackground=DEEP, background=LINE, foreground=TEXT, arrowcolor=TEXT, padding=7)
        style.map("TCombobox", fieldbackground=[("readonly", DEEP)], foreground=[("readonly", TEXT)])
        style.configure("TEntry", fieldbackground=DEEP, foreground=TEXT, padding=7, insertcolor=TEXT)
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=LINE, borderwidth=0, thickness=4)
        root.option_add("*TCombobox*Listbox.background", CARD)
        root.option_add("*TCombobox*Listbox.foreground", TEXT)
        header = tk.Frame(root, bg=BG)
        header.pack(fill="x", padx=28, pady=(16, 14))
        left = tk.Frame(header, bg=BG)
        left.pack(side="left")
        tk.Label(left, text="口风琴助手", font=("Microsoft YaHei UI", 22, "bold"), fg=TEXT, bg=BG).pack(anchor="w")
        tk.Label(left, text="MELODICA  /  让旋律进入游戏", font=("Microsoft YaHei UI", 10), fg=MUTED, bg=BG).pack(anchor="w", pady=(3, 0))
        settings = ttk.Button(header, text="键位与设置", command=self.settings_dialog)
        settings.pack(side="right")
        self.locked_widgets.append(settings)
        ttk.Button(header, text="游戏悬浮窗  F7", command=lambda: self.overlay.begin_edit()).pack(side="right", padx=(0, 12))
        if self.elevated is not True:
            self.admin_button = ttk.Button(header, text="以管理员身份重启", command=self.elevate)
            self.admin_button.pack(side="right", padx=(0, 12))
            self.locked_widgets.append(self.admin_button)
        tk.Label(header, text="v0.3 · " + ("管理员权限" if self.elevated else "普通权限"), fg=ACCENT, bg=BG).pack(side="right", padx=16)

        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=28)
        sidebar = tk.Frame(body, bg=CARD, width=250)
        sidebar.pack(side="left", fill="y", padx=(0, 18))
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="我的曲库", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w", padx=18, pady=(20, 6))
        tk.Label(sidebar, text="示例旋律与本地 MIDI", bg=CARD, fg=MUTED).pack(anchor="w", padx=18, pady=(0, 14))
        self.library = tk.Listbox(sidebar, bg=CARD, fg=TEXT, selectbackground="#354a38", selectforeground=ACCENT,
                                  highlightthickness=0, bd=0, activestyle="none", exportselection=False,
                                  font=("Microsoft YaHei UI", 11), height=10)
        self.library.pack(fill="both", expand=True, padx=12)
        self.library.bind("<<ListboxSelect>>", self.select_song)
        self.locked_widgets.append(self.library)
        for text, command in (("＋  导入 MIDI", self.import_midi), ("＋  输入简谱", self.score_dialog)):
            button = ttk.Button(sidebar, text=text, command=command)
            button.pack(fill="x", padx=18, pady=(0, 12))
            self.locked_widgets.append(button)
        tk.Label(sidebar, text="支持 .mid / .midi\n多音轨可单独选择旋律", justify="left", bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=18, pady=(0, 20))

        content = tk.Frame(body, bg=BG)
        content.pack(side="left", fill="both", expand=True)
        track_card = tk.Frame(content, bg=CARD)
        track_card.pack(fill="x")
        tk.Label(track_card, text="当前曲目", bg=CARD, fg=ACCENT, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=22, pady=(14, 5))
        tk.Label(track_card, textvariable=self.title, bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 20, "bold"), anchor="w").pack(fill="x", padx=22)
        tk.Label(track_card, textvariable=self.subtitle, bg=CARD, fg=MUTED, anchor="w").pack(fill="x", padx=22, pady=(5, 12))
        fields = tk.Frame(track_card, bg=CARD)
        fields.pack(fill="x", padx=22, pady=(0, 14))
        for column, (label, variable, values, width) in enumerate([
            ("演奏音轨", self.track, [], 26),
            ("速度倍率", self.speed, ["0.25", "0.50", "0.75", "1.00", "1.25", "1.50", "2.00"], 8),
            ("移调 / 半音", self.transpose, list(range(-24, 25)), 7),
        ]):
            frame = tk.Frame(fields, bg=CARD)
            frame.grid(row=0, column=column, sticky="ew", padx=(0, 14 if column < 2 else 0))
            tk.Label(frame, text=label, bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(0, 6))
            combo = ttk.Combobox(frame, textvariable=variable, values=values, width=width, state="readonly")
            combo.pack(fill="x")
            combo.bind("<<ComboboxSelected>>", lambda event: self.rebuild_plan())
            self.locked_widgets.append(combo)
            if column == 0:
                self.track_combo = combo
                fields.columnconfigure(0, weight=1)

        score_card = tk.Frame(content, bg=CARD)
        score_card.pack(fill="both", expand=True, pady=(16, 0))
        score_top = tk.Frame(score_card, bg=CARD)
        score_top.pack(fill="x", padx=22, pady=(17, 8))
        tk.Label(score_top, text="旋律预览", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        tk.Label(score_top, textvariable=self.elapsed, bg=CARD, fg=MUTED, font=("Consolas", 11)).pack(side="right")
        self.roll = tk.Canvas(score_card, bg=DEEP, highlightthickness=0, height=90)
        self.roll.pack(fill="both", expand=True, padx=22)
        self.roll.bind("<Configure>", lambda event: self.draw_roll())
        self.progress = ttk.Progressbar(score_card, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=22, pady=(12, 10))
        tk.Label(score_card, textvariable=self.stats, bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9), anchor="w").pack(fill="x", padx=22)
        self.keys_canvas = tk.Canvas(score_card, height=73, bg=CARD, highlightthickness=0)
        self.keys_canvas.pack(fill="x", padx=22, pady=(8, 10))
        self.keys_canvas.bind("<Configure>", lambda event: self.draw_keys())

        controls = tk.Frame(content, bg=BG)
        controls.pack(fill="x", pady=(17, 0))
        self.preview_button = ttk.Button(controls, text="▷  本机试听", command=lambda: self.play(True))
        self.preview_button.pack(side="left", padx=(0, 10))
        self.play_button = ttk.Button(controls, text="▶  游戏演奏  F8", style="Accent.TButton", command=lambda: self.play(False))
        self.play_button.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.stop_button = ttk.Button(controls, text="■  停止  F9", command=self.stop)
        self.stop_button.pack(side="right")
        status_card = tk.Frame(content, bg=BG)
        status_card.pack(fill="x", pady=(13, 0))
        tk.Label(status_card, textvariable=self.status, bg=BG, fg=ACCENT, anchor="w", font=("Microsoft YaHei UI", 11, "bold")).pack(fill="x")
        tk.Label(status_card, textvariable=self.detail, bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=670, font=("Microsoft YaHei UI", 9)).pack(fill="x", pady=(4, 0))
        bottom = tk.Frame(root, bg=BG)
        bottom.pack(fill="x", padx=28, pady=(10, 0))
        tk.Label(bottom, textvariable=self.hotkey_status, bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side="left")
        log_button = tk.Label(bottom, text="查看诊断日志", bg=BG, fg=ACCENT, cursor="hand2", font=("Microsoft YaHei UI", 9))
        log_button.pack(side="right")
        log_button.bind("<Button-1>", lambda event: self.show_log())
        self.footer = tk.Label(root, text="游戏内：F7 操作悬浮窗　F8 播放 / 停止　F9 紧急停止　｜　悬浮窗建议配合无边框窗口模式",
                 bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 9))
        self.footer.pack(anchor="w", padx=28, pady=(5, 10))

    def check_permissions(self):
        for window in matching_windows(self.settings["target"]):
            problem = permission_problem(window[1])
            self.log.info("检测游戏：标题=%s；PID=%s；管理员权限=%s", window[2], window[1], process_elevated(window[1]))
            if problem:
                self.status.set("需要与游戏使用相同权限")
                self.detail.set(problem)
                return

    def elevate(self):
        if self.busy:
            return
        try:
            self.log.info("用户请求以管理员身份重新启动")
            restart_as_admin(self.data_dir)
        except OSError as error:
            self.log.warning("管理员启动失败：%s", error)
            self.detail.set(str(error))
            return
        self.close()

    def show_log(self):
        self.log_handler.flush()
        dialog = self._dialog("诊断日志", "820x520")
        tk.Label(dialog, text="包含热键、权限、目标窗口和输入失败记录。", bg=CARD, fg=MUTED).pack(anchor="w", padx=18, pady=14)
        viewer = tk.Text(dialog, bg=DEEP, fg=TEXT, wrap="word", bd=0, padx=12, pady=12)
        viewer.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        viewer.insert("1.0", (self.data_dir / "diagnostic.log").read_text(encoding="utf-8")[-20000:])
        viewer.configure(state="disabled")
        viewer.see("end")

    def _load_library(self, select_path=None):
        self.entries = [(name, ("demo", name)) for name in DEMO_SCORES]
        for path in sorted(self.library_dir.iterdir()):
            if path.suffix.lower() in (".mid", ".midi", ".json"):
                self.entries.append((path.stem.split("__", 1)[-1], ("file", path)))
        self.library.delete(0, "end")
        selected = 0
        for index, (name, source) in enumerate(self.entries):
            self.library.insert("end", "  " + name)
            if select_path and source[1] == select_path:
                selected = index
        self.library.selection_set(selected)
        self.library.see(selected)
        self.select_song()

    def select_song(self, event=None):
        if self.busy:
            return
        selection = self.library.curselection()
        if not selection:
            return
        name, source = self.entries[selection[0]]
        try:
            if source[0] == "demo":
                bpm, score = DEMO_SCORES[source[1]]
                song = parse_jianpu(score, bpm, name)
                hint = f"示例曲 · {bpm} BPM"
            elif source[1].suffix.lower() == ".json":
                data = json.loads(source[1].read_text(encoding="utf-8"))
                song = parse_jianpu(data["score"], float(data["bpm"]), data["title"])
                hint = f"自定义简谱 · {data['bpm']} BPM"
            else:
                song = read_midi(source[1])
                song.title = name
                hint = f"MIDI · {len(song.tracks)} 条旋律音轨 · 保留原始变速"
            self.song, self.current_source = song, source
            self.title.set(song.title)
            self.subtitle.set(hint)
            self.track_ids = [None, *song.tracks]
            values = ["全部音轨 · 取最高音", *(f"{k+1} · {v}" for k, v in song.tracks.items())]
            self.track_combo.configure(values=values)
            self.track_combo.current(1 if len(song.tracks) == 1 else 0)
            self.rebuild_plan()
        except Exception as error:
            self.song, self.plan = None, None
            self.title.set("曲目读取失败")
            self.stats.set("")
            self.detail.set(str(error))
            self.draw_roll()
            messagebox.showerror("无法读取曲目", str(error), parent=self.root)

    def rebuild_plan(self):
        if not self.song or self.busy:
            return
        try:
            self.plan = compile_plan(self.song, self.mapping(), self.track_ids[self.track_combo.current()], float(self.speed.get()), int(self.transpose.get()))
            self.stats.set(f"{len(self.plan.notes)} 个旋律音段  ·  单音演奏  ·  {self.plan.folded} 个音段折回可演奏八度")
            self.elapsed.set(f"00:00 / {clock_label(self.plan.duration)}")
            self.progress["value"] = 0
            self.status.set("准备就绪")
            self.detail.set("先试听，再进入游戏取出口风琴。按 F8 开始，F9 停止。")
            self.draw_roll()
            self.draw_keys()
        except (ValueError, IndexError) as error:
            self.plan = None
            self.status.set("请检查设置")
            self.detail.set(str(error))

    def import_midi(self):
        if self.busy:
            return
        paths = filedialog.askopenfilenames(title="选择 MIDI 音乐", filetypes=[("MIDI 音乐", "*.mid *.midi")], parent=self.root)
        last, errors = None, []
        for filename in paths:
            try:
                path = Path(filename)
                read_midi(path)
                destination = self.library_dir / (uuid.uuid4().hex[:8] + "__" + path.name)
                shutil.copy2(path, destination)
                last = destination
            except Exception as error:
                errors.append(f"{Path(filename).name}：{error}")
        if last:
            self._load_library(last)
        if errors:
            messagebox.showerror("部分 MIDI 未导入", "\n".join(errors), parent=self.root)

    def _dialog(self, title, geometry):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry(geometry)
        dialog.configure(bg=CARD)
        dialog.transient(self.root)
        dialog.grab_set()
        return dialog

    def score_dialog(self):
        dialog = self._dialog("新建简谱", "720x510")
        dialog.minsize(660, 480)
        name, bpm = tk.StringVar(value="我的旋律"), tk.StringVar(value="100")
        fields = tk.Frame(dialog, bg=CARD)
        fields.pack(fill="x", padx=22, pady=20)
        for label, variable, width in (("曲名", name, 28), ("BPM", bpm, 8)):
            tk.Label(fields, text=label, bg=CARD, fg=TEXT).pack(side="left", padx=(0, 8))
            ttk.Entry(fields, textvariable=variable, width=width).pack(side="left", padx=(0, 18))
        tk.Label(dialog, text="用空格分隔：1 2 3:2 +1 -5 #4 0\n+1 高音 1；-1 低音 1；#4 升半音；b3 降半音；0 休止\n:2 两拍；:0.5 或 :1/2 半拍；竖线 | 仅作分节标记。", justify="left", bg=CARD, fg=MUTED).pack(anchor="w", padx=22)
        editor = tk.Text(dialog, bg=DEEP, fg=TEXT, insertbackground=TEXT, wrap="word", bd=0, padx=12, pady=12, font=("Consolas", 13))
        editor.pack(fill="both", expand=True, padx=22, pady=16)
        editor.insert("1.0", "1 2 3 1 | 1 2 3 1 | 3 4 5:2")

        def save():
            try:
                score = editor.get("1.0", "end").strip()
                song = parse_jianpu(score, float(bpm.get()), name.get())
                safe_name = "".join(c for c in song.title if c not in '<>:"/\\|?*' and ord(c) >= 32).rstrip(" .")[:70] or "我的旋律"
                destination = self.library_dir / (uuid.uuid4().hex[:8] + "__" + safe_name + ".json")
                destination.write_text(json.dumps({"title": song.title, "bpm": float(bpm.get()), "score": score}, ensure_ascii=False, indent=2), encoding="utf-8")
                dialog.destroy()
                self._load_library(destination)
            except (ValueError, OSError) as error:
                messagebox.showerror("简谱未保存", str(error), parent=dialog)
        ttk.Button(dialog, text="保存到曲库", style="Accent.TButton", command=save).pack(anchor="e", padx=22, pady=(0, 20))

    def settings_dialog(self):
        dialog = self._dialog("键位与演奏设置", "660x690")
        dialog.resizable(False, False)
        tk.Label(dialog, text="按游戏内的实际效果校准", bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", padx=24, pady=(22, 8))
        tk.Label(dialog, text="默认：Z X C V B N M , → 1 2 3 4 5 6 7 高音1\n鼠标修饰键采用按住模式，音符结束后松开。", bg=CARD, fg=MUTED, justify="left").pack(anchor="w", padx=24, pady=(0, 18))
        frame = tk.Frame(dialog, bg=CARD)
        frame.pack(fill="x", padx=24)
        fields = [
            ("keys", "八个音阶键", None), ("base", "中央 1 的 MIDI 音高（C4 = 60）", [36, 48, 60, 72, 84]),
            ("low", "鼠标左键偏移 / 半音", list(range(-24, 25))),
            ("high", "鼠标右键偏移 / 半音", list(range(-24, 25))),
            ("half", "鼠标中键偏移 / 半音", [1, -1]),
            ("countdown", "开始倒计时 / 秒", list(range(2, 16))),
            ("gate", "音符按住比例 / %", [50, 65, 75, 85, 90, 95, 98]),
            ("target", "目标窗口标题（用 | 分隔关键词）", None),
        ]
        variables = {}
        for row, (key, label, values) in enumerate(fields):
            tk.Label(frame, text=label, bg=CARD, fg=TEXT).grid(row=row, column=0, sticky="w", pady=7)
            variable = variables[key] = tk.StringVar(value=str(self.settings[key]))
            widget = ttk.Combobox(frame, textvariable=variable, values=values, state="readonly", width=26) if values else ttk.Entry(frame, textvariable=variable, width=29)
            widget.grid(row=row, column=1, sticky="ew", pady=7, padx=(15, 0))
        frame.columnconfigure(1, weight=1)
        tk.Label(dialog, text="左／右键暂按 -12／+12 半音（低／高八度）；中键暂按 +1 半音。\n中央 1 的真实音高和鼠标效果，请用「音阶校准」曲在游戏内核对。\n只向倒计时结束时匹配的前台窗口演奏，切换窗口即停止。", bg=CARD, fg=MUTED, justify="left", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=24, pady=17)

        def save():
            try:
                candidate = {key: (value.get().strip() if key in ("keys", "target") else int(value.get())) for key, value in variables.items()}
                candidate["keys"] = candidate["keys"].lower()
                Mapping(**{k: candidate[k] for k in ("keys", "base", "low", "high", "half")}).validate()
                if not any(word.strip() for word in candidate["target"].split("|")):
                    raise ValueError("至少填写一个目标窗口标题关键词。")
                destination = self.data_dir / "settings.json"
                temporary = destination.with_suffix(".tmp")
                temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(destination)
                self.settings = candidate
                dialog.destroy()
                self.rebuild_plan()
            except (ValueError, OSError) as error:
                messagebox.showerror("设置未保存", str(error), parent=dialog)
        ttk.Button(dialog, text="保存设置", command=save, style="Accent.TButton").pack(anchor="e", padx=24, pady=(0, 20))

    def _set_busy(self, busy):
        self.busy = busy
        for widget in self.locked_widgets:
            state = "disabled" if busy else ("readonly" if isinstance(widget, ttk.Combobox) else "normal")
            widget.configure(state=state)
        for widget in (self.preview_button, self.play_button):
            widget.configure(state="disabled" if busy else "normal")

    def play(self, preview=False):
        if self.busy or self.player.active or self.root.grab_current():
            self.log.info("启动请求未执行：忙碌=%s；播放器=%s；弹窗=%s", self.busy, self.player.active, bool(self.root.grab_current()))
            return
        self.rebuild_plan()
        if not self.plan:
            self.log.warning("启动请求未执行：没有有效乐谱")
            return
        settings = self.settings.copy()

        def game_output():
            window = foreground()
            self.log.info("倒计时结束：前台标题=%s；HWND=%s；PID=%s；游戏管理员权限=%s", window[2], window[0], window[1], process_elevated(window[1]))
            if not target_matches(window, settings["target"]):
                raise RuntimeError(f"前台不是目标游戏（当前：{window[2] or '无标题'}）。请进入游戏，或在设置中修正窗口关键词。")
            problem = permission_problem(window[1])
            if problem:
                raise RuntimeError(problem)
            return WindowsOutput(window)
        self.started_at = None
        self.playing_mode = "本机试听" if preview else "游戏演奏"
        countdown = 0 if preview else settings["countdown"]
        if not preview and self.game_test_pending:
            from music import Plan
            notes = self.plan.notes[:7]
            self.plan = Plan(notes, notes[-1].end, 0, len(notes))
            countdown = 10
            self.game_test_pending = False
            self.log.info("本次为游戏内七音测试；10 秒倒计时；之后恢复普通演奏模式")
        self.log.info("开始请求：%s；曲目=%s；音符=%s", self.playing_mode, self.song.title, len(self.plan.notes))
        self._set_busy(True)
        self.status.set("正在准备" if preview else "准备游戏演奏")
        self.detail.set("试听使用本机合成音色。" if preview else "倒计时结束后开始，请保持游戏内口风琴打开；F9 随时停止。")
        try:
            self.player.start(self.plan, PreviewOutput if preview else game_output, countdown, settings["gate"] / 100)
        except Exception as error:
            self._set_busy(False)
            self.detail.set(str(error))

    def stop(self, source="停止按钮"):
        self.log.info("停止请求：%s", source)
        self.player.stop()

    def _poll(self):
        if self.closing:
            return
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "toggle":
                    self.log.info("收到 F8 热键；当前忙碌=%s", self.busy)
                    self.overlay.toggle_play()
                elif kind == "overlay":
                    self.log.info("收到 F7 悬浮窗热键")
                    self.overlay.toggle_edit()
                elif kind == "warning":
                    self.log.warning(value)
                    self.detail.set(value)
                elif kind == "hotkeys":
                    self.hotkey_status.set(value)
                    self.log.info("热键状态：%s", value)
                elif kind == "countdown":
                    self.status.set(f"{value} 秒后开始 · 保持口风琴打开")
                elif kind == "started":
                    self.log.info("已开始：%s", self.playing_mode)
                    self.started_at = time.perf_counter()
                    self.status.set(self.playing_mode + "中")
                elif kind == "note":
                    index, note = value
                    self.current_note = note
                    self.detail.set(f"{index+1} / {len(self.plan.notes)}　{pitch_name(note.fingering.pitch)}　按键：{note.fingering.label}　｜　F9 停止")
                    self.draw_keys()
                elif kind == "release":
                    self.current_note = None
                    self.draw_keys()
                elif kind == "done":
                    status, error = value
                    self.log.info("播放结束：%s；错误=%s", status, error)
                    elapsed = min(self.plan.duration, time.perf_counter()-self.started_at) if self.started_at else 0
                    if status == "演奏完成" and not error:
                        elapsed = self.plan.duration
                    self.elapsed.set(f"{clock_label(elapsed)} / {clock_label(self.plan.duration)}")
                    self.progress["value"] = elapsed/max(self.plan.duration, 0.01)*100
                    self.started_at = None
                    self.current_note = None
                    self._set_busy(False)
                    self.status.set(status if not error else "已停止，请检查提示")
                    self.detail.set(error or "可以选择下一首，或按 F8 再次演奏。")
                    self.draw_keys()
                    self.draw_roll(elapsed)
        except queue.Empty:
            pass
        if self.started_at is not None and self.plan:
            elapsed = min(self.plan.duration, time.perf_counter()-self.started_at)
            self.elapsed.set(f"{clock_label(elapsed)} / {clock_label(self.plan.duration)}")
            self.progress["value"] = elapsed/max(self.plan.duration, 0.01)*100
            self.draw_roll(elapsed)
        self.root.after(40, self._poll)

    def draw_keys(self):
        canvas = self.keys_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 200)
        keys = self.settings["keys"]
        key_width = (width-7*6)/8
        for index, key in enumerate(keys):
            x = index*(key_width+6)
            active = self.current_note and self.current_note.fingering.key == key
            canvas.create_rectangle(x, 4, x+key_width, 71, fill=ACCENT if active else "#26363d", outline="")
            canvas.create_text(x+key_width/2, 27, text=key.upper(), fill=BG if active else TEXT, font=("Consolas", 17, "bold"))
            canvas.create_text(x+key_width/2, 57, text=str(index+1) if index < 7 else "高音 1", fill=BG if active else MUTED, font=("Microsoft YaHei UI", 9))

    def draw_roll(self, elapsed=0):
        canvas = self.roll
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 200), max(canvas.winfo_height(), 80)
        if not self.plan:
            return
        span = 12
        left = max(0, elapsed-2) if elapsed > 2 else 0
        low = min(n.fingering.pitch for n in self.plan.notes)-1
        high = max(n.fingering.pitch for n in self.plan.notes)+1
        def y(pitch):
            return 15+(high-pitch)/max(high-low, 1)*(height-30)
        for pitch in range(low, high+1):
            if pitch % 12 == 0:
                canvas.create_line(35, y(pitch), width, y(pitch), fill=LINE)
                canvas.create_text(5, y(pitch), text=pitch_name(pitch), anchor="w", fill=MUTED, font=("Consolas", 8))
        for second in range(int(left), int(left+span)+1):
            x = 40+(second-left)/span*(width-45)
            if x >= 40:
                canvas.create_line(x, 0, x, height, fill="#1e3037")
        for note in self.plan.notes:
            if note.end < left:
                continue
            if note.start > left+span:
                break
            x1 = 40+(max(note.start, left)-left)/span*(width-45)
            x2 = min(width-5, 40+(note.end-left)/span*(width-45))
            fill = ACCENT if note.start <= elapsed < note.end else "#638b75"
            canvas.create_rectangle(x1, y(note.fingering.pitch)-4, max(x1+2, x2-2), y(note.fingering.pitch)+4, fill=fill, outline="")
        cursor = 40+(elapsed-left)/span*(width-45)
        canvas.create_line(cursor, 0, cursor, height, fill=ORANGE, width=2)

    def close(self):
        self.closing = True
        self.player.close()
        self.overlay.close()
        if self.hotkeys:
            self.hotkeys.close()
        self.log.info("关闭助手")
        self.log.removeHandler(self.log_handler)
        self.log_handler.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(Path(os.environ.get("LOCALAPPDATA", str(Path.cwd()))) / "DeltaMelodica"))
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--game-test", action="store_true", help="10 秒后向目标游戏播放小星星开头七音，仅执行一次")
    args = parser.parse_args()
    # EXE 使用 requireAdministrator 清单；源码运行也请求提权，冒烟测试除外。
    if not args.smoke and process_elevated() is False:
        try:
            restart_as_admin(args.data_dir, ["--game-test"] if args.game_test else [])
        except OSError as error:
            notice = tk.Tk()
            notice.withdraw()
            messagebox.showerror("需要管理员权限", str(error), parent=notice)
            notice.destroy()
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    app = App(root, args.data_dir, args.smoke, args.game_test)
    smoke_exit = 0
    if args.smoke:
        def verify():
            nonlocal smoke_exit
            try:
                root.update_idletasks()
                assert app.plan and len(app.plan.notes) == 42
                assert app.settings["keys"][-1] == ","
                assert app.play_button.winfo_ismapped()
                assert app.footer.winfo_y()+app.footer.winfo_height() <= root.winfo_height()
                midi_tested = 0
                for _, source in app.entries:
                    if source[0] == "file" and source[1].suffix.lower() in (".mid", ".midi"):
                        imported = read_midi(source[1])
                        assert compile_plan(imported, app.mapping()).notes
                        midi_tested += 1
                Path(args.data_dir, "smoke-result.json").write_text(json.dumps({"ok": True, "notes": len(app.plan.notes), "midi_tested": midi_tested, "width": root.winfo_width(), "height": root.winfo_height()}), encoding="utf-8")
            except Exception as error:
                smoke_exit = 1
                Path(args.data_dir, "smoke-result.json").write_text(json.dumps({"ok": False, "error": str(error)}), encoding="utf-8")
            finally:
                app.close()
        root.after(1200, verify)
    root.mainloop()
    if smoke_exit:
        raise SystemExit(smoke_exit)


if __name__ == "__main__":
    main()
