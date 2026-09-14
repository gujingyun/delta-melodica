"""账号对话框；联网和文件同步在后台，Tk 更新由主线程队列处理。"""
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox


class AccountPanel:
    def __init__(self, app):
        self.app = app
        self.client = app.account
        self.dialog = None
        self.running = False
        self.buttons = []
        self.caption = tk.StringVar(value=self.label())

    def label(self):
        return "账号 · " + self.client.user["email"] if self.client.user else "游客模式 · 本地功能可用"

    def show(self):
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.lift()
            return
        if self.app.busy:
            self.app.pause("打开账号面板")
        self.dialog = self.app._dialog("账号与云端曲库", "540x650")
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.render()

    def close(self):
        if self.running:
            self.message.set("正在处理，请稍候；本地曲谱会保留。")
            return
        if self.dialog:
            self.dialog.destroy()
        self.dialog = None

    def render(self):
        from app import BG, TEXT, MUTED
        for child in self.dialog.winfo_children():
            child.destroy()
        self.buttons = []
        box = tk.Frame(self.dialog, bg=BG)
        box.pack(fill="both", expand=True, padx=28, pady=24)
        tk.Label(box, text=self.label(), bg=BG, fg=TEXT, wraplength=450,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", pady=(0, 12))
        self.message = tk.StringVar(value=self.client.warning)
        if self.client.user:
            self.dialog.geometry("540x650")
            tk.Label(box, text="账号曲库支持离线演奏。点击同步会合并本机和云端曲目。\n速度、移调和片段设置保留在当前设备。",
                     bg=BG, fg=MUTED, justify="left", wraplength=450).pack(anchor="w", pady=(0, 12))
            self.button(box, "同步我的云端曲库", self.sync)
            self.button(box, "合并本机游客曲库…", self.merge)
            self.button(box, "退出登录，使用游客模式", lambda: self.run(self.client.logout, self.logged_out))
        else:
            self.mode = tk.StringVar(value="login")
            self.form_mode = None
            modes = tk.Frame(box, bg=BG)
            modes.pack(fill="x", pady=(0, 12))
            for label, mode in (("登录", "login"), ("注册", "register"), ("找回密码", "reset")):
                self.buttons.append(ttk.Radiobutton(modes, text=label, value=mode, variable=self.mode, command=self.update_form))
                self.buttons[-1].pack(side="left", padx=(0, 16))
            self.email, self.password, self.code = tk.StringVar(), tk.StringVar(), tk.StringVar()
            for label, variable, masked in (("邮箱", self.email, False), ("密码", self.password, True)):
                field_label = tk.Label(box, text=label, bg=BG, fg=MUTED)
                field_label.pack(anchor="w", pady=(8, 4))
                entry = ttk.Entry(box, textvariable=variable, show="●" if masked else "")
                entry.pack(fill="x")
                self.buttons.append(entry)
                if masked:
                    self.password_label = field_label
            self.verification = tk.Frame(box, bg=BG)
            tk.Label(self.verification, text="邮箱验证码", bg=BG, fg=MUTED).pack(anchor="w", pady=(8, 4))
            code_entry = ttk.Entry(self.verification, textvariable=self.code)
            code_entry.pack(fill="x")
            self.buttons.append(code_entry)
            self.send_button = self.button(self.verification, "发送邮箱验证码", self.send_code)
            self.submit_button = self.button(box, "登录", self.submit)
            self.submit_button.configure(style="Accent.TButton")
            self.form_hint = tk.StringVar()
            tk.Label(box, textvariable=self.form_hint,
                     bg=BG, fg=MUTED, wraplength=450, justify="left").pack(anchor="w", pady=14)
            self.update_form()
        tk.Label(box, textvariable=self.message, bg=BG, fg=TEXT, wraplength=450, justify="left").pack(fill="x", pady=14)
        self.button(box, "返回本地曲库", self.close)

    def button(self, parent, title, command):
        button = ttk.Button(parent, text=title, command=command)
        button.pack(fill="x", pady=(8, 0))
        self.buttons.append(button)
        return button

    def update_form(self):
        mode = self.mode.get()
        if mode != self.form_mode:
            # 邮箱沿用，密码、验证码和提示不跨流程残留。
            self.password.set("")
            self.code.set("")
            self.message.set(self.client.warning)
            self.form_mode = mode
        self.password_label.configure(text={"login": "密码", "register": "设置密码（10～128 字符）",
                                            "reset": "新密码（10～128 字符）"}[mode])
        self.submit_button.configure(text={"login": "登录", "register": "注册", "reset": "重置密码"}[mode])
        if mode == "login":
            self.verification.pack_forget()
        else:
            self.verification.pack(fill="x", before=self.submit_button)
        self.send_button.configure(state="disabled" if mode == "login" else "normal")
        self.form_hint.set({
            "login": "登录后可同步私有云端曲库。\n游客仍可导入、试听、演奏和下载公开曲库。",
            "register": "注册后，本机游客曲谱会自动归入此账号并同步至私有云端。原曲保留在本机，退出登录后仍可使用。",
            "reset": "使用注册邮箱接收验证码并设置新密码。\n重置成功后，所有设备需使用新密码重新登录。",
        }[mode])
        # 恢复提示需要额外空间，避免“返回本地曲库”按钮被挤出窗口。
        height = (500 if mode == "login" else 650) + (80 if self.client.warning else 0)
        self.dialog.geometry(f"540x{height}")

    def run(self, action, complete=None):
        if self.running:
            return
        self.running = True
        self.message.set("正在处理…")
        for button in self.buttons:
            button.configure(state="disabled")
        def worker():
            try:
                result, error = action(), None
            except Exception as failure:
                result, error = None, str(failure)
            self.app.events.put(("account_result", (result, error, complete)))
        threading.Thread(target=worker, name="账号请求", daemon=True).start()

    def accept(self, value):
        result, error, complete = value
        self.running = False
        self.refresh_profile()
        if not self.dialog or not self.dialog.winfo_exists():
            return
        for button in self.buttons:
            button.configure(state="normal")
        if complete:
            complete(result, error)
        else:
            self.message.set(error or result.get("message", "已完成"))
            if not self.client.user:
                self.update_form()

    def refresh_profile(self):
        app = self.app
        self.caption.set(self.label())
        if app.library_dir != self.client.library_dir:
            app.stop("切换账号曲库")
            app._close_online_library_dialog()
            app.library_dir = self.client.library_dir
            app.online_downloaded_ids.clear()
            try:
                path = self.client.profile_dir / "song-settings.json"
                value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                app.song_preferences = value if isinstance(value, dict) else {}
            except (ValueError, OSError):
                app.song_preferences = {}
        app._load_library()

    def send_code(self):
        if self.mode.get() == "login":
            return
        payload = {"email": self.email.get().strip(), "purpose": self.mode.get()}
        self.run(lambda: self.client.request("POST", "/auth/request-code", payload))

    def submit(self):
        mode, email, password, code = self.mode.get(), self.email.get().strip(), self.password.get(), self.code.get().strip()
        if not 10 <= len(password) <= 128:
            self.message.set("密码需为 10～128 个字符")
            return
        if mode == "reset":
            self.run(lambda: self.client.request("POST", "/auth/reset-password", {"email": email, "password": password, "code": code}),
                     self.password_reset)
            self.password.set("")
            return
        def authenticate():
            self.client.authenticate(mode, email, password, code)
            if mode == "register":
                self.client.claim_guest()
                return self.client.sync()
            return None
        self.run(authenticate, lambda result, error: self.authenticated(mode, result, error))
        self.password.set("")

    def password_reset(self, result, error):
        if error:
            self.message.set(error)
            return
        self.mode.set("login")
        self.update_form()
        self.message.set(result["message"])

    def authenticated(self, mode, result, error):
        if not self.client.user:
            self.message.set(error)
            return
        self.render()
        self.message.set(error or (self.sync_message(result) if result else "已登录，可以同步云端曲库"))
        if error:
            self.message.set("账号已登录；继承或同步未完成：" + error + "。可点击合并或同步重试。")
        elif mode == "login" and (self.client.guest_files() or self.client.state.get("pending")):
            self.merge()

    def sync_message(self, result):
        text = f"同步完成：上传 {result['uploaded']} 首，下载 {result['downloaded']} 首。"
        if result["errors"]:
            text += "\n以下曲谱未同步，本地文件保留：\n" + "\n".join(result["errors"][:3])
        return text

    def sync(self):
        self.run(self.client.sync, lambda result, error: self.message.set(error or self.sync_message(result)))

    def merge(self):
        if self.client.claims_error:
            self.message.set(self.client.claims_error)
            return
        count = len(self.client.guest_files())
        if not count and not self.client.state.get("pending"):
            self.message.set("本机没有尚未归属账号的游客曲谱")
            return
        if not messagebox.askyesno("合并游客曲库", f"将本机 {count} 首游客曲谱归入当前账号并上传至私有云端？\n同一批曲谱不会再次自动归入其他账号。", parent=self.dialog):
            return
        def action():
            self.client.claim_guest()
            return self.client.sync()
        self.run(action, lambda result, error: self.message.set(error or self.sync_message(result)))

    def logged_out(self, result, error):
        self.render()
        self.message.set(error or result)
