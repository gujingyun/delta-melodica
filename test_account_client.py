"""验证桌面游客继承、跨设备同步和界面后台请求，全部使用隔离测试数据。"""
from contextlib import contextmanager
import io
import gc
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
import urllib.error
from unittest.mock import patch

from fastapi.testclient import TestClient

from account_client import AccountClient, AccountError, atomic_json, protect_bytes
from cloud_score import from_song, score_id, to_song
from music import parse_jianpu
from server.accounts import Config, create_app


class LocalAPI:
    def __init__(self, api):
        self.api = api

    def open(self, request, timeout=20):
        response = self.api.request(request.method, request.full_url.split("example.com", 1)[1],
                                    content=request.data, headers=dict(request.header_items()))
        if response.status_code >= 400:
            raise urllib.error.HTTPError(request.full_url, response.status_code, "测试响应", {}, io.BytesIO(response.content))
        return io.BytesIO(response.content)


class DesktopAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mail = []
        self.api = TestClient(create_app(Config(self.root / "server"), lambda *args: self.mail.append(args)))
        self.client = self.make_client("desktop")
        atomic_json(self.client.library_dir / "legacy__游客曲谱.json", {"title": "游客曲谱", "bpm": 100, "score": "1 2 3:2"})

    def tearDown(self):
        self.api.close()
        self.temp.cleanup()

    def make_client(self, folder):
        client = AccountClient(self.root / folder, "https://example.com")
        client.opener = LocalAPI(self.api)
        return client

    def register(self, email="first@example.com", client=None):
        client = client or self.client
        client.request("POST", "/auth/request-code", {"email": email, "purpose": "register"})
        return client.authenticate("register", email, "test-password-123", self.mail[-1][2])

    def test_dpapi_round_trip(self):
        secret = b"test-only-session-token"
        encrypted = protect_bytes(secret)
        self.assertNotIn(secret, encrypted)
        self.assertEqual(protect_bytes(encrypted, decrypt=True), secret)

    def test_guest_sync_prompts_login_without_changing_files(self):
        with self.assertRaisesRegex(AccountError, "需要登录"):
            self.client.sync()
        self.assertEqual(len(self.client.guest_files()), 1)

    def test_register_claims_old_library_and_restart_keeps_account(self):
        response = self.register()
        self.assertEqual(self.client.claim_guest(), 1)
        self.assertEqual(self.client.claim_guest(), 0)
        result = self.client.sync()
        self.assertEqual(result["uploaded"], 1)
        self.assertTrue((self.root / "desktop/songs/legacy__游客曲谱.json").exists())
        self.assertEqual(self.client.guest_files(), [])
        restarted = self.make_client("desktop")
        self.assertEqual(restarted.user, response["user"])
        self.assertEqual(restarted.library_dir, self.client.library_dir)
        self.assertEqual(restarted.sync()["uploaded"], 0)

    def test_second_account_does_not_inherit_claimed_guest_songs(self):
        self.register()
        self.client.claim_guest()
        first_dir = self.client.library_dir
        self.client.logout()
        self.assertTrue((self.client.library_dir / "legacy__游客曲谱.json").is_file())
        self.assertEqual(self.client.guest_files(), [])
        self.register("second@example.com")
        self.assertEqual(self.client.claim_guest(), 0)
        self.assertNotEqual(self.client.library_dir, first_dir)
        self.assertEqual(list(self.client.library_dir.iterdir()), [])

    def test_claim_response_loss_retries_same_batch(self):
        self.register()
        original = self.client.request
        def lost(method, path, payload=None):
            response = original(method, path, payload)
            if path == "/library/claim":
                raise AccountError("测试断网")
            return response
        with patch.object(self.client, "request", side_effect=lost), self.assertRaises(AccountError):
            self.client.claim_guest()
        token = self.client.state["pending"]["guest_token"]
        restarted = self.make_client("desktop")
        self.assertEqual(restarted.state["pending"]["guest_token"], token)
        self.assertEqual(restarted.claim_guest(), 1)
        self.assertEqual(len(list(restarted.library_dir.glob("*.json"))), 1)

    def test_copy_failure_can_resume_and_later_user_deletion_stays_deleted(self):
        self.register()
        with patch("account_client.shutil.copy2", side_effect=OSError("测试磁盘失败")), self.assertRaises(OSError):
            self.client.claim_guest()
        restarted = self.make_client("desktop")
        restarted.claim_guest()
        target = restarted.library_dir / "legacy__游客曲谱.json"
        self.assertTrue(target.is_file())
        target.unlink()
        self.assertFalse((self.make_client("desktop").library_dir / target.name).exists())

    def test_pending_claim_cannot_move_to_other_account(self):
        self.register()
        with patch.object(self.client, "request", side_effect=AccountError("测试断网")), self.assertRaises(AccountError):
            self.client.claim_guest()
        self.client.logout()
        self.register("second@example.com")
        with self.assertRaisesRegex(AccountError, "其他账号"):
            self.client.claim_guest()

    def test_sync_downloads_to_other_device_and_preserves_notes(self):
        self.register()
        self.client.claim_guest()
        self.client.sync()
        second = self.make_client("second-device")
        second.authenticate("login", "first@example.com", "test-password-123")
        self.assertEqual(second.sync()["downloaded"], 1)
        score = json.loads(next(second.library_dir.glob("*.json")).read_text(encoding="utf-8"))
        song = to_song(score)
        self.assertEqual(len(song.notes), 3)
        self.assertEqual(song.duration, 2.4)
        self.assertEqual(second.sync()["downloaded"], 0)

    def test_sync_partial_upload_retries_without_duplicates(self):
        self.register()
        self.client.claim_guest()
        atomic_json(self.client.library_dir / "second.json", {"title": "另一首", "bpm": 100, "score": "3 4 5"})
        original = self.client.request
        count = 0
        def failing(method, path, payload=None):
            nonlocal count
            if method == "POST" and path == "/library/songs":
                count += 1
                if count == 2:
                    raise AccountError("测试断网")
            return original(method, path, payload)
        with patch.object(self.client, "request", side_effect=failing), self.assertRaises(AccountError):
            self.client.sync()
        self.assertEqual(self.client.sync()["uploaded"], 1)
        self.assertEqual(len(self.client.request("GET", "/library/songs")["songs"]), 2)

    def test_logout_offline_clears_local_token(self):
        self.register()
        with patch.object(self.client, "request", side_effect=AccountError("测试断网")):
            message = self.client.logout()
        self.assertIn("本机已退出", message)
        self.assertIsNone(self.make_client("desktop").user)

    def test_cloud_score_round_trip_keeps_tracks_and_repeated_notes(self):
        fixture = {"version": 1, "title": "跨端样例", "duration": 1200, "notes": [[0, 500, 60, 0], [500, 1000, 62, 3]]}
        self.assertEqual(score_id(fixture), "3a2f55eda21cb4933d77db4999aa9b2f2d3b91c0b368e3924393e86c77ffbb53")
        song = parse_jianpu("1 1 0:2 +1:1/2", 120, "跨端曲谱")
        cloud = from_song(song)
        self.assertEqual(score_id(cloud), score_id(from_song(to_song(cloud))))
        self.assertEqual(len(cloud["notes"]), 3)

    @contextmanager
    def account_panel(self):
        from app import App
        root = tk.Tk()
        app = App(root, self.root / "form-ui", smoke=True)
        try:
            app.account.opener = LocalAPI(self.api)
            app.account.api_url = "https://example.com"
            panel = app.account_ui
            panel.show()
            root.update()
            yield root, app, panel
        finally:
            app.close()
            del panel, app, root
            # 及时在主线程回收 Tk 对象，避免后台请求触发析构。
            gc.collect()

    def test_login_hides_verification_controls_and_cannot_send_code(self):
        with self.account_panel() as (root, app, panel):
            entries = [widget for widget in panel.buttons if isinstance(widget, ttk.Entry) and widget.winfo_ismapped()]
            self.assertEqual(len(entries), 2)
            self.assertFalse(panel.send_button.winfo_ismapped())
            self.assertEqual(panel.password_label.cget("text"), "密码")
            panel.send_code()
            self.assertFalse(panel.running)
            self.assertEqual(self.mail, [])

    def test_switching_forms_shows_only_relevant_fields_and_clears_secrets(self):
        with self.account_panel() as (root, app, panel):
            panel.email.set("form@example.com")
            for mode, password_label, submit in (("register", "设置密码（10～128 字符）", "注册"),
                                                  ("reset", "新密码（10～128 字符）", "重置密码"),
                                                  ("login", "密码", "登录"),
                                                  ("register", "设置密码（10～128 字符）", "注册")):
                with self.subTest(mode=mode):
                    panel.password.set("previous-password")
                    panel.code.set("123456")
                    panel.message.set("上一步提示")
                    panel.mode.set(mode)
                    panel.update_form()
                    root.update()
                    entries = [widget for widget in panel.buttons if isinstance(widget, ttk.Entry) and widget.winfo_ismapped()]
                    self.assertEqual(len(entries), 2 if mode == "login" else 3)
                    self.assertEqual(bool(panel.send_button.winfo_ismapped()), mode != "login")
                    self.assertEqual(panel.password_label.cget("text"), password_label)
                    self.assertEqual(panel.submit_button.cget("text"), submit)
                    self.assertEqual(panel.email.get(), "form@example.com")
                    self.assertEqual((panel.password.get(), panel.code.get()), ("", ""))
                    self.assertNotEqual(panel.message.get(), "上一步提示")
                    self.assertTrue(panel.submit_button.winfo_ismapped())
                    self.assertLessEqual(panel.buttons[-1].winfo_rooty() + panel.buttons[-1].winfo_height(),
                                         panel.dialog.winfo_rooty() + panel.dialog.winfo_height())

    def test_login_failure_keeps_verification_hidden_then_password_login_succeeds(self):
        self.register("login@example.com")
        with self.account_panel() as (root, app, panel):
            panel.email.set("login@example.com")
            panel.password.set("wrong-password")
            panel.submit()
            self.wait_ui(root, panel)
            self.assertIsNone(app.account.user)
            self.assertTrue(panel.message.get())
            self.assertFalse(panel.send_button.winfo_ismapped())
            self.assertFalse(panel.submit_button.instate(["disabled"]))
            panel.password.set("test-password-123")
            panel.submit()
            self.wait_ui(root, panel)
            self.assertEqual(app.account.user["email"], "login@example.com")
            self.assertEqual(len(self.mail), 1)

    def test_reset_failure_stays_in_form_and_success_returns_to_password_login(self):
        self.register("reset@example.com")
        with self.account_panel() as (root, app, panel):
            panel.mode.set("reset")
            panel.update_form()
            panel.email.set("reset@example.com")
            # 跨过注册邮件的冷却时间，仍走真实限流和重置接口。
            with patch("server.accounts.time.time", return_value=time.time() + 61):
                panel.send_code()
                self.wait_ui(root, panel)
            self.assertEqual(self.mail[-1][1], "reset")
            code = self.mail[-1][2]
            panel.code.set("000000" if code != "000000" else "111111")
            panel.password.set("new-password-123")
            panel.submit()
            self.wait_ui(root, panel)
            self.assertEqual(panel.mode.get(), "reset")
            self.assertTrue(panel.send_button.winfo_ismapped())
            self.assertIn("验证码", panel.message.get())
            panel.code.set(code)
            panel.password.set("new-password-123")
            panel.submit()
            self.wait_ui(root, panel)
            self.assertEqual(panel.mode.get(), "login")
            self.assertEqual(panel.email.get(), "reset@example.com")
            self.assertEqual((panel.password.get(), panel.code.get()), ("", ""))
            self.assertFalse(panel.send_button.winfo_ismapped())
            self.assertIn("密码已重置", panel.message.get())
            panel.password.set("new-password-123")
            panel.submit()
            self.wait_ui(root, panel)
            self.assertEqual(app.account.user["email"], "reset@example.com")

    def test_account_dialog_registers_and_logout_restores_guest_library(self):
        from app import App
        root = tk.Tk()
        app = App(root, self.root / "ui", smoke=True)
        try:
            app.account.opener = LocalAPI(self.api)
            app.account.api_url = "https://example.com"
            guest_dir = app.library_dir
            guest_path = guest_dir / "test.json"
            atomic_json(guest_path, {"title": "界面测试", "bpm": 100, "score": "1 2 3"})
            original = guest_path.read_bytes()
            panel = app.account_ui
            panel.show(); root.update()
            panel.mode.set("register"); panel.update_form()
            panel.email.set("ui@example.com"); panel.password.set("test-password-123")
            panel.send_code()
            self.wait_ui(root, panel)
            panel.code.set(self.mail[-1][2]); panel.submit()
            self.wait_ui(root, panel)
            self.assertIsNotNone(app.account.user)
            self.assertEqual(app.library_dir, app.account.library_dir)
            self.assertIn("同步完成", panel.message.get())
            self.assertEqual(len(app.account.request("GET", "/library/songs")["songs"]), 1)
            private_path = app.library_dir / "private.json"
            atomic_json(private_path, {"title": "账号专属曲谱", "bpm": 100, "score": "3 4 5"})
            panel.refresh_profile()
            self.assertIn(("file", private_path), [source for _, source in app.entries])
            panel.run(app.account.logout, panel.logged_out)
            self.wait_ui(root, panel)
            self.assertIsNone(app.account.user)
            self.assertEqual(app.library_dir, guest_dir)
            self.assertEqual([source for _, source in app.entries if source[0] == "file"], [("file", guest_path)])
            app._load_library(guest_path)
            self.assertEqual(app.current_source, ("file", guest_path))
            self.assertEqual(len(app.plan.notes), 3)
            self.assertEqual(guest_path.read_bytes(), original)
            self.assertTrue(private_path.is_file())
            self.assertEqual(app.account.guest_files(), [])
        finally:
            app.close()
            del panel, app, root
            # Tk 对象必须在主线程回收，避免后续 HTTP 测试线程触发循环垃圾回收。
            gc.collect()

    def wait_ui(self, root, panel):
        for _ in range(500):
            root.update()
            if not panel.running:
                return
            time.sleep(.01)
        self.fail("界面等待账号请求超时")


if __name__ == "__main__":
    unittest.main()
