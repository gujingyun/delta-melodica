"""统一乐曲编辑窗口；试听使用独立播放器，保存为兼容云同步的曲谱副本。"""
import json
import queue
import re
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import uuid
from bisect import bisect_right

from account_client import atomic_json
from cloud_score import from_song, to_song
from music import (DEMO_SCORES, compile_plan, parse_jianpu, parse_jianpu_space, select_jianpu_space,
                   song_to_jianpu, transpose_jianpu)
from jianpu_editor import ScorePreview, replace_header, score_glyphs, score_metadata, transpose_source
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
        self.preview_trace, self.preview_starts = [], []
        self.preview_run_id = None
        self.playing_span = None
        self.notation, self.source_mode, self.source_url = "simple", "score", ""
        text, bpm = self.source_text()
        self.is_source = self.notation == "jianpu_space"
        self.dialog = app._dialog("编辑乐曲 · 简谱工作台", "1180x800" if self.is_source else "920x710")
        # Windows 的临时对话框没有最大化按钮；编辑器使用普通窗口边框，仍保留模态抓取。
        self.dialog.transient("")
        self.dialog.resizable(True, True)
        self.dialog.minsize(960 if self.is_source else 820, 720 if self.is_source else 650)
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
        header.pack(fill="x", padx=24, pady=(14 if self.is_source else 20, 12))
        track = app.track_combo.get()
        if self.is_source:
            tk.Label(header, text="编辑原谱，边改边看", fg=TEXT, bg=CARD,
                     font=("Microsoft YaHei UI", 17, "bold")).pack(side="left")
            tk.Label(header, text=f"{app.song.title[:35]}  ·  {track[:35]}", fg=MUTED, bg=CARD).pack(side="right")
        else:
            tk.Label(header, text="SCORE EDITOR  /  乐曲编辑", fg=ACCENT, bg=CARD,
                     font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
            tk.Label(header, text="让每个音符，按你的想法演奏", fg=TEXT, bg=CARD,
                     font=("Microsoft YaHei UI", 19, "bold")).pack(anchor="w", pady=(5, 7))
            tk.Label(header, text=f"来源：{app.song.title[:35]}  ·  {track[:35]}", fg=MUTED, bg=CARD,
                     anchor="w").pack(fill="x")
        fields = tk.Frame(self.dialog, bg=CARD)
        fields.pack(fill="x", padx=24, pady=(0, 12))
        fields.columnconfigure(0, weight=1)
        for column, (label, variable, width) in enumerate((
                ("保存曲名", self.name, 28), ("BPM · 跟随谱文" if self.is_source else "BPM · 整体速度", self.bpm, 12), ("演奏方式", self.style, 19))):
            box = tk.Frame(fields, bg=CARD)
            box.grid(row=0, column=column, sticky="ew", padx=(0, 14 if column < 2 else 0))
            tk.Label(box, text=label, fg=MUTED, bg=CARD, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(0, 5))
            widget = ttk.Combobox(box, textvariable=variable, values=list(PLAY_STYLES), state="readonly", width=width) if column == 2 else ttk.Entry(box, textvariable=variable, width=width)
            if column == 1 and self.is_source:
                widget.configure(state="readonly")
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
        help_text = ("原谱写法：1' 高八度  1, 低八度  1_ 半拍  1= 四分之一拍  1- 两拍  | 小节  L: 歌词\n"
                     "调号和 BPM 写在谱文中；点击右侧音符定位文字，选段试听保留调号、变速和转调。" if self.is_source else
                     "1～7 音阶   +1 高八度   -1 低八度   #4 升半音   b3 降半音   0 休止\n"
                     "1:2 两拍；1:1/2 半拍；(1 2 3) 连奏。空格分隔，试听时选中完整音符及括号。")
        tk.Label(help_box, text=help_text, wraplength=850 if self.is_source else 0,
                 fg=MUTED, bg=BG, justify="left", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=12, pady=10)
        if self.is_source:
            symbols = tk.Frame(self.dialog, bg=CARD)
            symbols.pack(fill="x", padx=24, pady=(0, 10))
            self.symbol_buttons = {}
            ttk.Style(self.dialog).configure("ScoreSymbol.TButton", font=("Microsoft YaHei UI", 9), padding=(5, 4))
            for label, symbol in (("升音 #", "#"), ("高音 '", "'"), ("低音 ,", ","), ("半拍 _", "_"),
                                  ("¼ 拍 =", "="), ("延长 -", "-"), ("附点 .", "."), ("小节 |", "|")):
                button = ttk.Button(symbols, text=label, width=6, style="ScoreSymbol.TButton",
                                    command=lambda s=symbol: self.insert_symbol(s))
                button.pack(side="left", padx=(0, 4))
                self.symbol_buttons[symbol] = button
            ttk.Button(symbols, text="调号", width=5, style="ScoreSymbol.TButton", command=lambda: self.edit_header("key")).pack(side="right")
            ttk.Button(symbols, text="速度", width=5, style="ScoreSymbol.TButton", command=lambda: self.edit_header("tempo")).pack(side="right", padx=4)
            split = tk.PanedWindow(self.dialog, orient="horizontal", bg=LINE, sashwidth=7, bd=0)
            split.pack(fill="both", expand=True, padx=24)
            left, right = tk.Frame(split, bg=CARD), tk.Frame(split, bg=CARD)
            split.add(left, minsize=300, width=500, stretch="always")
            split.add(right, minsize=300, stretch="always")
            tk.Label(left, text="谱文 · 保留原谱调号、速度与歌词", bg=CARD, fg=MUTED, anchor="w").pack(fill="x", pady=(0, 7))
            mode = "按谱面规则" if self.source_mode == "score" else "跟随源站播放"
            tk.Label(right, text=f"谱面预览 · 绿色标记跟随试听 · {mode}", bg=CARD, fg=MUTED, anchor="w").pack(fill="x", pady=(0, 7))
            self.score_preview = ScorePreview(right, self.select_range)
            self.score_preview.pack(fill="both", expand=True)
            editor_box = tk.Frame(left, bg=DEEP, highlightbackground=LINE, highlightthickness=1)
            editor_box.pack(fill="both", expand=True)
        else:
            tk.Label(self.dialog, text="MIDI 按所选音轨转为完整原速旋律；精确拍数保留节奏，修改 BPM 可整体调速。",
                     fg=MUTED, bg=CARD, font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=24, pady=(0, 8))
            editor_box = tk.Frame(self.dialog, bg=DEEP, highlightbackground=LINE, highlightthickness=1)
            editor_box.pack(fill="both", expand=True, padx=24)
        self.text = tk.Text(editor_box, bg=DEEP, fg=TEXT, insertbackground=ACCENT, selectbackground="#35472b",
                            selectforeground=ACCENT, wrap="word", bd=0, padx=16, pady=14,
                            font=("Consolas", 13 if self.is_source else 15), spacing1=5, spacing3=5, undo=True, autoseparators=True,
                            maxundo=100, exportselection=False)
        scroll = ttk.Scrollbar(editor_box, command=self.text.yview)
        scroll.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("playing", background="#c6ef86", foreground="#182318")
        self.text.insert("1.0", text)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.initial = self.snapshot()
        self.text.bind("<<Modified>>", self.changed)
        self.text.bind("<Control-a>", self.select_all)
        for variable in ((self.name, self.style) if self.is_source else (self.name, self.bpm, self.style)):
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
            original = data.get("jianpu_source")
            candidates = []
            if isinstance(saved, dict) and saved.get("format") == "jianpu_space":
                candidates.append((saved.get("score"), saved.get("mode", "score"), saved.get("source_url", "")))
            if isinstance(original, dict):
                candidates.append((original.get("text"), original.get("mode", "source"), original.get("url", "")))
            for raw, mode, url in candidates:
                try:
                    parsed, _ = parse_jianpu_space(raw, data["title"], mode=mode)
                    if from_song(parsed) == from_song(to_song(data)):
                        self.notation, self.source_mode, self.source_url = "jianpu_space", mode, url
                        return raw, f"{score_metadata(raw)[1]:g}"
                except (KeyError, ValueError, TypeError):
                    pass
            if isinstance(saved, dict):
                try:
                    parsed = parse_jianpu(saved["score"], float(saved["bpm"]), data["title"], precise=True)
                    if from_song(parsed) == from_song(to_song(data)):
                        return saved["score"], saved["bpm"]
                except (KeyError, ValueError, TypeError):
                    pass
        return song_to_jianpu(self.app.song, self.app.track_ids[self.app.track_combo.current()],
                              self.styles[self.app.arrangement.get()]), 120

    def snapshot(self):
        return self.name.get(), self.bpm.get(), self.style.get(), self.text.get("1.0", "end-1c")

    def parsed(self, selection=False, trace=None):
        if selection:
            if not self.text.tag_ranges("sel"):
                raise ValueError("请先在简谱中选中一段完整音符。")
            score = self.text.get("sel.first", "sel.last")
        else:
            score = self.text.get("1.0", "end-1c")
        title = self.name.get().strip()
        if not title or len(title) > 100 or any(ord(c) < 32 for c in title):
            raise ValueError("曲名需为 1～100 个字符。")
        if self.is_source:
            if selection:
                start = len(self.text.get("1.0", "sel.first"))
                end = len(self.text.get("1.0", "sel.last"))
                return select_jianpu_space(self.text.get("1.0", "end-1c"), title, start, end,
                                           mode=self.source_mode, trace=trace)
            return parse_jianpu_space(score, title, mode=self.source_mode, trace=trace)[0]
        try:
            bpm = float(self.bpm.get())
        except ValueError:
            raise ValueError("BPM 请填写 20～300 之间的数字。") from None
        return parse_jianpu(score, bpm, title, precise=True)

    def select_all(self, event=None):
        self.text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def text_index(self, offset):
        return f"1.0+{offset}c"

    def select_range(self, start, end):
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", self.text_index(start), self.text_index(end))
        self.text.mark_set("insert", self.text_index(end))
        self.text.see(self.text_index(start))
        self.text.focus_set()

    def replace_range(self, start, end, replacement):
        left, right = self.text_index(start), self.text_index(end)
        self.text.edit_separator()
        self.text.configure(autoseparators=False)
        self.text.delete(left, right)
        self.text.insert(left, replacement)
        self.text.edit_separator()
        self.text.configure(autoseparators=True)
        self.text.tag_remove("sel", "1.0", "end")
        self.text.focus_set()

    def insert_symbol(self, symbol):
        text = self.text.get("1.0", "end-1c")
        selection = self.text.tag_ranges("sel")
        start = len(self.text.get("1.0", "sel.first" if selection else "insert"))
        end = len(self.text.get("1.0", "sel.last" if selection else "insert"))
        glyph = next((g for g in score_glyphs(text) if g.kind == "note" and
                      ((g.start == start and g.end == end) if selection else (g.start < start <= g.end))), None)
        if glyph and symbol != "|":
            accidental, degree, octave, length, dots = glyph.parts
            accidental = accidental or ""
            if degree in ("0", "-") and symbol in ("#", "'", ","):
                self.status.set("休止符和延音线不需要八度或升降号。")
                return
            if symbol == "#":
                accidental = accidental[1:] if accidental.startswith("b") else (accidental.replace("n", "") + "#")[:2]
            elif symbol in ("'", ","):
                octave = octave[:-1] if octave and not octave.startswith(symbol) else octave + symbol
            elif symbol in ("_", "="):
                length = symbol
            elif symbol == "-":
                length = length + "-" if length.startswith("-") else "-"
            elif symbol == ".":
                dots = (dots + ".")[:2]
            replacement = accidental + degree + octave + length + dots
            self.replace_range(glyph.start, glyph.end, replacement)
        else:
            # 小节线添加到所选音符后；不会用一个符号覆盖整段旋律。
            self.replace_range(end, end, symbol)

    def edit_header(self, kind):
        text = self.text.get("1.0", "end-1c")
        key, bpm = score_metadata(text)
        if kind == "key":
            value = simpledialog.askstring("起始调号", "填写调号，例如 C4、A3、F#4；其余段落调号保留。",
                                           initialvalue=key, parent=self.dialog)
            if value is None:
                return
            value = value.strip()
            if not re.fullmatch(r"[A-Ga-g][#b]?[0-9]?", value):
                messagebox.showerror("调号无效", "请填写 C4、A3、F#4 等调号。", parent=self.dialog)
                return
        else:
            value = simpledialog.askfloat("起始速度", "填写 20～500 BPM；其余段落的 bpm 标记保留。",
                                         initialvalue=bpm, minvalue=20, maxvalue=500, parent=self.dialog)
            if value is None:
                return
        result = replace_header(text, kind, value)
        try:
            parse_jianpu_space(result, self.name.get(), mode=self.source_mode)
        except ValueError as error:
            messagebox.showerror("无法应用", str(error), parent=self.dialog)
            return
        self.replace_range(0, len(text), result)

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
        if self.validation_timer:
            self.dialog.after_cancel(self.validation_timer)
        self.validation_timer = None
        try:
            song = self.parsed()
            if self.is_source:
                text = self.text.get("1.0", "end-1c")
                self.bpm.set(f"{score_metadata(text)[1]:g}")
                self.score_preview.show(text)
                self.text.tag_remove("error", "1.0", "end")
                self.text.tag_configure("lyric", foreground="#a6afa0")
                self.text.tag_configure("directive", foreground="#c6ef86")
                for tag in ("lyric", "directive"):
                    self.text.tag_remove(tag, "1.0", "end")
                for number, line in enumerate(text.splitlines(), 1):
                    if line.lstrip().startswith("L:"):
                        self.text.tag_add("lyric", f"{number}.0", f"{number}.end")
                for glyph in self.score_preview.glyphs:
                    if glyph.kind in ("key", "tempo"):
                        self.text.tag_add("directive", self.text_index(glyph.start), self.text_index(glyph.end))
            self.summary.set(f"{len(song.notes)} 音  ·  {song.duration:.2f} 秒")
            self.status.set("修改尚未保存 · 可试听全曲或选中片段。" if self.snapshot() != self.initial else
                            "修改后可先试听，再另存到曲库。原曲会保留。")
        except ValueError as error:
            self.summary.set("请检查简谱")
            self.status.set(str(error))
            if self.is_source:
                self.score_preview.show("", str(error))
                self.text.tag_configure("error", background="#633c26")
                self.text.tag_remove("error", "1.0", "end")
                line = re.search(r"第 (\d+) 行", str(error))
                if line:
                    self.text.tag_add("error", f"{line[1]}.0", f"{line[1]}.end")

    def transpose(self):
        try:
            self.parsed()
            text = self.text.get("1.0", "end-1c")
            result = (transpose_source(text, int(self.shift.get()), self.source_mode) if self.is_source
                      else transpose_jianpu(text, int(self.shift.get())))
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
            trace = []
            song = self.parsed(selection, trace=trace)
            # 试听使用保存后相同的毫秒曲谱，避免保存前后节奏不同。
            from cloud_score import to_song
            plan = compile_plan(to_song(from_song(song)), self.app.mapping(), track="auto",
                                style=self.styles[self.style.get()])
            # 先完成待处理的谱文校验，避免延迟回调在试听期间重画并清空标记。
            if self.validation_timer:
                self.validate()
            self.preview_trace = [(left, right, round(start*1000)/1000, round(end*1000)/1000)
                                  for left, right, start, end in trace]
            self.preview_starts = [item[2] for item in self.preview_trace]
            self.player.start(plan, PreviewOutput, gate=self.app.settings["gate"]/100)
            self.preview_run_id = self.player.run_id
            self.status.set("正在试听" + ("选中片段" if selection else "全曲") + " · F9 停止")
        except (ValueError, RuntimeError) as error:
            messagebox.showerror("无法试听", str(error), parent=self.dialog)

    def stop_preview(self):
        # F9 可从热键线程调用；这里不访问任何 Tk 控件。
        self.player.stop()

    def update_playing_position(self):
        """只在 Tk 主线程读取播放器时钟；反复、休止和延音按原谱片段定位。"""
        span = None
        if (self.is_source and self.player.active and not self.player.cancel.is_set()
                and self.preview_run_id == self.player.run_id):
            position = self.player.position
            index = bisect_right(self.preview_starts, position) - 1
            if index >= 0 and position < self.preview_trace[index][3]:
                span = self.preview_trace[index][:2]
        if span == self.playing_span:
            return
        self.playing_span = span
        self.text.tag_remove("playing", "1.0", "end")
        if self.is_source:
            self.score_preview.mark_playing(span)
        if span:
            start, end = (self.text_index(offset) for offset in span)
            self.text.tag_add("playing", start, end)
            # 播放标记独立于选区，不移动编辑光标或改变选段试听的范围。
            self.text.tag_raise("sel")
            self.text.see(start)

    def poll(self):
        try:
            while True:
                run_id, kind, value = self.events.get_nowait()
                if run_id == self.player.run_id and kind == "done":
                    status, error = value
                    self.status.set(f"试听失败：{error}" if error else status)
        except queue.Empty:
            pass
        self.update_playing_position()
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
            if self.is_source:
                data["editor"].update(format="jianpu_space", mode=self.source_mode, source_url=self.source_url,
                                      bpm=score_metadata(data["editor"]["score"])[1])
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
