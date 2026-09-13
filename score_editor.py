"""统一乐曲编辑窗口；试听使用独立播放器，保存为兼容云同步的曲谱副本。"""
import json
import queue
import tkinter as tk
from tkinter import ttk, messagebox
import uuid

from account_client import atomic_json
from cloud_score import from_song, normalize_score
from music import DEMO_SCORES, compile_plan, parse_jianpu, song_to_jianpu, transpose_jianpu
from player import Player
from win_input import PreviewOutput


class ScoreEditor:
    def __init__(self, app):
        from app import BG, CARD, DEEP, TEXT, MUTED, ACCENT, LINE, PLAY_STYLES
        self.app = app
        self.styles = PLAY_STYLES
        self.events = queue.Queue()
        self.player = Player(lambda run_id, kind, value: self.events.put((run_id, kind, value)))
        self.closed = False
        self.validation_timer = None
        self.saved_path = None
        text, bpm = self.source_text()
        self.dialog = app._dialog("编辑乐曲 · 简谱工作台", "920x710")
        self.dialog.minsize(820, 650)
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        title = app.song.title if app.song.title.endswith(" · 修改版") else app.song.title[:94] + " · 修改版"
        self.name = tk.StringVar(self.dialog, value=title)
        self.bpm = tk.StringVar(self.dialog, value=str(bpm))
        self.style = tk.StringVar(self.dialog, value=app.arrangement.get())
        self.shift = tk.StringVar(self.dialog, value="0")
        self.summary = tk.StringVar(self.dialog)
        self.status = tk.StringVar(self.dialog, value="修改后可先试听，再另存到曲库。原曲会保留。")

        # 先安排底栏，窗口缩小或字体放大时保存和停止仍可见。
        footer = tk.Frame(self.dialog, bg=CARD)
        footer.pack(side="bottom", fill="x", padx=24, pady=(10, 20))
        tk.Label(footer, textvariable=self.status, fg=MUTED, bg=CARD, anchor="w",
                 wraplength=760, justify="left").pack(fill="x", pady=(0, 10))
        actions = tk.Frame(footer, bg=CARD)
        actions.pack(fill="x")
        self.preview_button = ttk.Button(actions, text="▷  试听全曲", command=self.preview)
        self.preview_button.pack(side="left")
        self.selection_button = ttk.Button(actions, text="试听选中", command=lambda: self.preview(True))
        self.selection_button.pack(side="left", padx=8)
        ttk.Button(actions, text="停止  F9", command=self.stop_preview).pack(side="left")
        self.save_button = ttk.Button(actions, text="另存到曲库", style="Accent.TButton", command=self.save)
        self.save_button.pack(side="right")

        header = tk.Frame(self.dialog, bg=CARD)
        header.pack(fill="x", padx=24, pady=(20, 12))
        tk.Label(header, text="SCORE EDITOR  /  乐曲编辑", fg=ACCENT, bg=CARD,
                 font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        tk.Label(header, text="让每个音符，按你的想法演奏", fg=TEXT, bg=CARD,
                 font=("Microsoft YaHei UI", 19, "bold")).pack(anchor="w", pady=(5, 7))
        track = app.track_combo.get()
        tk.Label(header, text=f"来源：{app.song.title[:35]}  ·  {track[:35]}", fg=MUTED, bg=CARD,
                 anchor="w").pack(fill="x")
        fields = tk.Frame(self.dialog, bg=CARD)
        fields.pack(fill="x", padx=24, pady=(0, 12))
        fields.columnconfigure(0, weight=1)
        for column, (label, variable, width) in enumerate((
                ("保存曲名", self.name, 28), ("BPM · 整体速度", self.bpm, 9), ("演奏方式", self.style, 19))):
            box = tk.Frame(fields, bg=CARD)
            box.grid(row=0, column=column, sticky="ew", padx=(0, 14 if column < 2 else 0))
            tk.Label(box, text=label, fg=MUTED, bg=CARD, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(0, 5))
            widget = ttk.Combobox(box, textvariable=variable, values=list(PLAY_STYLES), state="readonly", width=width) if column == 2 else ttk.Entry(box, textvariable=variable, width=width)
            widget.pack(fill="x")

        toolbar = tk.Frame(self.dialog, bg=CARD)
        toolbar.pack(fill="x", padx=24, pady=(0, 8))
        ttk.Button(toolbar, text="撤销", command=lambda: self.history("undo")).pack(side="left")
        ttk.Button(toolbar, text="重做", command=lambda: self.history("redo")).pack(side="left", padx=(6, 14))
        tk.Label(toolbar, text="整曲移调", fg=MUTED, bg=CARD).pack(side="left", padx=(0, 8))
        ttk.Combobox(toolbar, textvariable=self.shift, values=list(range(-24, 25)), state="readonly", width=4).pack(side="left")
        ttk.Button(toolbar, text="应用", command=self.transpose).pack(side="left", padx=6)
        tk.Label(toolbar, textvariable=self.summary, fg=ACCENT, bg=CARD,
                 font=("Microsoft YaHei UI", 9)).pack(side="right")

        help_box = tk.Frame(self.dialog, bg=BG, highlightbackground=LINE, highlightthickness=1)
        help_box.pack(fill="x", padx=24, pady=(0, 10))
        tk.Label(help_box, text="1～7 音阶   +1 高八度   -1 低八度   #4 升半音   b3 降半音   0 休止\n"
                 "默认一拍；1:2 两拍；1:1/2 半拍。空格分隔，选中完整音符可试听片段。",
                 fg=MUTED, bg=BG, justify="left", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=12, pady=10)
        tk.Label(self.dialog, text="MIDI 按所选音轨转为完整原速旋律；精确拍数保留节奏，修改 BPM 可整体调速。",
                 fg=MUTED, bg=CARD, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=24, pady=(0, 8))
        editor_box = tk.Frame(self.dialog, bg=DEEP, highlightbackground=LINE, highlightthickness=1)
        editor_box.pack(fill="both", expand=True, padx=24)
        self.text = tk.Text(editor_box, bg=DEEP, fg=TEXT, insertbackground=ACCENT, selectbackground="#35472b",
                            selectforeground=ACCENT, wrap="word", bd=0, padx=16, pady=14,
                            font=("Consolas", 15), spacing1=5, spacing3=5, undo=True, autoseparators=True,
                            maxundo=100, exportselection=False)
        scroll = ttk.Scrollbar(editor_box, command=self.text.yview)
        scroll.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", text)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.initial = self.snapshot()
        self.text.bind("<<Modified>>", self.changed)
        self.text.bind("<Control-a>", self.select_all)
        for variable in (self.name, self.bpm, self.style):
            variable.trace_add("write", self.changed)
        self.dialog.bind("<Control-s>", lambda event: self.save())
        self.dialog.bind("<Escape>", lambda event: self.close())
        self.validate()
        self.poll_timer = self.dialog.after(50, self.poll)

    def source_text(self):
        source = self.app.current_source
        if source[0] == "demo":
            bpm, score = DEMO_SCORES[source[1]]
            return score, bpm
        if source[1].suffix.lower() == ".json":
            data = json.loads(source[1].read_text(encoding="utf-8"))
            if data.get("version") != 1:
                return data["score"], data["bpm"]
            saved = data.get("editor")
            if isinstance(saved, dict):
                try:
                    parsed = parse_jianpu(saved["score"], float(saved["bpm"]), data["title"], precise=True)
                    if from_song(parsed) == normalize_score(data):
                        return saved["score"], saved["bpm"]
                except (KeyError, ValueError, TypeError):
                    pass
        return song_to_jianpu(self.app.song, self.app.track_ids[self.app.track_combo.current()],
                              self.styles[self.app.arrangement.get()]), 120

    def snapshot(self):
        return self.name.get(), self.bpm.get(), self.style.get(), self.text.get("1.0", "end-1c")

    def parsed(self, selection=False):
        if selection:
            if not self.text.tag_ranges("sel"):
                raise ValueError("请先在简谱中选中一段完整音符。")
            score = self.text.get("sel.first", "sel.last")
        else:
            score = self.text.get("1.0", "end-1c")
        title = self.name.get().strip()
        if not title or len(title) > 100 or any(ord(c) < 32 for c in title):
            raise ValueError("曲名需为 1～100 个字符。")
        try:
            bpm = float(self.bpm.get())
        except ValueError:
            raise ValueError("BPM 请填写 20～300 之间的数字。") from None
        return parse_jianpu(score, bpm, title, precise=True)

    def select_all(self, event=None):
        self.text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def history(self, action):
        try:
            getattr(self.text, "edit_"+action)()
        except tk.TclError:
            pass

    def changed(self, *args):
        if self.closed:
            return
        if args and isinstance(args[0], tk.Event):
            if not self.text.edit_modified():
                return
            self.text.edit_modified(False)
        self.stop_preview()
        if self.validation_timer:
            self.dialog.after_cancel(self.validation_timer)
        self.validation_timer = self.dialog.after(350, self.validate)

    def validate(self):
        self.validation_timer = None
        try:
            song = self.parsed()
            self.summary.set(f"{len(song.notes)} 音  ·  {song.duration:.2f} 秒")
            self.status.set("修改尚未保存 · 可试听全曲或选中片段。" if self.snapshot() != self.initial else
                            "修改后可先试听，再另存到曲库。原曲会保留。")
        except ValueError as error:
            self.summary.set("请检查简谱")
            self.status.set(str(error))

    def transpose(self):
        try:
            self.parsed()
            result = transpose_jianpu(self.text.get("1.0", "end-1c"), int(self.shift.get()))
            if result == self.text.get("1.0", "end-1c"):
                return
            self.text.edit_separator()
            self.text.configure(autoseparators=False)
            self.text.delete("1.0", "end")
            self.text.insert("1.0", result)
            self.text.edit_separator()
            self.text.configure(autoseparators=True)
        except ValueError as error:
            messagebox.showerror("无法移调", str(error), parent=self.dialog)

    def preview(self, selection=False):
        if self.player.active:
            self.status.set("请先停止当前试听。")
            return
        try:
            song = self.parsed(selection)
            # 试听使用保存后相同的毫秒曲谱，避免保存前后节奏不同。
            from cloud_score import to_song
            plan = compile_plan(to_song(from_song(song)), self.app.mapping(), track="auto",
                                style=self.styles[self.style.get()])
            self.player.start(plan, PreviewOutput, gate=self.app.settings["gate"]/100)
            self.status.set("正在试听" + ("选中片段" if selection else "全曲") + " · F9 停止")
        except (ValueError, RuntimeError) as error:
            messagebox.showerror("无法试听", str(error), parent=self.dialog)

    def stop_preview(self):
        # F9 可从热键线程调用；这里不访问任何 Tk 控件。
        self.player.stop()

    def poll(self):
        try:
            while True:
                run_id, kind, value = self.events.get_nowait()
                if run_id == self.player.run_id and kind == "done":
                    status, error = value
                    self.status.set(f"试听失败：{error}" if error else status)
        except queue.Empty:
            pass
        active = self.player.active
        for button in (self.preview_button, self.selection_button):
            button.configure(state="disabled" if active else "normal")
        self.poll_timer = self.dialog.after(50, self.poll)

    def save(self):
        try:
            song = self.parsed()
            data = from_song(song)
            # 本地保留原编辑文字；云同步只传已有的标准音符格式。
            data["editor"] = {"score": self.text.get("1.0", "end-1c"), "bpm": float(self.bpm.get()),
                              "style": self.styles[self.style.get()]}
            safe = "".join(c for c in song.title if c not in '<>:"/\\|?*').rstrip(" .")[:70] or "我的旋律"
            path = self.app.library_dir / f"{uuid.uuid4().hex}__{safe}.json"
            atomic_json(path, data)
        except (ValueError, OSError) as error:
            messagebox.showerror("曲谱未保存", str(error), parent=self.dialog)
            return
        self.saved_path = path
        self.close(force=True)
        self.app._load_library(path)
        self.app.save_song_preferences()
        self.app.detail.set("修改版已保存到曲库，原曲保留。可继续编辑或按 F8 演奏。")

    def close(self, force=False):
        if self.closed:
            return
        if not force and self.snapshot() != self.initial and not messagebox.askyesno(
                "放弃本次修改？", "修改尚未保存，确定关闭编辑器吗？", parent=self.dialog):
            return
        self.closed = True
        if self.validation_timer:
            self.dialog.after_cancel(self.validation_timer)
        self.dialog.after_cancel(self.poll_timer)
        self.player.close()
        self.dialog.destroy()
        self.app.score_editor = None
