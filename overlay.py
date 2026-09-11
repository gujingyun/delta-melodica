"""半透明游戏悬浮窗：观看时穿透鼠标，F7 打开操作面板。"""
from __future__ import annotations

import json
import tkinter as tk

from win_input import (activate_window, foreground, matching_windows, overlay_style,
                       root_window, target_matches, window_info)

BG = "#122125"
CARD = "#263a3e"
TEXT = "#eff7ee"
MUTED = "#9bb4b5"
ACCENT = "#b7f17c"


class Overlay:
    WIDTH = 440
    HUD_HEIGHT = 186
    PANEL_HEIGHT = 452

    def __init__(self, app):
        self.app = app
        self.config_path = app.data_dir / "overlay.json"
        self.enabled, self.alpha, self.x, self.y = True, 0.82, 36, 120
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            self.enabled = bool(data.get("enabled", True))
            self.alpha = min(1.0, max(0.45, float(data.get("alpha", 0.82))))
            self.x, self.y = int(data.get("x", 36)), int(data.get("y", 120))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        self.x = min(max(0, self.x), max(0, app.root.winfo_screenwidth()-self.WIDTH))
        self.y = min(max(0, self.y), max(0, app.root.winfo_screenheight()-self.PANEL_HEIGHT))
        self.editing, self.visible, self.closed = False, False, False
        self.target = None
        self.regions = []
        self.page = 0
        self.drag_origin = None
        self.window = tk.Toplevel(app.root)
        self.window.withdraw()
        self.window.title("三角洲口风琴 · 游戏悬浮窗")
        self.window.protocol("WM_DELETE_WINDOW", self.disable)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", self.alpha)
        self.window.configure(bg=BG)
        self.window.geometry(f"{self.WIDTH}x{self.HUD_HEIGHT}+{self.x}+{self.y}")
        self.canvas = tk.Canvas(self.window, width=self.WIDTH, height=self.HUD_HEIGHT, bg=BG, bd=0, highlightthickness=1, highlightbackground="#486158")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.window.update_idletasks()
        self.hwnd = root_window(self.window.winfo_id())
        overlay_style(self.hwnd)
        self.timer = self.window.after(160, self.tick)

    def save(self):
        try:
            temporary = self.config_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"enabled": self.enabled, "alpha": self.alpha, "x": self.x, "y": self.y}, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.config_path)
        except OSError as error:
            self.app.log.warning("悬浮窗设置保存失败：%s", error)

    def _show(self):
        if not self.visible:
            # 先设置不激活样式，再显示，防止观看状态夺走游戏焦点。
            overlay_style(self.hwnd, self.editing)
            self.window.deiconify()
            self.hwnd = root_window(self.window.winfo_id())
            overlay_style(self.hwnd, self.editing)
            self.visible = True
            self.app.overlay_visibility_changed(True)

    def _hide(self):
        if self.visible:
            self.window.withdraw()
            self.visible = False
            self.app.overlay_visibility_changed(False)

    def game_window(self):
        current = foreground()
        if target_matches(current, self.app.settings["target"]):
            self.target = current
        if self.target:
            refreshed = window_info(self.target[0])
            if refreshed[:2] == self.target[:2] and target_matches(refreshed, self.app.settings["target"]):
                return refreshed
        games = matching_windows(self.app.settings["target"])
        if len(games) == 1:
            self.target = games[0]
            return self.target
        raise RuntimeError("未找到唯一的游戏窗口，请先进入游戏后按 F7。")

    def begin_edit(self):
        if self.closed:
            return
        current = foreground()
        if target_matches(current, self.app.settings["target"]):
            self.target = current
        if self.app.busy:
            self.app.stop("打开悬浮窗操作面板")
        self.enabled, self.editing = True, True
        self.window.geometry(f"{self.WIDTH}x{self.PANEL_HEIGHT}+{self.x}+{self.y}")
        self._show()
        overlay_style(self.hwnd, True)
        self.app.log.info("打开悬浮窗操作面板")
        try:
            activate_window(window_info(self.hwnd))
        except RuntimeError as error:
            self.app.detail.set(str(error))
        self.draw()
        self.save()

    def return_to_game(self, start=False):
        if start and self.app.busy:
            return
        try:
            target = self.game_window()
            # 恢复穿透后才切回游戏，随后发送的鼠标变音不会点击到面板。
            self.editing = False
            self.window.geometry(f"{self.WIDTH}x{self.HUD_HEIGHT}+{self.x}+{self.y}")
            overlay_style(self.hwnd, False)
            activate_window(target)
            self.target = target
            self.app.log.info("悬浮窗交还游戏焦点：PID=%s；播放=%s", target[1], start)
            if start:
                self.window.after(120, lambda: self.app.play(False))
        except RuntimeError as error:
            self.editing = True
            self.window.geometry(f"{self.WIDTH}x{self.PANEL_HEIGHT}+{self.x}+{self.y}")
            overlay_style(self.hwnd, True)
            self.app.status.set("请先进入游戏")
            self.app.detail.set(str(error))
            self.app.log.warning("悬浮窗返回失败：%s", error)
        self.draw()

    def toggle_edit(self):
        if self.editing:
            self.return_to_game()
        else:
            self.begin_edit()

    def toggle_visibility(self):
        if self.closed:
            return
        if self.visible:
            self.disable()
        elif target_matches(foreground(), self.app.settings["target"]):
            # 游戏内只切换观看窗，保持焦点和正在进行的演奏。
            self.enabled, self.editing = True, False
            self.window.geometry(f"{self.WIDTH}x{self.HUD_HEIGHT}+{self.x}+{self.y}")
            self._show()
            self.draw()
            self.save()
        else:
            self.begin_edit()

    def toggle_play(self):
        if self.app.busy:
            self.app.stop("F8")
        elif self.editing:
            self.return_to_game(start=True)
        else:
            self.app.play(False)

    def tick(self):
        if self.closed:
            return
        current = foreground()
        in_game = target_matches(current, self.app.settings["target"])
        if in_game:
            self.target = current
        if self.editing and current[0] != self.hwnd:
            # 用户主动切回游戏或其他程序时，立即恢复鼠标穿透。
            self.editing = False
            self.window.geometry(f"{self.WIDTH}x{self.HUD_HEIGHT}+{self.x}+{self.y}")
            overlay_style(self.hwnd, False)
        if self.enabled and (in_game or self.editing):
            self._show()
            self.draw()
        else:
            self._hide()
        self.timer = self.window.after(160, self.tick)

    def _text(self, x, y, text, color=TEXT, size=10, bold=False, anchor="w"):
        return self.canvas.create_text(x, y, text=text, fill=color, anchor=anchor,
                                      font=("Microsoft YaHei UI", size, "bold" if bold else "normal"))

    def _button(self, x, y, width, height, text, action, enabled=True, primary=False):
        self.canvas.create_rectangle(x, y, x+width, y+height, fill=ACCENT if primary and enabled else CARD, outline="")
        self._text(x+width/2, y+height/2, text, BG if primary and enabled else TEXT if enabled else MUTED, 10, primary, "center")
        if enabled:
            self.regions.append((x, y, x+width, y+height, action))

    def draw(self):
        c = self.canvas
        c.delete("all")
        self.regions = []
        self._text(16, 21, "三角洲口风琴", ACCENT, 11, True)
        self._text(422, 21, "拖动标题移动" if self.editing else "F7 打开操作", MUTED, 9, anchor="e")
        title = self.app.title.get()
        self._text(16, 54, title[:19] + ("…" if len(title) > 19 else ""), size=15, bold=True)
        self._text(16, 84, self.app.status.get()[:27], ACCENT, 10)
        self._text(422, 84, self.app.elapsed.get(), MUTED, 9, anchor="e")
        c.create_rectangle(16, 103, 424, 107, fill=CARD, outline="")
        c.create_rectangle(16, 103, 16+408*float(self.app.progress["value"])/100, 107, fill=ACCENT, outline="")
        for index, key in enumerate(self.app.settings["keys"]):
            x = 16+index*51
            active = self.app.current_note and self.app.current_note.fingering.key == key
            c.create_rectangle(x, 119, x+45, 147, fill=ACCENT if active else CARD, outline="")
            self._text(x+22, 133, key.upper(), BG if active else TEXT, 11, True, "center")
        if not self.editing:
            text = self.app.current_note.fingering.label if self.app.current_note else "F6 隐藏　F7 操作　F8 播放 / 停止　F9 停止"
            self._text(16, 168, text, MUTED, 9)
            return
        ready = not self.app.busy
        self._button(16, 159, 194, 36, "▶ 播放并返回游戏", lambda: self.return_to_game(True), ready, True)
        self._button(220, 159, 94, 36, "■ 停止", lambda: self.app.stop("悬浮窗"))
        self._button(324, 159, 100, 36, "返回 F7", self.return_to_game)
        self._text(16, 217, "选择曲目", MUTED, 9)
        page_count = max(1, (len(self.app.entries)+3)//4)
        self.page = min(self.page, page_count-1)
        self._text(295, 217, f"{self.page+1} / {page_count}", MUTED, 9)
        self._button(336, 204, 38, 25, "‹", lambda: self.change_page(-1), self.page > 0)
        self._button(384, 204, 40, 25, "›", lambda: self.change_page(1), self.page < page_count-1)
        selected = self.app.library.curselection()
        for row, index in enumerate(range(self.page*4, min(self.page*4+4, len(self.app.entries)))):
            name = self.app.entries[index][0]
            label = ("● " if selected and selected[0] == index else "   ") + name[:26]
            self._button(16, 235+row*30, 408, 27, label, lambda i=index: self.select(i), ready)
        self._button(16, 363, 100, 29, "速度 −", lambda: self.change_speed(-1), ready)
        self._text(169, 378, self.app.speed.get()+" 倍", TEXT, 10, anchor="center")
        self._button(220, 363, 100, 29, "速度 +", lambda: self.change_speed(1), ready)
        self._button(330, 363, 94, 29, f"不透明 {round(self.alpha*100)}%", self.change_alpha)
        self._button(16, 402, 128, 31, "打开主窗口", self.open_main)
        self._button(156, 402, 128, 31, "隐藏悬浮窗", self.disable)
        self._text(422, 418, "F6 显示 / 隐藏", MUTED, 9, anchor="e")

    def select(self, index):
        if self.app.busy:
            return
        self.app.library.selection_clear(0, "end")
        self.app.library.selection_set(index)
        self.app.library.see(index)
        self.app.select_song()
        self.draw()

    def change_page(self, step):
        self.page += step
        self.draw()

    def change_speed(self, step):
        speeds = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2]
        current = min(range(len(speeds)), key=lambda i: abs(speeds[i]-float(self.app.speed.get())))
        self.app.speed.set(f"{speeds[min(max(current+step, 0), len(speeds)-1)]:.2f}")
        self.app.rebuild_plan()
        self.draw()

    def change_alpha(self):
        self.alpha = 0.65 if self.alpha > 0.94 else 0.82 if self.alpha < 0.8 else 0.96
        self.window.attributes("-alpha", self.alpha)
        overlay_style(self.hwnd, self.editing)
        self.save()
        self.draw()

    def open_main(self):
        self.app.show_main()

    def disable(self):
        return_focus = self.editing and foreground()[0] == self.hwnd
        self.editing, self.enabled = False, False
        overlay_style(self.hwnd, False)
        self._hide()
        self.save()
        if return_focus:
            try:
                activate_window(self.game_window())
            except RuntimeError:
                # 桌面中也允许独立开关面板，不要求游戏必须存在。
                pass

    def _press(self, event):
        if self.editing and event.y < 38:
            self.drag_origin = (event.x_root, event.y_root, self.window.winfo_x(), self.window.winfo_y())

    def _drag(self, event):
        if self.drag_origin:
            px, py, x, y = self.drag_origin
            self.x = max(0, min(self.app.root.winfo_screenwidth()-self.WIDTH, x+event.x_root-px))
            self.y = max(0, min(self.app.root.winfo_screenheight()-self.PANEL_HEIGHT, y+event.y_root-py))
            self.window.geometry(f"+{self.x}+{self.y}")

    def _release(self, event):
        if self.drag_origin:
            self.drag_origin = None
            self.save()
            return
        if self.editing:
            for x1, y1, x2, y2, action in self.regions:
                if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                    action()
                    break

    def close(self):
        self.closed = True
        self.window.after_cancel(self.timer)
        self.save()
        self.window.destroy()
