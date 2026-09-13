"""隔离数据库及假邮件投递，验证账号安全和云端曲库归属。"""
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from server.accounts import Config, create_app, COOKIE, COOKIE_PATH


SCORE = {"version": 1, "title": "游客的小曲", "duration": 1000, "notes": [[0, 500, 60, 0], [500, 1000, 62, 0]]}
PASSWORD = "test-password-123"


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.mail = []
        self.app = create_app(Config(Path(self.folder.name)), lambda *args: self.mail.append(args))
        self.client = TestClient(self.app, base_url="https://aiygzn.top")
        self.store = self.app.state.store

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def register(self, email="first@example.com", client="native"):
        response = self.client.post("/auth/request-code", json={"email": email, "purpose": "register"})
        self.assertEqual(response.status_code, 200, response.text)
        code = self.mail[-1][2]
        response = self.client.post("/auth/register", json={"email": email, "password": PASSWORD, "code": code, "client": client})
        self.assertEqual(response.status_code, 201, response.text)
        return response

    def auth(self, result):
        return {"Authorization": "Bearer " + result.json()["token"]}

    def reset_code(self, email="first@example.com"):
        with self.store.connection() as db:
            db.execute("DELETE FROM limits")
        self.client.post("/auth/request-code", json={"email": email, "purpose": "reset"})
        return self.mail[-1][2]

    def test_email_verification_required_and_no_plaintext_secrets(self):
        response = self.client.post("/auth/register", json={"email": "first@example.com", "password": PASSWORD, "code": "123456"})
        self.assertEqual(response.status_code, 400)
        result = self.register()
        self.assertEqual(self.client.get("/auth/me", headers=self.auth(result)).status_code, 200)
        database = self.store.path.read_bytes()
        self.assertNotIn(PASSWORD.encode(), database)
        self.assertNotIn(result.json()["token"].encode(), database)

    def test_login_case_normalization_and_invalid_password(self):
        self.register()
        result = self.client.post("/auth/login", json={"email": "FIRST@example.com", "password": PASSWORD, "client": "native"})
        self.assertEqual(result.status_code, 200)
        wrong = self.client.post("/auth/login", json={"email": "first@example.com", "password": "wrong-password"})
        unknown = self.client.post("/auth/login", json={"email": "unknown@example.com", "password": "wrong-password"})
        self.assertEqual(wrong.json(), unknown.json())
        self.assertEqual(wrong.status_code, 401)

    def test_invalid_code_exhaustion_and_replay(self):
        self.client.post("/auth/request-code", json={"email": "first@example.com", "purpose": "register"})
        code = self.mail[-1][2]
        bad = "000000" if code != "000000" else "111111"
        data = {"email": "first@example.com", "password": PASSWORD, "code": bad}
        for _ in range(5):
            self.assertEqual(self.client.post("/auth/register", json=data).status_code, 400)
        data["code"] = code
        self.assertEqual(self.client.post("/auth/register", json=data).status_code, 400)
        result = self.register("second@example.com")
        data.update(email="second@example.com", code=self.mail[-1][2])
        self.assertEqual(self.client.post("/auth/register", json=data).status_code, 400)
        self.assertEqual(self.client.get("/auth/me", headers=self.auth(result)).status_code, 200)

    def test_code_expiry_and_purpose_separation(self):
        self.register()
        code = self.reset_code()
        with self.store.connection() as db:
            db.execute("UPDATE codes SET expires_at=0")
        data = {"email": "first@example.com", "password": PASSWORD, "code": code}
        self.assertEqual(self.client.post("/auth/reset-password", json=data).status_code, 400)

    def test_password_reset_revokes_all_sessions(self):
        first = self.register()
        second = self.client.post("/auth/login", json={"email": "first@example.com", "password": PASSWORD, "client": "native"})
        code = self.reset_code()
        response = self.client.post("/auth/reset-password", json={"email": "first@example.com", "password": "new-password-456", "code": code})
        self.assertEqual(response.status_code, 200)
        for result in (first, second):
            self.assertEqual(self.client.get("/auth/me", headers=self.auth(result)).status_code, 401)
        old = self.client.post("/auth/login", json={"email": "first@example.com", "password": PASSWORD})
        self.assertEqual(old.status_code, 401)

    def test_logout_and_session_expiry(self):
        result = self.register()
        headers = self.auth(result)
        self.assertEqual(self.client.post("/auth/logout", json={}, headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)
        result = self.client.post("/auth/login", json={"email": "first@example.com", "password": PASSWORD, "client": "native"})
        with self.store.connection() as db:
            db.execute("UPDATE sessions SET expires_at=0")
        self.assertEqual(self.client.get("/auth/me", headers=self.auth(result)).status_code, 401)

    def test_web_cookie_flags_and_csrf(self):
        result = self.register(client="web")
        self.assertNotIn("token", result.json())
        cookie = result.headers["set-cookie"]
        for flag in ("HttpOnly", "Secure", "SameSite=strict", f"Path={COOKIE_PATH}"):
            self.assertIn(flag, cookie)
        token = self.client.cookies.get(COOKIE)
        headers = {"Cookie": f"{COOKIE}={token}"}
        self.assertEqual(self.client.post("/auth/logout", json={}, headers=headers).status_code, 403)
        headers["Origin"] = "https://evil.example.com"
        self.assertEqual(self.client.post("/auth/logout", json={}, headers=headers).status_code, 403)
        headers["Origin"] = "https://aiygzn.top"
        self.assertEqual(self.client.post("/auth/logout", json={}, headers=headers).status_code, 200)

    def test_guest_requires_login_and_private_scores_cannot_be_read_by_other_account(self):
        self.assertEqual(self.client.get("/library/songs").status_code, 401)
        first, second = self.register(), self.register("second@example.com")
        response = self.client.post("/library/songs", json=SCORE, headers=self.auth(first))
        self.assertEqual(response.status_code, 200, response.text)
        sid = response.json()["id"]
        path = "/library/songs/" + sid
        self.assertEqual(self.client.get(path, headers=self.auth(second)).status_code, 404)
        self.assertEqual(self.client.get(path, headers=self.auth(first)).json(), SCORE)
        self.client.request("DELETE", path, json={}, headers=self.auth(second))
        self.assertEqual(self.client.get(path, headers=self.auth(first)).status_code, 200)

    def test_upload_retry_deduplicates_and_titles_stay_private(self):
        first, second = self.register(), self.register("second@example.com")
        for _ in range(3):
            result = self.client.post("/library/songs", json=SCORE, headers=self.auth(first))
        other = dict(SCORE, title="另一个账号的标题")
        self.client.post("/library/songs", json=other, headers=self.auth(second))
        songs = self.client.get("/library/songs", headers=self.auth(first)).json()["songs"]
        self.assertEqual(len(songs), 1)
        path = "/library/songs/" + result.json()["id"]
        self.assertEqual(self.client.get(path, headers=self.auth(second)).json()["title"], other["title"])
        self.client.request("DELETE", path, json={}, headers=self.auth(first))
        self.assertEqual(self.client.get(path, headers=self.auth(second)).status_code, 200)

    def test_guest_claim_retry_is_idempotent_and_cannot_change_owner(self):
        first, second = self.register(), self.register("second@example.com")
        data = {"guest_token": "a" * 43}
        for _ in range(2):
            self.assertEqual(self.client.post("/library/claim", json=data, headers=self.auth(first)).status_code, 200)
        self.assertEqual(self.client.post("/library/claim", json=data, headers=self.auth(second)).status_code, 409)

    def test_rate_limits_and_mail_failure(self):
        payload = {"email": "first@example.com", "purpose": "register"}
        self.assertEqual(self.client.post("/auth/request-code", json=payload).status_code, 200)
        self.assertEqual(self.client.post("/auth/request-code", json=payload).status_code, 429)
        with tempfile.TemporaryDirectory() as folder:
            def fail(*args):
                raise RuntimeError("包含凭据的上游错误")
            app = create_app(Config(Path(folder)), fail)
            with TestClient(app) as client:
                response = client.post("/auth/request-code", json=payload)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("上游错误", response.text)
                with app.state.store.connection() as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM codes").fetchone()[0], 0)

    def test_payload_validation_does_not_echo_password(self):
        result = self.client.post("/auth/login", json={"email": "bad", "password": "SECRET"})
        self.assertEqual(result.status_code, 422)
        self.assertNotIn("SECRET", result.text)
        headers = self.auth(self.register())
        for score in (dict(SCORE, duration=-1), dict(SCORE, notes=[[0, 2000, 60, 0]]), dict(SCORE, notes=[[0, 500, True, 0]])):
            self.assertEqual(self.client.post("/library/songs", json=score, headers=headers).status_code, 400)
        response = self.client.post("/library/songs", content=b"x" * (2 * 1024 * 1024 + 1), headers=dict(headers, **{"Content-Type": "application/json"}))
        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
