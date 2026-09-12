"""三角洲口风琴：曲库、音轨选择、试听与游戏演奏界面。"""
from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import re
import shutil
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import urllib.request
import uuid
import webbrowser

from music import (DEMO_SCORES, Mapping, compile_plan, parse_jianpu, pitch_name, read_midi,
                   recommend_track, validate_segments, segment_source_position)
from online_library import (ONLINE_CATALOG_URL, OnlineSong, download_online_song,
                            fetch_catalog)
from player import Player
from overlay import Overlay
from tray import Tray
from win_input import (Hotkeys, PreviewOutput, WindowsOutput, foreground, target_matches,
                       matching_windows, process_elevated, permission_problem, restart_as_admin,
                       activate_window, window_info, root_window)

BG = "#11191d"
CARD = "#1b272d"
DEEP = "#152126"
TEXT = "#e9f0ec"
MUTED = "#96a9aa"
ACCENT = "#b7f17c"
LINE = "#304249"
ORANGE = "#f1c077"
PLAY_STYLES = {"钢琴适配 · 连奏": "piano", "原谱 · 分音": "original"}
SPEEDS = ["0.25", "0.50", "0.75", "1.00", "1.25", "1.50", "1.75", "2.00"]
APP_VERSION = "0.11"
UPDATE_MANIFEST_URL = "https://aiygzn.top/melodica/version.json"
UPDATE_PAGE_URL = "https://aiygzn.top/melodica/"

DEFAULTS = {"keys": "zxcvbnm,", "base": 60, "low": -12, "high": 12, "half": 1,
            "target": "三角洲|Delta Force|DeltaForce", "countdown": 5, "gate": 85}


def clock_label(seconds):
    return f"{int(max(0, seconds)) // 60:02d}:{int(max(0, seconds)) % 60:02d}"


def precise_clock_label(seconds):
    # 向下取到毫秒，原曲末尾含小数时也不会显示越界时间。
    milliseconds = int(max(0, seconds)*1000)
    return f"{milliseconds // 60000:02d}:{milliseconds // 1000 % 60:02d}.{milliseconds % 1000:03d}"


def parse_clock(text):
    value = text.strip().replace("：", ":")
    if not re.fullmatch(r"(?:\d+:)?\d+(?:\.\d{1,3})?", value):
        raise ValueError("时间请填写 分:秒（如 01:23.500）或秒数（如 83.5），最多三位小数。")
    parts = value.split(":")
    seconds = float(parts[-1])
    if len(parts) == 2:
        if seconds >= 60:
            raise ValueError("分:秒格式中的秒数必须小于 60。")
        seconds += int(parts[0])*60
    return seconds


def parse_version(value):
    """解析由数字和点组成的版本号，兼容 v0.10 这种展示形式。"""
    if not isinstance(value, str):
        raise ValueError("版本号必须是文本")
    value = value.strip()
    if not re.fullmatch(r"v?\d+(?:\.\d+)*", value, re.IGNORECASE):
        raise ValueError(f"版本号格式不正确：{value or '空'}")
    return tuple(int(part) for part in value.lstrip("vV").split("."))


def parse_update_manifest(payload):
    """校验官网版本清单，只保留更新提示所需字段。"""
    if not isinstance(payload, dict):
        raise ValueError("版本清单格式不正确")
    version = payload.get("version")
    version_tuple = parse_version(version)
    notes = payload.get("notes", "")
    if notes is None:
        notes = ""
    if not isinstance(notes, str):
        raise ValueError("版本说明格式不正确")
    return {"version": version.lstrip("vV"), "version_tuple": version_tuple, "notes": notes.strip()}


