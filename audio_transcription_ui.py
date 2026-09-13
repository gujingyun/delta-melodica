"""音频扒谱窗口：选择片段、取消转换、试听并进入既有编辑器。"""
from pathlib import Path
import queue
import tkinter as tk
from tkinter import ttk, filedialog

from audio_transcription import AudioOptions, AudioTranscription


class AudioTranscriptionDialog:
    def __init__(self, app):
        from app import CARD, BG, TEXT, MUTED, ACCENT
        self.app, self.library_dir = app, Path(app.library_dir)
        self.job, self.result_path = None, None
        self.closed = False
        self.dialog = app._dialog("MP3 自动扒谱", "780x530")
        self.dialog.minsize(740, 510)
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.path = tk.StringVar(self.dialog)
        self.mode = tk.StringVar(self.dialog, value="vocal")
        self.start_seconds = tk.StringVar(self.dialog, value="0")
        self.duration = tk.StringVar(self.dialog, value="30")
        self.status = tk.StringVar(self.dialog, value="先选 30 秒试听效果；自动跳过开头静音，生成的旋律可继续编辑修正。")
        self.summary = tk.StringVar(self.dialog, value="等待选择音频")
        tk.Label(self.dialog, text="AUDIO TO SCORE  /  音频转曲谱", bg=CARD, fg=ACCENT,
                 font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", padx=24, pady=(22, 6))
        tk.Label(self.dialog, text="把你想听的旋律，变成可演奏的曲谱", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 17, "bold")).pack(anchor="w", padx=24, pady=(0, 16))
        footer = tk.Frame(self.dialog, bg=CARD)
        footer.pack(side="bottom", fill="x", padx=24, pady=(12, 22))
        tk.Label(footer, textvariable=self.status, bg=CARD, fg=MUTED, anchor="w", justify="left",
                 wraplength=685, height=3).pack(fill="x", pady=(0, 10))
        actions = tk.Frame(footer, bg=CARD)
        actions.pack(fill="x")
        self.run_button = ttk.Button(actions, text="开始扒谱", command=self.run, style="Accent.TButton")
        self.run_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="取消扒谱", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        self.preview_button = ttk.Button(actions, text="试听扒谱结果", command=self.preview, state="disabled")
        self.preview_button.pack(side="right")
        self.edit_button = ttk.Button(actions, text="编辑曲谱", command=self.edit, state="disabled")
        self.edit_button.pack(side="right", padx=8)
        body = tk.Frame(self.dialog, bg=CARD)
        body.pack(fill="both", expand=True, padx=24)
        file_row = tk.Frame(body, bg=CARD)
        file_row.pack(fill="x")
        ttk.Entry(file_row, textvariable=self.path, state="readonly").pack(side="left", fill="x", expand=True)
        self.browse_button = ttk.Button(file_row, text="选择音频…", command=self.browse)
        self.browse_button.pack(side="right", padx=(10, 0))
        tk.Label(body, text="支持 MP3 / WAV / FLAC / OGG · 本机处理 · 单次最多 10 分钟", bg=CARD,
                 fg=MUTED, anchor="w").pack(fill="x", pady=(5, 15))
        modes = tk.Frame(body, bg=CARD)
        modes.pack(fill="x")
        self.mode_buttons = []
        for label, value in (("人声歌曲 · 先分离人声", "vocal"), ("独奏 / 纯音乐 · 直接识别", "solo")):
            button = tk.Radiobutton(modes, text=label, variable=self.mode, value=value, bg=CARD, fg=TEXT,
                                    selectcolor=BG, activebackground=CARD, activeforeground=ACCENT)
            button.pack(side="left", padx=(0, 18))
            self.mode_buttons.append(button)
        fields = tk.Frame(body, bg=CARD)
        fields.pack(fill="x", pady=15)
        tk.Label(fields, text="起点（秒）", bg=CARD, fg=MUTED).pack(side="left")
        self.start_entry = ttk.Entry(fields, textvariable=self.start_seconds, width=8)
        self.start_entry.pack(side="left", padx=(8, 24))
        tk.Label(fields, text="时长（秒）", bg=CARD, fg=MUTED).pack(side="left")
        self.duration_combo = ttk.Combobox(fields, textvariable=self.duration, values=("30", "60", "120", "整首"), width=8)
        self.duration_combo.pack(side="left", padx=8)
        tk.Label(body, textvariable=self.summary, bg=CARD, fg=ACCENT, anchor="w").pack(fill="x", pady=(2, 8))
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(fill="x")
        self.timer = app.root.after(80, self.poll)

    def browse(self):
        filename = filedialog.askopenfilename(parent=self.dialog, title="选择要扒谱的音频",
            filetypes=[("音乐音频", "*.mp3 *.wav *.flac *.ogg")])
        if filename:
            self.path.set(filename)
            self.result_path = None
            self.summary.set(Path(filename).name)
            self.buttons(False)

    def buttons(self, running):
        for widget in (self.run_button, self.browse_button, self.start_entry, self.duration_combo, *self.mode_buttons):
            widget.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        for widget in (self.preview_button, self.edit_button):
            widget.configure(state="normal" if self.result_path and not running else "disabled")

    def run(self):
        if self.job and self.job.active:
            return
        try:
            options = AudioOptions(self.mode.get(), float(self.start_seconds.get()),
                                   None if self.duration.get().strip() == "整首" else float(self.duration.get()))
            job = AudioTranscription(self.path.get(), self.library_dir, self.app.mapping(), options)
            job.start()
        except (ValueError, OSError) as error:
            self.status.set(str(error))
            return
        self.job, self.result_path = job, None
        self.buttons(True)
        self.progress.start(15)
        self.summary.set("正在准备扒谱…")
        self.status.set("人声模式会先分离伴奏；长片段耗时较多，可取消后缩短片段重试。")

    def cancel(self):
        if self.job:
            self.job.cancel()
            self.summary.set("正在取消并清理临时文件…")
            self.cancel_button.configure(state="disabled")

    def poll(self):
        if self.closed:
            return
        if self.app.closing or Path(self.app.library_dir) != self.library_dir:
            self.close()
            return
        if self.job:
            try:
                while True:
                    kind, value = self.job.events.get_nowait()
                    if self.job.cancelled.is_set() and kind != "cancelled":
                        continue
                    if kind == "progress":
                        self.summary.set(value)
                    elif kind in ("done", "error", "cancelled"):
                        self.progress.stop()
                        if kind == "done":
                            self.result_path, count, duration = value
                            self.app._load_library(self.result_path)
                            self.summary.set(f"已生成 {count} 个音符 · {duration:.1f} 秒 · 已加入当前曲库")
                            self.status.set("点击“试听扒谱结果”听效果；错音或节奏不准时，可点击“编辑曲谱”修改。")
                            self.app.log.info("音频扒谱完成：%s；音符=%s", self.result_path.name, count)
                        elif kind == "error":
                            self.summary.set("扒谱未完成")
                            self.status.set(value[:260])
                            self.app.log.warning("音频扒谱失败：%s", value)
                        else:
                            self.summary.set("已取消")
                            self.status.set("转换已取消，原始音频与已有曲库保留。")
                        self.buttons(False)
            except queue.Empty:
                pass
        self.timer = self.app.root.after(80, self.poll)

    def preview(self):
        if self.result_path:
            self.app._load_library(self.result_path)
            self.close()
            self.app.play(preview=True)

    def edit(self):
        if self.result_path:
            self.app._load_library(self.result_path)
            self.close()
            self.app.edit_song()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.job:
            self.job.cancel()
        self.progress.stop()
        self.app.root.after_cancel(self.timer)
        self.dialog.destroy()
        if self.app.audio_dialog is self:
            self.app.audio_dialog = None
