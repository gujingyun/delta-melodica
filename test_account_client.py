"""验证桌面游客继承、跨设备同步和界面后台请求，全部使用隔离测试数据。"""
from contextlib import contextmanager
import io
import gc
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
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
        self.assertFalse(self.client.visible(self.client.library_dir / "legacy__游客曲谱.json"))
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

    def test_account_dialog_renders_and_registers_in_background(self):
        from app import App
        root = tk.Tk()
        app = App(root, self.root / "ui", smoke=True)
        try:
            app.account.opener = LocalAPI(self.api)
            app.account.api_url = "https://example.com"
            atomic_json(app.library_dir / "test.json", {"title": "界面测试", "bpm": 100, "score": "1 2 3"})
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