def fetch_update_manifest(url=UPDATE_MANIFEST_URL):
    """从官网读取版本清单，网络请求只应在线程中调用。"""
    request = urllib.request.Request(url, headers={"User-Agent": f"DeltaMelodica/{APP_VERSION}"})
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read(64 * 1024).decode("utf-8"))
    return parse_update_manifest(payload)


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
        self.log.info("启动 三角洲口风琴 v%s；PID=%s；管理员权限=%s", APP_VERSION, os.getpid(), self.elevated)
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
        self.song_preferences = {}
        try:
            saved = json.loads((self.data_dir / "song-settings.json").read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError("曲目设置格式不正确")
            self.song_preferences = saved
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as error:
            self.load_error = f"曲目设置读取失败，已使用默认值：{error}"
        self.events = queue.Queue()
        self.player = Player(lambda run_id, kind, value: self.events.put(("player", (run_id, kind, value))))
        self.song, self.plan, self.current_source = None, None, None
        self.entries, self.track_ids, self.locked_widgets = [], [], []
        self.playing_mode, self.current_note = "", None
        self.seeking, self.pending_play, self.transport_revision = False, None, 0
        self.seek_revision = 0
        self.restore_plan_after_test = False
        self.busy, self.closing = False, False
        self.update_checking = False
        self.online_catalog = []
        self.online_catalog_dialog = None
        self.online_catalog_list = None
        self.online_catalog_status = None
        self.online_catalog_detail = None
        self.online_download_button = None
        self.online_operation = None
        self.online_operation_kind = None
        self.online_downloaded_ids = set()
        self.speed = tk.StringVar(value="1.00")
        self.transpose = tk.StringVar(value="0")
        self.plan_parameters = ("1.00", "0")
        self.arrangement = tk.StringVar(value="原谱 · 分音")
        self.track = tk.StringVar()
        self.segments = []
        self.segment_summary = tk.StringVar(value="全曲 · 参数按曲目自动保存")
        self.preview_title = tk.StringVar(value="旋律预览")
        self.title = tk.StringVar(value="选择一首音乐")
        self.subtitle = tk.StringVar(value="从曲库开始，或导入你的 MIDI")
        self.status = tk.StringVar(value="准备就绪")
        self.detail = tk.StringVar(value="先试听，再进入游戏取出口风琴。")
        self.elapsed = tk.StringVar(value="00:00 / 00:00")
        self.stats = tk.StringVar(value="")
        self.hotkey_status = tk.StringVar(value="热键正在初始化")
        self.overlay_button_text = tk.StringVar(value="显示悬浮窗  F6")
        self._build()
        self._load_library()
        self.overlay = Overlay(self)
        self.tray = None
        if not smoke:
            try:
                self.tray = Tray(lambda kind, value: self.events.put((kind, value)))
            except Exception as error:
                self.events.put(("tray_error", str(error)))
        self.hotkeys = None if smoke else Hotkeys(
            lambda: self.events.put(("toggle", None)),
            lambda: self.stop("F9"),
            lambda text: self.events.put(("warning", text)),
            lambda text: self.events.put(("hotkeys", text)),
            lambda: self.events.put(("overlay", None)),
            lambda: self.events.put(("overlay_visibility", None)),
            speed=lambda step: self.events.put(("speed", step)),
            transpose=lambda step: self.events.put(("transpose", step)),
        )
        self.root.protocol("WM_DELETE_WINDOW", self.hide_main)
        self.poll_timer = self.root.after(40, self._poll)
        if not smoke:
            self.root.after(300, self.check_permissions)
            self.root.after(1000, lambda: self.check_updates(automatic=True))
        if game_test:
            self.root.after(1000, lambda: self.play(False))
        if self.load_error:
            self.detail.set(self.load_error)

    def mapping(self):
        return Mapping(**{k: self.settings[k] for k in ("keys", "base", "low", "high", "half")})

    def _build(self):
        root = self.root
        root.title(f"三角洲口风琴 v{APP_VERSION} · MIDI 自动演奏")
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
        tk.Label(left, text="三角洲口风琴", font=("Microsoft YaHei UI", 22, "bold"), fg=TEXT, bg=BG).pack(anchor="w")
        tk.Label(left, text="MELODICA  /  让旋律进入游戏", font=("Microsoft YaHei UI", 10), fg=MUTED, bg=BG).pack(anchor="w", pady=(3, 0))
        settings = ttk.Button(header, text="键位与设置", command=self.settings_dialog)
        settings.pack(side="right")
        self.locked_widgets.append(settings)
        self.update_button = ttk.Button(header, text="检查更新", command=self.check_updates)
        self.update_button.pack(side="right", padx=(0, 12))
        ttk.Button(header, text="悬浮窗操作  F7", command=lambda: self.overlay.begin_edit()).pack(side="right", padx=(0, 12))
        if self.elevated is not True:
            self.admin_button = ttk.Button(header, text="以管理员身份重启", command=self.elevate)
            self.admin_button.pack(side="right", padx=(0, 12))
            self.locked_widgets.append(self.admin_button)
        tk.Label(header, text=f"v{APP_VERSION} · " + ("管理员权限" if self.elevated else "普通权限"), fg=ACCENT, bg=BG).pack(side="right", padx=16)

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
        self.online_button = ttk.Button(sidebar, text="☁  线上曲库", command=self.online_library_dialog)
        self.online_button.pack(fill="x", padx=18, pady=(0, 12))
        self.locked_widgets.append(self.online_button)
        self.delete_button = ttk.Button(sidebar, text="删除选中曲目", command=self.delete_song)
        self.delete_button.pack(fill="x", padx=18, pady=(0, 12))
        self.locked_widgets.append(self.delete_button)
        tk.Label(sidebar, text="支持 .mid / .midi\n多音轨可单独选择旋律", justify="left", bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=18, pady=(0, 20))

        content = tk.Frame(body, bg=BG)
        content.pack(side="left", fill="both", expand=True)
        track_card = tk.Frame(content, bg=CARD)
        track_card.pack(fill="x")
        tk.Label(track_card, text="当前曲目", bg=CARD, fg=ACCENT, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=22, pady=(10, 4))
        tk.Label(track_card, textvariable=self.title, bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 20, "bold"), anchor="w").pack(fill="x", padx=22)
        tk.Label(track_card, textvariable=self.subtitle, bg=CARD, fg=MUTED, anchor="w").pack(fill="x", padx=22, pady=(3, 6))
        fields = tk.Frame(track_card, bg=CARD)
        fields.pack(fill="x", padx=22, pady=(0, 8))
        for column, (label, variable, values, width) in enumerate([
            ("演奏音轨", self.track, [], 26),
            ("速度倍率", self.speed, SPEEDS, 8),
            ("移调 / 半音", self.transpose, list(range(-24, 25)), 7),
        ]):
            frame = tk.Frame(fields, bg=CARD)
            frame.grid(row=0, column=column, sticky="ew", padx=(0, 14 if column < 2 else 0))
            tk.Label(frame, text=label, bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(0, 6))
            combo = ttk.Combobox(frame, textvariable=variable, values=values, width=width, state="readonly")
            combo.pack(fill="x")
            if column == 0:
                combo.bind("<<ComboboxSelected>>", lambda event: self.rebuild_plan())
                self.locked_widgets.append(combo)
                self.track_combo = combo
                fields.columnconfigure(0, weight=1)
            else:
                combo.bind("<<ComboboxSelected>>", lambda event: self.rebuild_plan(preserve_position=True))
                if column == 1:
                    self.speed_combo = combo
                else:
                    self.transpose_combo = combo

        adaptation = tk.Frame(track_card, bg=CARD)
        adaptation.pack(fill="x", padx=22, pady=(0, 10))
        tk.Label(adaptation, text="演奏方式", bg=CARD, fg=MUTED).pack(side="left", padx=(0, 12))
        self.style_combo = ttk.Combobox(adaptation, textvariable=self.arrangement,
                                       values=list(PLAY_STYLES), state="readonly", width=18)
        self.style_combo.pack(side="left")
        self.style_combo.bind("<<ComboboxSelected>>", lambda event: self.rebuild_plan())
        self.locked_widgets.append(self.style_combo)
        tk.Label(adaptation, text="连奏：整理伴奏碎音，连接短间隙", bg=CARD, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(14, 0))

        segments = tk.Frame(track_card, bg=CARD)
        segments.pack(fill="x", padx=22, pady=(0, 10))
        tk.Label(segments, text="演出片段", bg=CARD, fg=MUTED).pack(side="left", padx=(0, 12))
        self.segment_button = ttk.Button(segments, text="设置片段…", command=self.segments_dialog, padding=(10, 5))
        self.segment_button.pack(side="right")
        tk.Label(segments, textvariable=self.segment_summary, bg=CARD, fg=ACCENT,
                 font=("Microsoft YaHei UI", 9), anchor="w").pack(side="left", fill="x", expand=True)

        score_card = tk.Frame(content, bg=CARD)
        score_card.pack(fill="both", expand=True, pady=(16, 0))
        score_top = tk.Frame(score_card, bg=CARD)
        score_top.pack(fill="x", padx=22, pady=(12, 6))
        tk.Label(score_top, textvariable=self.preview_title, bg=CARD, fg=TEXT, font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        tk.Label(score_top, textvariable=self.elapsed, bg=CARD, fg=MUTED, font=("Consolas", 11)).pack(side="right")
        self.roll = tk.Canvas(score_card, bg=DEEP, highlightthickness=0, height=70)
        self.roll.pack(fill="both", expand=True, padx=22)
        self.roll.bind("<Configure>", lambda event: self.draw_roll())
        style.configure("Horizontal.TScale", background=ACCENT, troughcolor=LINE)
        self.progress = ttk.Scale(score_card, from_=0, to=100, value=0, cursor="hand2")
        self.progress.pack(fill="x", padx=22, pady=(12, 10))
        self.progress.bind("<ButtonPress-1>", self._seek_press)
        self.progress.bind("<B1-Motion>", self._seek_motion)
        self.progress.bind("<ButtonRelease-1>", self._seek_release)
        for key, step in (("Left", -2), ("Right", 2), ("Down", -2), ("Up", 2)):
            self.progress.bind(f"<{key}>", lambda event, step=step: self._seek_key(step))
        self.progress.bind("<Home>", lambda event: self._seek_key(to_end=False))
        self.progress.bind("<End>", lambda event: self._seek_key(to_end=True))
        stats_label = tk.Label(score_card, textvariable=self.stats, bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9), anchor="w")
        stats_label.pack(fill="x", padx=22)
        self.keys_canvas = tk.Canvas(score_card, height=73, bg=CARD, highlightthickness=0)
        self.keys_canvas.pack(fill="x", padx=22, pady=(4, 6))
        self.keys_canvas.bind("<Configure>", lambda event: self.draw_keys())
        self.keys_canvas.pack_configure(side="bottom", before=self.roll)
        stats_label.pack_configure(side="bottom", before=self.roll)
        self.progress.pack_configure(side="bottom", before=self.roll)

        controls = tk.Frame(content, bg=BG)
        controls.pack(fill="x", pady=(12, 0))
        self.preview_button = ttk.Button(controls, text="▷  本机试听", command=lambda: self.toggle_play(True))
        self.preview_button.pack(side="left", padx=(0, 10))
        self.play_button = ttk.Button(controls, text="▶  游戏演奏  F8", style="Accent.TButton", command=lambda: self.toggle_play(False))
        self.play_button.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.stop_button = ttk.Button(controls, text="■  停止  F9", command=self.stop)
        self.stop_button.pack(side="right")
        status_card = tk.Frame(content, bg=BG)
        status_card.pack(fill="x", pady=(10, 0))
        tk.Label(status_card, textvariable=self.status, bg=BG, fg=ACCENT, anchor="w", font=("Microsoft YaHei UI", 11, "bold")).pack(fill="x")
        tk.Label(status_card, textvariable=self.detail, bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=670, font=("Microsoft YaHei UI", 9)).pack(fill="x", pady=(4, 0))
        bottom = tk.Frame(root, bg=BG)
        bottom.pack(fill="x", padx=28, pady=(10, 0))
        tk.Label(bottom, textvariable=self.hotkey_status, bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.overlay_button = ttk.Button(bottom, textvariable=self.overlay_button_text,
                                         command=lambda: self.overlay.toggle_visibility(), padding=(8, 3))
        self.overlay_button.pack(side="left", padx=12)
        self.exit_button = ttk.Button(bottom, text="退出程序", command=self.close, padding=(8, 3))
        log_button = tk.Label(bottom, text="查看诊断日志", bg=BG, fg=ACCENT, cursor="hand2", font=("Microsoft YaHei UI", 9))
        log_button.pack(side="right")
        log_button.bind("<Button-1>", lambda event: self.show_log())
        self.footer = tk.Label(root, text="F4/F5 音调 −/+　F10/F11 速度 −/+　F6 显隐　F7 操作　F8 暂停/继续　F9 停止归零　｜　关闭后从托盘退出",
                 bg=BG, fg=MUTED, justify="left", font=("Microsoft YaHei UI", 9))
        self.footer.pack(anchor="w", padx=28, pady=(5, 10))
        # 先为底部操作与提示留出空间，窗口变小时由旋律画布缩小。
        self.footer.pack_configure(side="bottom", before=body)
        bottom.pack_configure(side="bottom", before=body)
        status_card.pack_configure(side="bottom", before=score_card)
        controls.pack_configure(side="bottom", before=score_card)

    def check_permissions(self):
        for window in matching_windows(self.settings["target"]):
            problem = permission_problem(window[1])
            self.log.info("检测游戏：标题=%s；PID=%s；管理员权限=%s", window[2], window[1], process_elevated(window[1]))
            if problem:
                self.status.set("需要与游戏使用相同权限")
                self.detail.set(problem)
                return

    def check_updates(self, automatic=False):
        """在线程中检查官网版本，结果回到 Tk 主线程处理。"""
        if self.closing:
            return
        if self.update_checking:
            if not automatic:
                self.detail.set("正在检查更新，请稍候。")
            return
        self.update_checking = True
        if not automatic:
            self.status.set("正在检查更新")
            self.detail.set("正在连接官网读取版本信息…")
        self.log.info("开始%s检查更新", "自动" if automatic else "手动")
        threading.Thread(target=self._check_updates, args=(automatic,), daemon=True).start()

    def _check_updates(self, automatic):
        try:
            manifest = fetch_update_manifest()
            self.events.put(("update_result", (automatic, manifest, None)))
        except Exception as error:
            self.events.put(("update_result", (automatic, None, error)))

    def _show_update_notice(self, manifest):
        version = manifest["version"]
        notes = manifest["notes"]
        message = f"发现新版本 v{version}，当前版本为 v{APP_VERSION}。"
        if notes:
            message += f"\n\n更新说明：\n{notes}"
        message += "\n\n是否打开官网查看并下载？"
        if messagebox.askyesno("发现新版本", message, parent=self.root):
            webbrowser.open(UPDATE_PAGE_URL)

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

    def _online_dialog_alive(self):
        return self.online_catalog_dialog and self.online_catalog_dialog.winfo_exists()

    def online_library_dialog(self):
        """打开线上曲库，目录读取和 MIDI 下载均不阻塞主界面。"""
        if self.busy:
            return
        if self._online_dialog_alive():
            self.online_catalog_dialog.lift()
            return self.online_catalog_dialog
        dialog = self._dialog("线上曲库", "760x620")
        dialog.minsize(700, 540)
        self.online_catalog_dialog = dialog
        tk.Label(dialog, text="从官网曲库下载 MIDI", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", padx=22, pady=(20, 4))
        tk.Label(dialog, text="选择曲目后下载到本地曲库；网络不可用时不影响已有曲目播放。",
                 bg=CARD, fg=MUTED).pack(anchor="w", padx=22, pady=(0, 14))
        body = tk.Frame(dialog, bg=CARD)
        body.pack(fill="both", expand=True, padx=22)
        self.online_catalog_list = tk.Listbox(
            body, bg=DEEP, fg=TEXT, selectbackground="#354a38", selectforeground=ACCENT,
            highlightthickness=0, bd=0, activestyle="none", exportselection=False,
            font=("Microsoft YaHei UI", 11), width=34)
        self.online_catalog_list.pack(side="left", fill="both", expand=True)
        self.online_catalog_list.bind("<<ListboxSelect>>", self._select_online_song)
        self.online_catalog_list.bind("<Double-Button-1>", lambda event: self.download_online_selected())
        detail_frame = tk.Frame(body, bg=CARD, width=300)
        detail_frame.pack(side="left", fill="both", expand=True, padx=(18, 0))
        detail_frame.pack_propagate(False)
        self.online_catalog_detail = tk.StringVar(value="正在读取线上曲库…")
        tk.Label(detail_frame, textvariable=self.online_catalog_detail, bg=CARD, fg=MUTED,
                 justify="left", anchor="nw", wraplength=300).pack(fill="both", expand=True, anchor="nw")
        self.online_catalog_status = tk.StringVar(value="")
        tk.Label(dialog, textvariable=self.online_catalog_status, bg=CARD, fg=ORANGE,
                 anchor="w", justify="left", wraplength=700).pack(fill="x", padx=22, pady=(12, 4))
        actions = tk.Frame(dialog, bg=CARD)
        actions.pack(fill="x", padx=22, pady=(6, 20))
        ttk.Button(actions, text="刷新目录", command=self.refresh_online_catalog).pack(side="left")
        self.online_download_button = ttk.Button(actions, text="下载到本地曲库",
                                                 command=self.download_online_selected,
                                                 style="Accent.TButton")
        self.online_download_button.pack(side="right")
        ttk.Button(actions, text="关闭", command=self._close_online_library_dialog).pack(side="right", padx=(0, 10))
        dialog.protocol("WM_DELETE_WINDOW", self._close_online_library_dialog)
        self.refresh_online_catalog()
        return dialog

    def _close_online_library_dialog(self):
        if not self._online_dialog_alive():
            return
        self.online_operation = None
        self.online_operation_kind = None
        self.online_catalog_dialog.destroy()
        self.online_catalog_dialog = None
        self.online_catalog_list = None
        self.online_catalog_status = None
        self.online_catalog_detail = None
        self.online_download_button = None

    def refresh_online_catalog(self):
        if not self._online_dialog_alive() or self.online_operation:
            return
        token = uuid.uuid4().hex
        self.online_operation, self.online_operation_kind = token, "catalog"
        self.online_catalog_status.set("正在连接官网读取曲目目录…")
        self.online_catalog_list.configure(state="disabled")
        self.online_download_button.configure(state="disabled")
        threading.Thread(target=self._fetch_online_catalog, args=(token,), daemon=True).start()

    def _fetch_online_catalog(self, token):
        try:
            songs = fetch_catalog(ONLINE_CATALOG_URL)
            self.events.put(("online_catalog_result", (token, songs, None)))
        except Exception as error:
            self.events.put(("online_catalog_result", (token, None, error)))

    def _select_online_song(self, event=None):
        if not self.online_catalog_list or not self.online_catalog_detail:
            return
        selection = self.online_catalog_list.curselection()
        if not selection or selection[0] >= len(self.online_catalog):
            self.online_catalog_detail.set("请选择一首曲目。")
            return
        song = self.online_catalog[selection[0]]
        lines = [song.title]
        if song.artist:
            lines.append(f"作者：{song.artist}")
        if song.description:
            lines.extend(["", song.description])
        lines.extend(["", "已下载到本地曲库" if song.song_id in self.online_downloaded_ids else "尚未下载"])
        self.online_catalog_detail.set("\n".join(lines))
        self.online_download_button.configure(state="normal" if not self.online_operation else "disabled")

    def download_online_selected(self):
        if self.busy or not self._online_dialog_alive() or self.online_operation:
            return
        selection = self.online_catalog_list.curselection()
        if not selection or selection[0] >= len(self.online_catalog):
            self.online_catalog_status.set("请先选择一首线上曲目。")
            return
        song = self.online_catalog[selection[0]]
        token = uuid.uuid4().hex
        self.online_operation, self.online_operation_kind = token, "download"
        self.online_catalog_status.set(f"正在下载“{song.title}”…")
        self.online_catalog_list.configure(state="disabled")
        self.online_download_button.configure(state="disabled")
        threading.Thread(target=self._download_online_song, args=(token, song), daemon=True).start()

    def _download_online_song(self, token, song: OnlineSong):
        try:
            path = download_online_song(song, self.library_dir)
            self.events.put(("online_download_result", (token, song, path, None)))
        except Exception as error:
            self.events.put(("online_download_result", (token, song, None, error)))

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
            self._update_delete_button()
            self.title.set(song.title)
            self.subtitle.set(hint)
            self.track_ids = ["auto", None, *song.tracks]
            recommended = recommend_track(song)
            values = [f"自动旋律 · {song.tracks[recommended]}", "全部音轨 · 取最高音",
                      *(f"{k+1} · {v}" for k, v in song.tracks.items())]
            self.track_combo.configure(values=values)
            self.track_combo.current(0)
            is_midi = source[0] == "file" and source[1].suffix.lower() in (".mid", ".midi")
            self.arrangement.set("钢琴适配 · 连奏" if is_midi else "原谱 · 分音")
            preference_warning = self.restore_song_preferences()
            self.rebuild_plan(save_preferences=False)
            if preference_warning:
                self.detail.set(preference_warning)
        except Exception as error:
            self.song, self.plan, self.current_source = None, None, None
            self._update_delete_button()
            self.title.set("曲目读取失败")
            self.stats.set("")
            self.detail.set(str(error))
            self.draw_roll()
            messagebox.showerror("无法读取曲目", str(error), parent=self.root)

    def song_preference_key(self):
        kind, value = self.current_source
        # 导入文件名含独立编号，同名曲目不会互相覆盖，也不依赖数据目录的位置。
        return f"{kind}:{value.name if kind == 'file' else value}"

    def restore_song_preferences(self):
        self.speed.set("1.00")
        self.transpose.set("0")
        self.segments = []
        warning = None
        saved = self.song_preferences.get(self.song_preference_key(), {})
        if not isinstance(saved, dict):
            return
        speed = saved.get("speed")
        if type(speed) in (int, float) and speed in [float(value) for value in SPEEDS]:
            self.speed.set(f"{speed:.2f}")
        transpose = saved.get("transpose")
        if type(transpose) is int and -24 <= transpose <= 24:
            self.transpose.set(str(transpose))
        track = saved.get("track", "auto")
        if (track is None or track == "auto" or type(track) is int) and track in self.track_ids:
            self.track_combo.current(self.track_ids.index(track))
        style = saved.get("style")
        for label, value in PLAY_STYLES.items():
            if style == value:
                self.arrangement.set(label)
        try:
            self.segments = validate_segments(saved.get("segments", []), self.song.duration)
        except ValueError as error:
            warning = f"已保存的片段不可用，暂用全曲：{error}"
        return warning

    def save_song_preferences(self):
        if not self.current_source:
            return
        candidate = self.song_preferences.copy()
        candidate[self.song_preference_key()] = {
            "speed": float(self.speed.get()), "transpose": int(self.transpose.get()),
            "track": self.track_ids[self.track_combo.current()], "style": PLAY_STYLES[self.arrangement.get()],
            "segments": self.segments,
        }
        destination = self.data_dir / "song-settings.json"
        try:
            temporary = destination.with_suffix(".tmp")
            temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(destination)
            self.song_preferences = candidate
        except OSError as error:
            self.log.warning("曲目设置保存失败：%s", error)
            self.detail.set(f"本次调整已生效，但曲目设置未保存：{error}")

    def rebuild_plan(self, preserve_position=False, save_preferences=True, segments=None):
        if not self.song or (self.busy and not preserve_position):
            return False
        try:
            selected_segments = self.segments if segments is None else validate_segments(segments, self.song.duration)
            plan = compile_plan(self.song, self.mapping(), self.track_ids[self.track_combo.current()],
                                float(self.speed.get()), int(self.transpose.get()), PLAY_STYLES[self.arrangement.get()], selected_segments)
            if preserve_position and self.restore_plan_after_test:
                # 专用七音测试改参数后仍只演奏原来的七音。
                plan.notes = plan.notes[:len(self.plan.notes)]
                plan.duration = plan.notes[-1].end
            if not preserve_position:
                self.transport_revision += 1
                self.pending_play, self.seeking = None, False
                self.player.stop()
                self.status.set("准备就绪")
                self.detail.set("先试听，再进入游戏取出口风琴。按 F8 开始，F9 停止。")
            self.player.update_plan(plan)
            self.plan = plan
            self.segments = selected_segments
            self.plan_parameters = (self.speed.get(), self.transpose.get())
            self.current_note = None
            if self.plan.style == "piano":
                scope = "全曲" if self.segments else ""
                self.stats.set(f"{len(self.plan.notes)} 个旋律音  ·  {scope}整理 {self.plan.cleaned} 个音段  ·  {scope}连接 {self.plan.bridged} 处间隙  ·  {self.plan.folded} 个音折回八度")
            else:
                self.stats.set(f"{len(self.plan.notes)} 个旋律音段  ·  单音演奏  ·  {self.plan.folded} 个音段折回可演奏八度")
            self._update_progress()
            self.segment_summary.set(f"{len(self.segments)} 个片段 · 按列表顺序 · 自动保存" if self.segments else "全曲 · 参数按曲目自动保存")
            self.preview_title.set("片段预览 · 拼接进度" if self.segments else "旋律预览")
            self.draw_keys()
            self._update_play_buttons()
            if save_preferences:
                self.save_song_preferences()
            return True
        except (ValueError, IndexError) as error:
            if preserve_position:
                self.speed.set(self.plan_parameters[0])
                self.transpose.set(self.plan_parameters[1])
            elif segments is None:
                self.plan = None
                self.status.set("请检查设置")
            self.detail.set(str(error))
            return False

    def original_position(self):
        if not self.song:
            return 0.0
        return segment_source_position(self.player.position*float(self.speed.get()), self.segments, self.song.duration)

    def segments_dialog(self):
        if not self.song:
            return
        position = self.original_position()
        game_playing = self.busy and self.player.active and not self.player.cancel.is_set() and self.playing_mode == "游戏演奏"
        if game_playing:
            # 游戏演奏时打开编辑面板会改变前台窗口，先释放游戏按键并冻结当前位置。
            self.pause("设置片段")
        dialog = self._dialog("设置演出片段", "760x760")
        dialog.minsize(700, 720)
        draft = list(self.segments)
        tk.Label(dialog, text="按顺序演奏你选的片段", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", padx=22, pady=(18, 6))
        position_value = tk.StringVar(value=precise_clock_label(position))
        tk.Label(dialog, text=f"原曲时长 {precise_clock_label(self.song.duration)}　·　当前原曲位置：",
                 bg=CARD, fg=MUTED).pack(anchor="w", padx=22, pady=(0, 2))
        tk.Label(dialog, textvariable=position_value, bg=CARD, fg=ACCENT,
                 font=("Consolas", 13, "bold")).pack(anchor="w", padx=22, pady=(0, 8))
        tk.Label(dialog, text="播放时记录起点和终点；暂停后可以拖动下方进度条精确定位。时间按原曲 1 倍速计算。",
                 bg=CARD, fg=MUTED, justify="left").pack(anchor="w", padx=22, pady=(0, 8))

        transport = tk.Frame(dialog, bg=CARD)
        transport.pack(fill="x", padx=22, pady=(0, 8))
        dialog_progress = ttk.Scale(transport, from_=0, to=100, value=0, cursor="hand2")
        dialog_progress.pack(fill="x", pady=(0, 8))
        start_value = tk.StringVar(value=precise_clock_label(position))
        end_value = tk.StringVar(value=precise_clock_label(min(self.song.duration, position+10)))
        transport_buttons = tk.Frame(transport, bg=CARD)
        transport_buttons.pack(fill="x")
        dialog_play_text = tk.StringVar(value="Ⅱ 暂停播放" if self.busy and not self.player.cancel.is_set() else "▷ 继续播放")
        dialog_play = ttk.Button(transport_buttons, textvariable=dialog_play_text, padding=(12, 6))
        dialog_play.pack(side="left")
        record_start_button = ttk.Button(transport_buttons, text="记录当前为起点", command=lambda: record_current(start_value), padding=(12, 6))
        record_start_button.pack(side="left", padx=(8, 0))
        record_end_button = ttk.Button(transport_buttons, text="记录当前为终点", command=lambda: record_current(end_value), padding=(12, 6))
        record_end_button.pack(side="left", padx=(8, 0))
        dialog.segment_progress = dialog_progress
        dialog.segment_play = dialog_play
        dialog.segment_position = position_value
        dialog.segment_start_value = start_value
        dialog.segment_end_value = end_value
        dialog.segment_start_button = record_start_button
        dialog.segment_end_button = record_end_button

        fields = tk.Frame(dialog, bg=CARD)
        fields.pack(fill="x", padx=22)
        for row, (label, variable) in enumerate((("起点", start_value), ("终点", end_value))):
            tk.Label(fields, text=label, bg=CARD, fg=MUTED).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            ttk.Entry(fields, textvariable=variable, width=18).grid(row=row, column=1, sticky="ew", pady=4)
            ttk.Button(fields, text="使用当前位置", padding=(10, 5),
                       command=lambda variable=variable: record_current(variable)).grid(row=row, column=2, padx=(12, 0))
        fields.columnconfigure(1, weight=1)
        tk.Label(dialog, text="支持 01:23.500 或 83.5 秒；片段可重复，也可调整顺序。",
                 bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=22, pady=(5, 8))
        style = ttk.Style()
        style.configure("Segments.Treeview", background=DEEP, fieldbackground=DEEP, foreground=TEXT,
                        rowheight=28, borderwidth=0)
        style.configure("Segments.Treeview.Heading", background=LINE, foreground=TEXT)
        style.map("Segments.Treeview", background=[("selected", "#354a38")], foreground=[("selected", ACCENT)])
        table_frame = tk.Frame(dialog, bg=CARD)
        table_frame.pack(fill="both", expand=True, padx=22)
        table = ttk.Treeview(table_frame, columns=("order", "start", "end", "duration"),
                             show="headings", selectmode="browse", height=5, style="Segments.Treeview")
        for column, label, width in (("order", "顺序", 60), ("start", "原曲起点", 160),
                                     ("end", "原曲终点", 160), ("duration", "原速时长", 140)):
            table.heading(column, text=label)
            table.column(column, width=width, anchor="center", stretch=column != "order")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        table.pack(side="left", fill="both", expand=True)
        error_text = tk.StringVar()
        summary = tk.StringVar()
        editor_footer = tk.Frame(dialog, bg=CARD)
        editor_footer.pack(side="bottom", fill="x", before=table_frame)

        def record_current(variable):
            variable.set(precise_clock_label(self.original_position()))

        def dialog_fraction(event):
            return (event.x-8)/max(1, dialog_progress.winfo_width()-16)

        def dialog_seek_press(event):
            dialog_progress.focus_set()
            self.begin_seek()
            self.seek_fraction(dialog_fraction(event))
            return "break"

        def dialog_seek_motion(event):
            if self.seeking:
                self.seek_fraction(dialog_fraction(event))
            return "break"

        def dialog_seek_release(event):
            if self.seeking:
                self.seek_fraction(dialog_fraction(event))
                self.end_seek()
            return "break"

        dialog_progress.bind("<ButtonPress-1>", dialog_seek_press)
        dialog_progress.bind("<B1-Motion>", dialog_seek_motion)
        dialog_progress.bind("<ButtonRelease-1>", dialog_seek_release)

        def toggle_dialog_play():
            if self.player.active and not self.player.cancel.is_set():
                self.pause("片段设置面板")
                return
            if self.playing_mode == "游戏演奏":
                # 游戏必须重新获得前台焦点，继续游戏演奏时关闭编辑面板。
                dialog.grab_release()
                dialog.destroy()
                self.overlay.return_to_game(start=True)
                return
            dialog.grab_release()
            self.play(True)
            if dialog.winfo_exists():
                dialog.grab_set()

        dialog_play.configure(command=toggle_dialog_play)

        def refresh_live():
            try:
                if not dialog.winfo_exists():
                    return
            except tk.TclError:
                return
            current = self.original_position()
            position_value.set(precise_clock_label(current))
            if self.plan and self.plan.duration:
                dialog_progress.set(self.player.position/self.plan.duration*100)
            if self.player.active and not self.player.cancel.is_set():
                dialog_play_text.set("Ⅱ 暂停播放")
            elif self.playing_mode == "游戏演奏" and self.player.paused:
                dialog_play_text.set("▷ 继续游戏并关闭")
            elif self.player.paused:
                dialog_play_text.set("▷ 继续播放")
            else:
                dialog_play_text.set("▷ 开始试听")
            dialog.after(80, refresh_live)

        refresh_live()

        def refresh(selected=None):
            table.delete(*table.get_children())
            for index, (start, end) in enumerate(draft):
                table.insert("", "end", iid=str(index), values=(index+1, precise_clock_label(start),
                             precise_clock_label(end), precise_clock_label(end-start)))
            if selected is not None and draft:
                item = str(min(selected, len(draft)-1))
                table.selection_set(item)
                table.see(item)
            summary.set(f"{len(draft)} 个片段 · 当前速度下共 {precise_clock_label(sum(end-start for start, end in draft)/float(self.speed.get()))}"
                        if draft else "列表为空：播放全曲")
            error_text.set("")

        def selected_index():
            selection = table.selection()
            return int(selection[0]) if selection else None

        def select(event=None):
            index = selected_index()
            if index is not None:
                start_value.set(precise_clock_label(draft[index][0]))
                end_value.set(precise_clock_label(draft[index][1]))

        def edit(replace=False):
            try:
                segment = validate_segments([(parse_clock(start_value.get()), parse_clock(end_value.get()))], self.song.duration)[0]
                index = selected_index() if replace else len(draft)
                if index is None:
                    raise ValueError("请先选择要更新的片段。")
                candidate = list(draft)
                if replace:
                    candidate[index] = segment
                else:
                    candidate.append(segment)
                validate_segments(candidate, self.song.duration)
                draft[:] = candidate
                refresh(index)
            except (ValueError, OverflowError) as error:
                error_text.set(str(error))

        def remove():
            index = selected_index()
            if index is not None:
                draft.pop(index)
                refresh(index)

        def move(step):
            index = selected_index()
            if index is not None and 0 <= index+step < len(draft):
                draft[index], draft[index+step] = draft[index+step], draft[index]
                refresh(index+step)

        def clear():
            draft.clear()
            refresh()

        def export():
            safe_title = "".join(c for c in self.song.title if c not in '<>:"/\\|?*' and ord(c) >= 32).rstrip(" .")[:70] or "演出片段"
            filename = filedialog.asksaveasfilename(
                title="导出演出片段", defaultextension=".json",
                filetypes=[("片段设置", "*.json"), ("所有文件", "*.*")],
                initialfile=f"{safe_title} - 片段设置.json", parent=dialog)
            if not filename:
                return
            try:
                segments = validate_segments(draft, self.song.duration)
                payload = {
                    "format": "三角洲口风琴演出片段",
                    "version": 1,
                    "song": {"title": self.song.title, "duration": self.song.duration},
                    "segments": [list(segment) for segment in segments],
                    "empty_means_full_song": not segments,
                }
                Path(filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                error_text.set(f"已导出 {len(segments)} 个片段：{Path(filename).name}。" if segments
                               else f"已导出全曲设置：{Path(filename).name}。")
            except (ValueError, OSError) as error:
                error_text.set(f"导出失败：{error}")

        saving = [False]

        def finish_save():
            if not dialog.winfo_exists():
                return
            if self.player.active or self.busy:
                dialog.after(40, finish_save)
                return
            if self.rebuild_plan(segments=draft):
                self.seeking = False
                dialog.destroy()
            else:
                saving[0] = False
                error_text.set(self.detail.get())

        def save():
            if saving[0]:
                return
            saving[0] = True
            if self.player.active or self.busy:
                self.pause("保存片段")
                dialog.after(40, finish_save)
            else:
                finish_save()

        table.bind("<<TreeviewSelect>>", select)
        actions = tk.Frame(editor_footer, bg=CARD)
        actions.pack(fill="x", padx=22, pady=(10, 5))
        for label, command in (("添加到列表", edit), ("更新选中", lambda: edit(True)), ("删除", remove),
                               ("上移", lambda: move(-1)), ("下移", lambda: move(1)), ("清空 / 全曲", clear)):
            ttk.Button(actions, text=label, command=command, width=0, padding=(10, 6)).pack(side="left", padx=(0, 6))
        tk.Label(editor_footer, textvariable=summary, bg=CARD, fg=ACCENT).pack(anchor="w", padx=22, pady=(5, 0))
        tk.Label(editor_footer, text="播放时跳过未选部分，进度条显示拼接后的时间。保存后回到片段开头。",
                 bg=CARD, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=22, pady=(5, 0))
        tk.Label(editor_footer, textvariable=error_text, bg=CARD, fg=ORANGE, anchor="w", wraplength=630,
                 font=("Microsoft YaHei UI", 9)).pack(fill="x", padx=22, pady=(5, 0))
        buttons = tk.Frame(editor_footer, bg=CARD)
        buttons.pack(fill="x", padx=22, pady=(8, 18))
        ttk.Button(buttons, text="导出片段", command=export).pack(side="left")
        ttk.Button(buttons, text="保存片段", command=save, style="Accent.TButton").pack(side="right")
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side="right", padx=10)
        refresh()
        return dialog

    def change_speed(self, step):
        current = min(range(len(SPEEDS)), key=lambda i: abs(float(SPEEDS[i])-float(self.speed.get())))
        value = SPEEDS[min(max(current+step, 0), len(SPEEDS)-1)]
        if value != self.speed.get():
            self.speed.set(value)
            self.rebuild_plan(preserve_position=True)

    def change_transpose(self, step):
        value = str(min(24, max(-24, int(self.transpose.get())+step)))
        if value != self.transpose.get():
            self.transpose.set(value)
            self.rebuild_plan(preserve_position=True)

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
            ("gate", "原谱分音按住比例 / %", [50, 65, 75, 85, 90, 95, 98]),
            ("target", "目标窗口标题（用 | 分隔关键词）", None),
        ]
        variables = {}
        for row, (key, label, values) in enumerate(fields):
            tk.Label(frame, text=label, bg=CARD, fg=TEXT).grid(row=row, column=0, sticky="w", pady=7)
            variable = variables[key] = tk.StringVar(value=str(self.settings[key]))
            widget = ttk.Combobox(frame, textvariable=variable, values=values, state="readonly", width=26) if values else ttk.Entry(frame, textvariable=variable, width=29)
            widget.grid(row=row, column=1, sticky="ew", pady=7, padx=(15, 0))
        frame.columnconfigure(1, weight=1)
        tk.Label(dialog, text="钢琴适配连奏使用完整时值，衔接处最多留 25 毫秒松键；不使用上方比例。\n左／右键暂按低／高八度，中键暂按 +1 半音，请用「音阶校准」核对。\n只向倒计时结束时匹配的前台窗口演奏，切换窗口即停止。", bg=CARD, fg=MUTED, justify="left", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=24, pady=17)

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
        self._update_play_buttons()
        self._update_delete_button()

    def _update_delete_button(self):
        if not hasattr(self, "delete_button"):
            return
        can_delete = bool(self.current_source and self.current_source[0] == "file" and not self.busy)
        self.delete_button.configure(state="normal" if can_delete else "disabled")

    def delete_song(self):
        """删除当前选中的用户曲目，并移除对应的曲目参数记忆。"""
        if self.busy:
            return
        selection = self.library.curselection()
        if not selection:
            return
        name, source = self.entries[selection[0]]
        if source[0] != "file":
            self.detail.set("内置示例曲目不能删除。")
            return
        path = Path(source[1])
        try:
            library_root = self.library_dir.resolve()
            if path.resolve().parent != library_root or not path.is_file():
                raise OSError("曲目文件不在本地曲库目录中。")
        except OSError as error:
            self.detail.set(f"无法删除曲目：{error}")
            return
        if not messagebox.askyesno("删除曲目", f"确定删除“{name}”吗？\n\n这只会删除曲库副本，不会影响原始 MIDI 文件。", parent=self.root):
            return
        try:
            path.unlink()
        except OSError as error:
            messagebox.showerror("删除失败", f"无法删除曲目文件：{error}", parent=self.root)
            return
        preference_key = f"file:{path.name}"
        candidate = self.song_preferences.copy()
        candidate.pop(preference_key, None)
        try:
            destination = self.data_dir / "song-settings.json"
            temporary = destination.with_suffix(".tmp")
            temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(destination)
            self.song_preferences = candidate
            message = f"已删除曲目“{name}”。"
        except OSError as error:
            self.log.warning("删除曲目后的设置清理失败：%s", error)
            message = f"已删除曲目“{name}”，但对应参数记忆清理失败：{error}"
        self._load_library()
        self.detail.set(message)

    def _update_play_buttons(self):
        for button, preview, label in ((self.preview_button, True, "本机试听"), (self.play_button, False, "游戏演奏  F8")):
            current = (self.playing_mode == "本机试听") == preview
            waiting = self.busy and self.player.cancel.is_set()
            disabled = self.seeking or (self.busy and (not current or waiting))
            if self.busy and current and not waiting:
                text = "Ⅱ  暂停试听" if preview else "Ⅱ  暂停演奏  F8"
            elif self.player.paused:
                text = "▷  继续试听" if preview else "▶  继续演奏  F8"
            else:
                text = ("▷  " if preview else "▶  ") + label
            button.configure(text=text, state="disabled" if disabled else "normal")

    def toggle_play(self, preview=False):
        if self.pending_play is not None:
            self.transport_revision += 1
            self.pending_play = None
        elif self.player.active and not self.player.cancel.is_set():
            self.pause("播放按钮 / F8")
        else:
            self.play(preview)

    def play(self, preview=False):
        if self.seeking or self.root.grab_current():
            return
        self.transport_revision += 1
        if self.busy or self.player.active:
            if self.player.cancel.is_set():
                self.pending_play = preview
            self.log.info("启动请求未执行：忙碌=%s；播放器=%s；弹窗=%s", self.busy, self.player.active, bool(self.root.grab_current()))
            return
        if self.restore_plan_after_test:
            self.rebuild_plan()
            self.restore_plan_after_test = False
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
        continuing = self.player.paused
        start_at = self.player.position if continuing and self.player.position < self.plan.duration else 0
        self.playing_mode = "本机试听" if preview else "游戏演奏"
        countdown = 0 if preview or (continuing and target_matches(foreground(), settings["target"])) else settings["countdown"]
        if not preview and self.game_test_pending:
            from music import Plan
            notes = self.plan.notes[:7]
            self.plan = Plan(notes, notes[-1].end, 0, len(notes))
            countdown = 10
            self.game_test_pending = False
            self.restore_plan_after_test = True
            start_at = 0
            self.log.info("本次为游戏内七音测试；10 秒倒计时；之后恢复普通演奏模式")
        self.log.info("开始请求：%s；曲目=%s；音符=%s；方式=%s；音轨=%s；整理=%s；连接=%s", self.playing_mode,
                      self.song.title, len(self.plan.notes), self.plan.style, self.plan.track, self.plan.cleaned, self.plan.bridged)
        self.status.set("正在准备" if preview else "准备游戏演奏")
        timeline = "片段拼接进度 " if self.segments else ""
        self.detail.set(f"从{timeline} {clock_label(start_at)} 开始。" + ("试听使用本机合成音色。" if preview else "请保持游戏内口风琴打开；F8 暂停，F9 停止归零。"))
        try:
            self.player.start(self.plan, PreviewOutput if preview else game_output, countdown, settings["gate"] / 100, start_at=start_at)
            self._set_busy(True)
        except Exception as error:
            self._set_busy(False)
            self.detail.set(str(error))

    def stop(self, source="停止按钮"):
        self.log.info("停止请求：%s", source)
        self.transport_revision += 1
        self.player.stop()
        self.events.put(("stop_ui", (self.player.run_id, self.transport_revision)))

    def pause(self, source="暂停"):
        self.transport_revision += 1
        self.pending_play, self.seeking = None, False
        self.player.pause()
        self.log.info("暂停请求：%s；位置=%.3f", source, self.player.position)
        self._update_play_buttons()

    def begin_seek(self):
        if not self.plan:
            return
        self.pause("拖动进度")
        self.seeking = True
        self.seek_revision = self.transport_revision

    def seek_fraction(self, fraction):
        if not self.plan or not self.seeking or self.seek_revision != self.transport_revision:
            return
        self.player.seek(max(0.0, min(1.0, fraction))*self.plan.duration, self.plan.duration)
        self.current_note = None
        self._update_progress()
        self.draw_keys()
        self.status.set("定位至 " + clock_label(self.player.position))
        self.detail.set("松开进度后按 F8 从此处继续；F9 停止并回到" + ("首个片段。" if self.segments else "曲首。"))

    def end_seek(self):
        self.seeking = False
        self._update_play_buttons()

    def _seek_fraction_at(self, event):
        return (event.x-8)/max(1, self.progress.winfo_width()-16)

    def _seek_press(self, event):
        self.progress.focus_set()
        self.begin_seek()
        self.seek_fraction(self._seek_fraction_at(event))
        return "break"

    def _seek_motion(self, event):
        if self.seeking:
            self.seek_fraction(self._seek_fraction_at(event))
        return "break"

    def _seek_release(self, event):
        if self.seeking:
            self.seek_fraction(self._seek_fraction_at(event))
            self.end_seek()
        return "break"

    def _seek_key(self, step=0, to_end=None):
        if self.plan:
            position = self.plan.duration if to_end else 0 if to_end is False else self.player.position+step
            self.begin_seek()
            self.seek_fraction(position/max(self.plan.duration, 0.01))
            self.end_seek()
        return "break"

    def _update_progress(self):
        if self.plan:
            elapsed = min(self.plan.duration, self.player.position)
            self.elapsed.set(f"{clock_label(elapsed)} / {clock_label(self.plan.duration)}")
            self.progress["value"] = elapsed/max(self.plan.duration, 0.01)*100
            self.draw_roll(elapsed)

    def _poll(self):
        if self.closing:
            return
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "player":
                    run_id, kind, value = value
                    if run_id != self.player.run_id:
                        continue
                    if self.player.cancel.is_set() and kind != "done":
                        continue
                if kind == "toggle":
                    self.log.info("收到 F8 热键；当前忙碌=%s", self.busy)
                    self.overlay.toggle_play()
                elif kind == "overlay":
                    self.log.info("收到 F7 悬浮窗热键")
                    self.overlay.toggle_edit()
                elif kind == "overlay_visibility":
                    self.log.info("切换悬浮窗显示 / 隐藏")
                    self.overlay.toggle_visibility()
                elif kind in ("speed", "transpose"):
                    if not self.root.grab_current():
                        (self.change_speed if kind == "speed" else self.change_transpose)(value)
                elif kind == "show_main":
                    self.show_main()
                elif kind == "stop":
                    self.stop("系统托盘")
                elif kind == "stop_ui":
                    if value == (self.player.run_id, self.transport_revision):
                        self.pending_play, self.seeking, self.current_note = None, False, None
                        beginning = "首个片段" if self.segments else "曲首"
                        self.status.set("已停止 · 回到" + beginning)
                        self.detail.set(f"按 F8 从{beginning}播放，或拖动进度选择位置。")
                        self._set_busy(self.player.active)
                        self._update_progress()
                        self.draw_keys()
                elif kind == "exit":
                    self.close()
                    return
                elif kind == "tray_ready":
                    self.log.info("系统托盘已就绪")
                elif kind == "tray_error":
                    self.log.error("系统托盘不可用：%s", value)
                    self.show_main()
                    self.status.set("系统托盘不可用")
                    self.detail.set("暂时保留主窗口，请用下方“退出程序”结束运行。" + value)
                    self.exit_button.pack(side="right", padx=12)
                elif kind == "online_catalog_result":
                    token, songs, error = value
                    if token != self.online_operation or self.online_operation_kind != "catalog":
                        continue
                    self.online_operation = self.online_operation_kind = None
                    if not self._online_dialog_alive():
                        continue
                    self.online_catalog_list.configure(state="normal")
                    if error:
                        self.log.warning("读取线上曲库失败：%s", error)
                        self.online_catalog = []
                        self.online_catalog_list.delete(0, "end")
                        self.online_catalog_status.set("无法读取线上曲库，请检查网络后点击“刷新目录”重试。")
                        self.online_catalog_detail.set(str(error))
                        self.online_download_button.configure(state="disabled")
                        continue
                    self.online_catalog = songs
                    self.online_catalog_list.delete(0, "end")
                    for song in songs:
                        label = song.title + (f"  ·  {song.artist}" if song.artist else "")
                        self.online_catalog_list.insert("end", "  " + label)
                    self.online_catalog_status.set(f"已读取 {len(songs)} 首曲目。双击或选择后点击下载。")
                    if songs:
                        self.online_catalog_list.selection_set(0)
                        self.online_catalog_list.see(0)
                        self._select_online_song()
                    else:
                        self.online_catalog_detail.set("官网暂时没有可下载的曲目。")
                        self.online_download_button.configure(state="disabled")
                elif kind == "online_download_result":
                    token, song, path, error = value
                    if token != self.online_operation or self.online_operation_kind != "download":
                        continue
                    self.online_operation = self.online_operation_kind = None
                    if error:
                        self.log.warning("下载线上曲目失败：%s；曲目=%s", error, song.title)
                        if self._online_dialog_alive():
                            self.online_catalog_list.configure(state="normal")
                            self.online_catalog_status.set(f"下载“{song.title}”失败：{error}")
                            self._select_online_song()
                        continue
                    self.online_downloaded_ids.add(song.song_id)
                    if self._online_dialog_alive():
                        self.online_catalog_list.configure(state="normal")
                        self.online_catalog_status.set(f"已下载“{song.title}”，已加入本地曲库。")
                        self._select_online_song()
                    self.log.info("线上曲目已下载：标题=%s；文件=%s", song.title, path)
                    self._load_library(path)
                    self.detail.set(f"已从线上曲库下载“{song.title}”。")
                elif kind == "update_result":
                    automatic, manifest, error = value
                    self.update_checking = False
                    if error:
                        self.log.warning("检查更新失败：%s", error)
                        if not automatic:
                            self.status.set("检查更新失败")
                            self.detail.set("无法连接官网，请稍后重试。")
                            messagebox.showwarning("检查更新失败", f"暂时无法读取版本信息：\n{error}", parent=self.root)
                        continue
                    if manifest["version_tuple"] <= parse_version(APP_VERSION):
                        self.log.info("当前已是最新版本 v%s", APP_VERSION)
                        if not automatic:
                            self.status.set("已是最新版本")
                            self.detail.set(f"当前使用 v{APP_VERSION}，官网没有更新版本。")
                            messagebox.showinfo("检查更新", f"当前已是最新版本 v{APP_VERSION}。", parent=self.root)
                        continue
                    self.log.info("发现新版本 v%s", manifest["version"])
                    self.status.set(f"发现新版本 v{manifest['version']}")
                    self.detail.set("官网已有更新版本，点击提示框即可打开下载页面。")
                    self._show_update_notice(manifest)
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
                    self.status.set(self.playing_mode + "中")
                elif kind == "note":
                    index, note = value
                    if not self.plan or index >= len(self.plan.notes) or note is not self.plan.notes[index]:
                        continue
                    self.current_note = note
                    self.detail.set(f"{index+1} / {len(self.plan.notes)}　{pitch_name(note.fingering.pitch)}　按键：{note.fingering.label}　｜　F9 停止")
                    self.draw_keys()
                elif kind == "release":
                    self.current_note = None
                    self.draw_keys()
                elif kind == "done":
                    status, error = value
                    self.log.info("播放结束：%s；错误=%s", status, error)
                    self.current_note = None
                    self._set_busy(False)
                    self.status.set("已暂停，请检查提示" if error else "已暂停" if self.player.paused else status)
                    beginning = "首个片段" if self.segments else "曲首"
                    self.detail.set(error or ("按 F8 从当前位置继续，或拖动进度定位。" if self.player.paused else f"按 F8 从{beginning}播放，或拖动进度选择位置。"))
                    self.draw_keys()
                    self._update_progress()
        except queue.Empty:
            pass
        if self.busy and not self.seeking:
            self._update_progress()
        if self.pending_play is not None and not self.player.active and not self.seeking:
            preview, self.pending_play = self.pending_play, None
            self._set_busy(False)
            self.play(preview)
        self.poll_timer = self.root.after(40, self._poll)

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

    def draw_roll(self, elapsed=None):
        canvas = self.roll
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 200), max(canvas.winfo_height(), 30)
        if not self.plan:
            return
        if elapsed is None:
            elapsed = self.player.position
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

    def overlay_visibility_changed(self, visible):
        self.overlay_button_text.set(("隐藏" if visible else "显示") + "悬浮窗  F6")

    def hide_main(self):
        if self.closing:
            return
        # 只有托盘可用时才隐藏，防止用户失去恢复窗口和退出的入口。
        if not self.smoke and (not self.tray or not self.tray.available):
            self.detail.set("系统托盘尚未就绪，暂时保留主窗口。")
            return
        dialog = self.root.grab_current()
        if dialog:
            dialog.lift()
            return
        self.root.withdraw()
        self.log.info("隐藏主窗口，后台和 F6 / F7 / F8 / F9 热键继续运行")

    def show_main(self):
        if self.closing:
            return
        self.pause("打开主窗口")
        self.overlay.editing = False
        self.overlay._hide()
        self.root.deiconify()
        self.root.update_idletasks()
        self.root.lift()
        try:
            dialog = self.root.grab_current()
            target = dialog if dialog else self.root
            activate_window(window_info(root_window(target.winfo_id())))
        except RuntimeError as error:
            self.detail.set(str(error))

    def close(self):
        if self.closing:
            return
        self.closing = True
        self._close_online_library_dialog()
        self.root.after_cancel(self.poll_timer)
        self.player.close()
        self.overlay.close()
        if self.hotkeys:
            self.hotkeys.close()
        if self.tray:
            self.tray.close()
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
        app.tray = Tray(lambda kind, value: app.events.put((kind, value)))
        def verify():
            nonlocal smoke_exit
            try:
                root.update_idletasks()
                assert app.plan and len(app.plan.notes) == 42
                assert app.settings["keys"][-1] == ","
                assert app.play_button.winfo_ismapped()
                assert app.footer.winfo_y()+app.footer.winfo_height() <= root.winfo_height()
                assert app.footer.winfo_height() >= app.footer.winfo_reqheight()
                assert app.tray.available, "系统托盘未就绪"
                assert app.overlay_button.winfo_ismapped()
                app.hide_main()
                assert root.state() == "withdrawn" and not app.closing
                app.show_main()
                assert root.state() == "normal"
                midi_tested = 0
                for _, source in app.entries:
                    if source[0] == "file" and source[1].suffix.lower() in (".mid", ".midi"):
                        imported = read_midi(source[1])
                        assert compile_plan(imported, app.mapping(), track="auto", style="piano").notes
                        midi_tested += 1
                Path(args.data_dir, "smoke-result.json").write_text(json.dumps({"ok": True, "notes": len(app.plan.notes), "midi_tested": midi_tested, "width": root.winfo_width(), "height": root.winfo_height(), "tray": True, "hide_restore": True}), encoding="utf-8")
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
