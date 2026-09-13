"""独立账号 API，SQLite 保存身份、会话和私有云端曲库。"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from email.message import EmailMessage
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import smtplib
import sqlite3
import ssl
import time
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from email_validator import validate_email, EmailNotValidError
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from cloud_score import MAX_SCORE_BYTES, normalize_score, score_id


SESSION_SECONDS = 30 * 86400
COOKIE = "melodica_session"
COOKIE_PATH = "/melodica/account-api/"
PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(24))


@dataclass
class Config:
    data_dir: Path
    origin: str = "https://aiygzn.top"
    secure_cookie: bool = True
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_tls: str = "ssl"

    @classmethod
    def from_env(cls):
        return cls(Path(os.environ.get("MELODICA_ACCOUNT_DIR", "work/account-server")),
                   os.environ.get("MELODICA_ORIGIN", "https://aiygzn.top").rstrip("/"),
                   os.environ.get("MELODICA_DEV_HTTP", "0") != "1",
                   os.environ.get("SMTP_HOST", ""), int(os.environ.get("SMTP_PORT", "465")),
                   os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", ""),
                   os.environ.get("SMTP_FROM", ""), os.environ.get("SMTP_TLS", "ssl"))


def send_code(config, email, purpose, code):
    """只使用加密 SMTP，凭据和验证码不写日志。"""
    if not config.smtp_host or not config.smtp_from or config.smtp_tls not in ("ssl", "starttls"):
        raise RuntimeError("发信服务尚未配置")
    message = EmailMessage()
    label = "注册验证" if purpose == "register" else "重置密码"
    message["Subject"] = f"三角洲口风琴 · {label}"
    message["From"], message["To"] = config.smtp_from, email
    message.set_content(f"你正在进行{label}。\n\n验证码：{code}\n\n10 分钟内有效，请勿向他人提供。"
                        "如果不是你本人操作，请忽略此邮件。\n三角洲口风琴")
    context = ssl.create_default_context()
    if config.smtp_tls == "ssl":
        connection = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=15, context=context)
    else:
        connection = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15)
    with connection:
        if config.smtp_tls == "starttls":
            connection.starttls(context=context)
        if config.smtp_user:
            connection.login(config.smtp_user, config.smtp_password)
        connection.send_message(message)


class Store:
    def __init__(self, config):
        config.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = config.data_dir / "accounts.sqlite3"
        secret_file = config.data_dir / "otp-secret"
        try:
            handle = os.open(secret_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(handle, "wb") as output:
                output.write(secrets.token_bytes(32))
        self.secret = secret_file.read_bytes()
        if len(self.secret) != 32:
            raise RuntimeError("验证码密钥文件损坏，请从备份恢复")
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL, created_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    expires_at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS codes (
                    email TEXT NOT NULL, purpose TEXT NOT NULL, digest TEXT NOT NULL,
                    expires_at INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    sent_at INTEGER NOT NULL, PRIMARY KEY(email, purpose));
                CREATE TABLE IF NOT EXISTS limits (
                    key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS guest_claims (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id));
                CREATE TABLE IF NOT EXISTS songs (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS user_songs (
                    user_id TEXT NOT NULL REFERENCES users(id), song_id TEXT NOT NULL REFERENCES songs(id),
                    title TEXT NOT NULL, created_at INTEGER NOT NULL, PRIMARY KEY(user_id, song_id));
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def digest_code(self, email, purpose, code):
        return hmac.new(self.secret, f"{email}\0{purpose}\0{code}".encode(), hashlib.sha256).hexdigest()

    def limit(self, key, count, seconds):
        now = int(time.time())
        key = hashlib.sha256(key.encode()).hexdigest()
        with self.connection() as db:
            db.execute("DELETE FROM limits WHERE expires_at <= ?", (now,))
            db.execute("INSERT INTO limits VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1",
                       (key, now + seconds))
            exceeded = db.execute("SELECT count FROM limits WHERE key=?", (key,)).fetchone()[0] > count
        if exceeded:
            raise HTTPException(429, "操作过于频繁，请稍后再试")

    def consume_code(self, db, email, purpose, code):
        row = db.execute("SELECT * FROM codes WHERE email=? AND purpose=?", (email, purpose)).fetchone()
        if not row or row["expires_at"] <= time.time() or row["attempts"] >= 5:
            return False
        if not hmac.compare_digest(row["digest"], self.digest_code(email, purpose, code)):
            db.execute("UPDATE codes SET attempts=attempts+1 WHERE email=? AND purpose=?", (email, purpose))
            return False
        db.execute("DELETE FROM codes WHERE email=? AND purpose=?", (email, purpose))
        return True


def normalized_email(value):
    try:
        return validate_email(value, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise HTTPException(400, "请输入有效邮箱地址") from None


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CodeRequest(Input):
    email: str = Field(max_length=254)
    purpose: Literal["register", "reset"]


class Login(Input):
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128)
    client: Literal["native", "web"] = "web"


class Register(Login):
    code: str = Field(pattern=r"^\d{6}$")


class Reset(Input):
    email: str = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128)
    code: str = Field(pattern=r"^\d{6}$")


class Claim(Input):
    guest_token: str = Field(pattern=r"^[A-Za-z0-9_-]{32,128}$")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_app(config=None, mailer=None):
    config = config or Config.from_env()
    store = Store(config)
    mailer = mailer or (lambda email, purpose, code: send_code(config, email, purpose, code))
    app = FastAPI(title="三角洲口风琴账号 API", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # 默认校验响应包含输入内容，账号接口不能回显密码或验证码。
        return JSONResponse({"detail": "输入格式不正确；密码需为 10～128 个字符，验证码为 6 位数字"}, status_code=422)

    @app.middleware("http")
    async def protect(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if (origin and origin != config.origin) or (request.cookies.get(COOKIE) and origin != config.origin):
                return JSONResponse({"detail": "请求来源无效"}, status_code=403)
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"detail": "请使用 JSON 请求"}, status_code=415)
            body = bytearray()
            async for part in request.stream():
                body.extend(part)
                if len(body) > MAX_SCORE_BYTES:
                    return JSONResponse({"detail": "请求超过 2 MB"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def limit_ip(request, category, count=30, seconds=900):
        # Uvicorn 只信任本机反向代理，不读取客户端自行提供的转发头。
        store.limit(f"{category}:{request.client.host if request.client else 'unknown'}", count, seconds)

    def identity(request):
        authorization = request.headers.get("authorization", "")
        token = authorization[7:] if authorization.startswith("Bearer ") else request.cookies.get(COOKIE, "")
        with store.connection() as db:
            row = db.execute("SELECT users.id,users.email FROM sessions JOIN users ON users.id=sessions.user_id "
                             "WHERE token_hash=? AND expires_at>?", (token_hash(token), int(time.time()))).fetchone()
        if not row:
            raise HTTPException(401, "请先登录，或重新登录后同步")
        return dict(row), token

    def new_session(user, client, response, expected_hash=None):
        token = secrets.token_urlsafe(32)
        expires = int(time.time()) + SESSION_SECONDS
        with store.connection() as db:
            if expected_hash is not None:
                current = db.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
                if not current or current[0] != expected_hash:
                    raise HTTPException(401, "密码已更新，请重新登录")
            db.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (token_hash(token), user["id"], expires))
        result = {"user": user, "expires_at": expires}
        if client == "native":
            result["token"] = token
        else:
            response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                                secure=config.secure_cookie, samesite="strict", path=COOKIE_PATH)
        return result

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/auth/request-code")
    def request_code(body: CodeRequest, request: Request):
        email = normalized_email(body.email)
        limit_ip(request, "mail", 10, 3600)
        store.limit(f"mail:{email}", 5, 3600)
        store.limit(f"mail-cooldown:{email}", 1, 60)
        code, now = f"{secrets.randbelow(1000000):06d}", int(time.time())
        digest = store.digest_code(email, body.purpose, code)
        with store.connection() as db:
            db.execute("DELETE FROM codes WHERE expires_at<=?", (now,))
            exists = db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone() is not None
            eligible = exists if body.purpose == "reset" else not exists
            if eligible:
                db.execute("INSERT OR REPLACE INTO codes VALUES (?,?,?,?,0,?)",
                           (email, body.purpose, digest, now + 600, now))
        if eligible:
            try:
                mailer(email, body.purpose, code)
            except Exception:
                with store.connection() as db:
                    db.execute("DELETE FROM codes WHERE email=? AND purpose=? AND digest=?", (email, body.purpose, digest))
                raise HTTPException(503, "邮件暂时无法发送，请稍后重试或联系站点维护者") from None
        return {"message": "若邮箱可用于此操作，验证码将发送至邮箱；10 分钟内有效，请检查垃圾邮件"}

    @app.post("/auth/register", status_code=201)
    def register(body: Register, request: Request, response: Response):
        email = normalized_email(body.email)
        limit_ip(request, "credentials")
        password_hash = PASSWORDS.hash(body.password)
        user = {"id": secrets.token_hex(16), "email": email}
        with store.connection() as db:
            valid = store.consume_code(db, email, "register", body.code)
            if valid:
                if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
                    valid = False
                else:
                    db.execute("INSERT INTO users VALUES (?,?,?,?)", (user["id"], email, password_hash, int(time.time())))
        if not valid:
            raise HTTPException(400, "验证码无效或已过期；已注册邮箱请直接登录")
        return new_session(user, body.client, response)

    @app.post("/auth/login")
    def login(body: Login, request: Request, response: Response):
        email = normalized_email(body.email)
        limit_ip(request, "credentials")
        store.limit(f"login:{email}", 10, 900)
        with store.connection() as db:
            row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        try:
            valid = PASSWORDS.verify(row["password_hash"] if row else DUMMY_HASH, body.password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not row or not valid:
            raise HTTPException(401, "邮箱或密码不正确")
        return new_session({"id": row["id"], "email": email}, body.client, response, row["password_hash"])

    @app.post("/auth/reset-password")
    def reset_password(body: Reset, request: Request):
        email = normalized_email(body.email)
        limit_ip(request, "credentials")
        password_hash = PASSWORDS.hash(body.password)
        with store.connection() as db:
            valid = store.consume_code(db, email, "reset", body.code)
            if valid:
                db.execute("UPDATE users SET password_hash=? WHERE email=?", (password_hash, email))
                db.execute("DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE email=?)", (email,))
        if not valid:
            raise HTTPException(400, "验证码无效或已过期，请重新获取")
        return {"message": "密码已重置，所有设备需要重新登录"}

    @app.get("/auth/me")
    def me(request: Request):
        return {"user": identity(request)[0]}

    @app.post("/auth/logout")
    def logout(request: Request, response: Response):
        try:
            _, token = identity(request)
        except HTTPException:
            token = ""
        with store.connection() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
        response.delete_cookie(COOKIE, path=COOKIE_PATH, secure=config.secure_cookie, httponly=True, samesite="strict")
        return {"message": "已退出登录"}

    @app.post("/library/claim")
    def claim(body: Claim, request: Request):
        user, _ = identity(request)
        digest = token_hash(body.guest_token)
        with store.connection() as db:
            row = db.execute("SELECT user_id FROM guest_claims WHERE token_hash=?", (digest,)).fetchone()
            if row and row[0] != user["id"]:
                raise HTTPException(409, "这批游客曲谱已归属其他账号")
            db.execute("INSERT OR IGNORE INTO guest_claims VALUES (?,?)", (digest, user["id"]))
        return {"user_id": user["id"]}

    @app.get("/library/songs")
    def list_songs(request: Request):
        user, _ = identity(request)
        with store.connection() as db:
            rows = db.execute("SELECT song_id AS id,title,created_at FROM user_songs WHERE user_id=? ORDER BY created_at,song_id",
                              (user["id"],)).fetchall()
        return {"songs": [dict(row) for row in rows]}

    @app.post("/library/songs")
    def upload_score(body: dict, request: Request):
        user, _ = identity(request)
        limit_ip(request, "upload", 1000, 3600)
        try:
            score = normalize_score(body)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        sid = score_id(score)
        with store.connection() as db:
            owned = db.execute("SELECT 1 FROM user_songs WHERE user_id=? AND song_id=?", (user["id"], sid)).fetchone()
            if not owned and db.execute("SELECT count(*) FROM user_songs WHERE user_id=?", (user["id"],)).fetchone()[0] >= 500:
                raise HTTPException(409, "当前账号云端曲库最多保存 500 首，请先整理曲库")
            db.execute("INSERT OR IGNORE INTO songs VALUES (?,?)", (sid, json.dumps(score, ensure_ascii=False, separators=(",", ":"))))
            db.execute("INSERT INTO user_songs VALUES (?,?,?,?) ON CONFLICT(user_id,song_id) DO UPDATE SET title=excluded.title",
                       (user["id"], sid, score["title"], int(time.time())))
        return {"id": sid, "title": score["title"]}

    @app.get("/library/songs/{sid}")
    def get_score(sid: str, request: Request):
        user, _ = identity(request)
        with store.connection() as db:
            row = db.execute("SELECT songs.payload,user_songs.title FROM user_songs JOIN songs ON songs.id=user_songs.song_id "
                             "WHERE user_id=? AND song_id=?", (user["id"], sid)).fetchone()
        if not row:
            raise HTTPException(404, "曲目不存在")
        score = json.loads(row["payload"])
        score["title"] = row["title"]
        return score

    @app.delete("/library/songs/{sid}")
    def delete_score(sid: str, request: Request):
        user, _ = identity(request)
        with store.connection() as db:
            db.execute("DELETE FROM user_songs WHERE user_id=? AND song_id=?", (user["id"], sid))
            db.execute("DELETE FROM songs WHERE id=? AND NOT EXISTS(SELECT 1 FROM user_songs WHERE song_id=?)", (sid, sid))
        return {"message": "已从云端移除；已下载的本地副本保留"}

    return app
