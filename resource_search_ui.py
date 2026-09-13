"""聚合搜索窗口；网络线程只使用普通数据和队列。"""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser

from resource_search import SOURCES, SearchCancelled, download_resource, search_all, search_url


def _download_worker(song, folder, mapping, cancel, events, preview):
    try:
        path = download_resource(song, folder, mapping, cancel)
        events.put(("download", (song, path, preview, None)))
    except SearchCancelled:
        pass
    except Exception as error:
        events.put(("download", (song, None, preview, str(error))))


class ResourceSearchDialog:
    def __init__(self, app, query=""):
        self.app = app
        self.library_dir = Path(app.library_dir)
        self.closed = False
        self.search_cancel = threading.Event()
        self.download_cancel = threading.Event()
        self.events = queue.Queue()
        self.pending, self.pages, self.more, self.songs = set(), {}, set(), {}
        self.source_status = {}
        self.downloading = False
        self.active_query = ""
        self.dialog = app._dialog("聚合搜索音乐", "960x680")
        self.dialog.minsize(860, 630)
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.query = tk.StringVar(value=query)
        self.status = tk.StringVar(value="输入曲名或作者，搜索多个 MIDI 资源网站。英文站点建议使用英文曲名。")
        self.detail = tk.StringVar(value="下载后自动选择旋律音轨并转换为八键演奏；完整 MIDI 保留在本地曲库。")
        self.source_summary = tk.StringVar(value="")
        self.enabled = {source: tk.BooleanVar(value=True) for source in SOURCES}
        self._build()
        self.timer = app.root.after(40, self._poll)
        self.entry.focus_set()
        if query.strip():
            self.search()

    def _build(self):
        from app import CARD, DEEP, TEXT, MUTED, ACCENT, ORANGE, LINE
        dialog = self.dialog
        heading = tk.Frame(dialog, bg=CARD)
        heading.pack(fill="x", padx=22, pady=(18, 6))
        tk.Label(heading, text="搜一首，加入你的曲库", bg=CARD, fg=TEXT,
                 font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        ttk.Button(heading, text="浏览官网精选", command=self.browse_official, style="Quiet.TButton").pack(side="right")
        tk.Label(dialog, text="聚合 MIDI 乐谱资源 · 自动转换旋律 · 下载后离线播放", bg=CARD,
                 fg=MUTED).pack(anchor="w", padx=22, pady=(0, 14))
        search = tk.Frame(dialog, bg=CARD)
        search.pack(fill="x", padx=22)
        self.entry = ttk.Entry(search, textvariable=self.query)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda event: self.search())
        self.search_button = ttk.Button(search, text="聚合搜索", command=self.search, style="Accent.TButton")
        self.search_button.pack(side="left", padx=(10, 0))
        self.cancel_button = ttk.Button(search, text="取消搜索", command=self.cancel_search, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        sources = tk.Frame(dialog, bg=CARD)
        sources.pack(fill="x", padx=22, pady=10)
        for source, label in SOURCES.items():
            tk.Checkbutton(sources, text=label, variable=self.enabled[source], bg=CARD, fg=TEXT,
                           selectcolor=DEEP, activebackground=CARD, activeforeground=ACCENT,
                           highlightthickness=0).pack(side="left", padx=(0, 15))
        # 底部先分配固定空间，缩小窗口时仍保留下载、来源和关闭入口。
        bottom = tk.Frame(dialog, bg=CARD)
        bottom.pack(side="bottom", fill="x", padx=22, pady=(10, 18))
        tk.Label(bottom, textvariable=self.detail, bg=CARD, fg=MUTED, justify="left",
                 anchor="w", wraplength=810, height=3).pack(fill="x")
        tk.Label(bottom, textvariable=self.source_summary, bg=CARD, fg=MUTED,
                 anchor="w", justify="left", wraplength=810).pack(fill="x", pady=(4, 0))
        tk.Label(bottom, textvariable=self.status, bg=CARD, fg=ORANGE, justify="left",
                 anchor="w", wraplength=810).pack(fill="x", pady=(6, 10))
        actions = tk.Frame(bottom, bg=CARD)
        actions.pack(fill="x")
        ttk.Button(actions, text="打开源网页", command=self.open_source).pack(side="left")
        ttk.Button(actions, text="导入已下载 MIDI", command=self.import_downloaded).pack(side="left", padx=8)
        self.download_button = ttk.Button(actions, text="下载并转换", command=self.download)
        self.download_button.pack(side="right")
        self.preview_button = ttk.Button(actions, text="下载后试听", command=lambda: self.download(True), style="Accent.TButton")
        self.preview_button.pack(side="right", padx=8)
        navigation = tk.Frame(dialog, bg=CARD)
        navigation.pack(side="bottom", fill="x", padx=22, pady=(8, 0))
        self.more_button = ttk.Button(navigation, text="加载更多", command=self.load_more, state="disabled")
        self.more_button.pack(side="right")
        self.count = tk.StringVar(value="等待搜索")
        tk.Label(navigation, textvariable=self.count, bg=CARD, fg=MUTED).pack(side="left")
        body = tk.Frame(dialog, bg=CARD)
        body.pack(fill="both", expand=True, padx=22)
        style = ttk.Style(dialog)
        style.configure("Resource.Treeview", background=DEEP, fieldbackground=DEEP, foreground=TEXT,
                        rowheight=32, borderwidth=0, font=("Microsoft YaHei UI", 10))
        style.map("Resource.Treeview", background=[("selected", "#354a38")], foreground=[("selected", ACCENT)])
        style.configure("Resource.Treeview.Heading", background=LINE, foreground=TEXT,
                        font=("Microsoft YaHei UI", 10, "bold"), padding=(8, 8))
        self.tree = ttk.Treeview(body, columns=("title", "source", "access"), show="headings", selectmode="browse",
                                 height=9, style="Resource.Treeview")
        for name, title, width in (("title", "曲名 / 作者", 470), ("source", "来源", 105), ("access", "下载方式", 155)):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=80, stretch=name == "title")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.select)
        self.tree.bind("<Double-Button-1>", lambda event: self.download())
        self._buttons()

    def selected(self):
        selection = self.tree.selection()
        return self.songs.get(selection[0]) if selection else None

    def _buttons(self):
        song = self.selected()
        can_download = song and song.downloadable and not self.downloading
        for button in (self.download_button, self.preview_button):
            button.configure(state="normal" if can_download else "disabled")
        self.more_button.configure(state="normal" if self.more and not self.pending and not self.downloading else "disabled")
        self.search_button.configure(state="disabled" if self.downloading else "normal")
        self.cancel_button.configure(state="normal" if self.pending else "disabled")

    def select(self, event=None):
        song = self.selected()
        if song:
            condition = "可直接下载，自动转换后加入曲库。" if song.downloadable else "需到 MidiShow 登录并按积分规则下载，再点击“导入已下载 MIDI”。"
            self.detail.set(f"{song.title} · {SOURCES[song.source]}\n{condition}")
        self._buttons()

    def search(self):
        if self.downloading:
            return
        query = self.query.get().strip()
        sources = [source for source, enabled in self.enabled.items() if enabled.get()]
        if not query or len(query) > 100 or not sources:
            self.status.set("请填写 1～100 个字符的曲名或作者，并至少选择一个来源。")
            return
        self.search_cancel.set()
        # 每次新搜索使用独立队列，旧请求即使晚到也不会混入当前结果。
        self.events = queue.Queue()
        self.active_query = query
        self.pages, self.more, self.songs, self.source_status = {}, set(), {}, {}
        self.tree.delete(*self.tree.get_children())
        self.detail.set("各站结果将陆续显示；选择曲目可查看下载方式。")
        self._start({source: 1 for source in sources})

    def _start(self, pages):
        self.search_cancel = threading.Event()
        self.pending = set(pages)
        self.requested_pages = pages
        for source in pages:
            self.source_status[source] = "搜索中…"
        self.status.set(f"正在搜索“{self.active_query}”…")
        self._summary()
        threading.Thread(target=search_all, args=(self.active_query, pages, self.search_cancel, self.events), daemon=True).start()

    def load_more(self):
        if self.pending or self.downloading or not self.more:
            return
        self._start({source: self.pages[source] + 1 for source in self.more})

    def cancel_search(self):
        self.search_cancel.set()
        for source in self.pending:
            self.source_status[source] = "已取消"
        self.pending.clear()
        self.status.set("搜索已取消，已找到的曲目仍可下载。")
        self._summary()

    def _summary(self):
        self.source_summary.set("\n".join(f"{SOURCES[source]}：{self.source_status[source]}"
                                              for source in SOURCES if source in self.source_status))
        self.count.set(f"已找到 {len(self.songs)} 首 · 搜索中 {len(self.pending)} 个来源" if self.pending else f"共 {len(self.songs)} 首")
        self._buttons()

    def download(self, preview=False):
        song = self.selected()
        if not song or self.downloading or self.app.busy:
            return
        if not song.downloadable:
            self.select()
            return
        self.downloading = True
        self.status.set(f"正在下载并转换“{song.title}”…")
        self._buttons()
        threading.Thread(target=_download_worker, args=(song, self.library_dir, self.app.mapping(),
                                                        self.download_cancel, self.events, preview), daemon=True).start()

    def _poll(self):
        if self.closed:
            return
        if self.app.closing or Path(self.app.library_dir) != self.library_dir:
            self.close()
            return
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "source":
                    source, page, error = value
                    if source not in self.pending:
                        continue
                    self.pending.remove(source)
                    if error:
                        self.source_status[source] = f"不可用：{error[:130]}"
                        self.app.log.warning("聚合搜索失败：来源=%s；%s", source, error)
                    else:
                        self.pages[source] = self.requested_pages[source]
                        self.more.discard(source)
                        if page.has_more:
                            self.more.add(source)
                        known = {song.key for song in self.songs.values()}
                        for song in page.songs:
                            if song.key in known:
                                continue
                            known.add(song.key)
                            item = str(len(self.songs))
                            self.songs[item] = song
                            self.tree.insert("", "end", iid=item, values=(song.title + (f" · {song.artist}" if song.artist else ""),
                                             SOURCES[source], "直接下载" if song.downloadable else "源站登录 / 积分"))
                        self.source_status[source] = f"第 {self.pages[source]} 页 · {len(page.songs)} 首"
                    if self.songs and not self.tree.selection():
                        self.tree.selection_set(next(iter(self.songs)))
                        self.select()
                    if not self.pending and not self.downloading:
                        self.status.set("搜索完成。选择曲目下载，或加载更多结果；不可用的来源可重新搜索。" if self.songs
                                        else "未找到可用结果。可换用别名或英文名，也可打开源站搜索。")
                    self._summary()
                elif kind == "download":
                    song, path, preview, error = value
                    self.downloading = False
                    self._buttons()
                    if error:
                        self.status.set(f"下载转换失败：{error[:220]}。可打开源网页查看。")
                        self.app.log.warning("聚合下载失败：%s；%s", song.page_url, error)
                        continue
                    self.app.log.info("聚合下载完成：%s；来源=%s；网页=%s；文件=%s", song.title, song.source, song.page_url, path)
                    self.app._load_library(path)
                    self.status.set(f"已下载并转换“{song.title}”，已选入本地曲库；关闭此窗口后可按 F8 游戏演奏。")
                    self.app.detail.set(f"已从 {SOURCES[song.source]} 下载并转换“{song.title}”。")
                    if preview:
                        self.close()
                        self.app.play(preview=True)
                        return
        except queue.Empty:
            pass
        self.timer = self.app.root.after(40, self._poll)

    def open_source(self):
        song = self.selected()
        if song:
            webbrowser.open(song.page_url)
        elif self.query.get().strip():
            source = next((source for source in ("midishow", "bitmidi", "midiworld", "official")
                           if self.enabled[source].get()), "midishow")
            webbrowser.open(search_url(source, self.query.get().strip()))

    def import_downloaded(self):
        if self.downloading:
            return
        self.close()
        self.app.import_midi()

    def browse_official(self):
        if self.downloading:
            return
        self.close()
        self.app.online_library_dialog()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.search_cancel.set()
        self.download_cancel.set()
        self.app.root.after_cancel(self.timer)
        self.dialog.destroy()
        if self.app.resource_search is self:
            self.app.resource_search = None
