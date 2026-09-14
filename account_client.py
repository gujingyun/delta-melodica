"""Windows 账号请求、受保护会话和可恢复的游客曲库继承。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import urllib.error
import urllib.parse
import urllib.request

from cloud_score import MAX_SCORE_BYTES, from_song, normalize_score, score_id
from score_file import read_score_data, score_from_data


API_URL = "https://aiygzn.top/melodica/account-api"


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def validate_claims(state):
    """先校验完整归属记录，再允许据此恢复或分配曲目。"""
    def filename(value):
        return (isinstance(value, str) and value not in ("", ".", "..")
                and Path(value).name == value and ":" not in value)

    def user_id(value):
        return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value)

    if not isinstance(state, dict) or not isinstance(state.get("owners"), dict):
        raise ValueError("归属表格式不正确")
    if any(not filename(name) or not user_id(owner) for name, owner in state["owners"].items()):
        raise ValueError("归属表包含无效的文件名或账号编号")
    pending = state.get("pending")
    if pending is not None and (not isinstance(pending, dict) or not user_id(pending.get("user_id"))
            or not isinstance(pending.get("guest_token"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", pending["guest_token"])
            or not isinstance(pending.get("files"), list)
            or any(not filename(name) for name in pending["files"])):
        raise ValueError("未完成的继承批次格式不正确")
    return state


def protect_bytes(data, decrypt=False):
    """使用当前 Windows 用户的 DPAPI，磁盘不保存明文登录令牌。"""
    class Blob(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.data, output.length)
    finally:
        kernel.LocalFree(output.data)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise ValueError("账号服务发生重定向，请检查服务地址")


class AccountError(ValueError):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class AccountClient:
    def __init__(self, data_dir, api_url=None):
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.api_url = (api_url or os.environ.get("MELODICA_ACCOUNT_API", API_URL)).rstrip("/")
        parsed = urllib.parse.urlsplit(self.api_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname or (
                parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost"))):
            raise ValueError("账号服务必须使用 HTTPS，本机联调除外")
        self.opener = urllib.request.build_opener(NoRedirect)
        self.session = None
        self.warning = ""
        try:
            value = json.loads(protect_bytes((self.root / "account-session.bin").read_bytes(), decrypt=True))
            if value.get("api_url") == self.api_url and re.fullmatch(r"[a-f0-9]{32}", value["user"]["id"]):
                self.session = value
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, TypeError, OSError):
            self.warning = "登录凭据无法恢复，请重新登录；曲谱仍保留在本机"
        self.state = {"owners": {}, "pending": None}
        self.claims_error = ""
        try:
            self.state = validate_claims(read_json(self.root / "guest-claims.json", self.state))
        except (ValueError, OSError):
            # 不覆盖损坏记录，也不把未知归属当成尚未归属。
            self.claims_error = ("游客继承记录无法读取，已暂停合并；原文件保留，本地曲库仍可使用。"
                                 "请恢复数据目录中的 guest-claims.json 备份后重新启动。")
            self.warning = "；".join(filter(None, (self.warning, self.claims_error)))
        try:
            self.restore_claims()
        except OSError:
            self.warning = "；".join(filter(None, (self.warning, "游客曲库副本恢复未完成，可在账号面板重试合并；原文件保留")))

    @property
    def user(self):
        return self.session["user"] if self.session else None

    @property
    def profile_dir(self):
        return self.root / "accounts" / self.user["id"] if self.user else self.root

    @property
    def library_dir(self):
        path = self.profile_dir / "songs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def guest_files(self):
        """只返回尚可归属账号的游客文件；归属记录不影响游客本地显示。"""
        if self.claims_error:
            return []
        folder = self.root / "songs"
        return [p for p in sorted(folder.iterdir()) if p.is_file() and not p.is_symlink()
                and p.suffix.lower() in (".mid", ".midi", ".json") and p.name not in self.state["owners"]] if folder.exists() else []

    def request(self, method, path, payload=None):
        headers = {"Content-Type": "application/json", "User-Agent": "DeltaMelodica/Accounts-1"}
        if self.session:
            headers["Authorization"] = "Bearer " + self.session["token"]
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        if body and len(body) > MAX_SCORE_BYTES:
            raise AccountError("曲谱超过云同步大小限制 2 MB")
        request = urllib.request.Request(self.api_url + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=20) as response:
                body = response.read(MAX_SCORE_BYTES + 1)
            if len(body) > MAX_SCORE_BYTES:
                raise AccountError("账号服务响应过大")
            return json.loads(body)
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read(4096)).get("detail")
            except (ValueError, OSError):
                detail = None
            raise AccountError(detail if isinstance(detail, str) else "账号服务暂时不可用，请稍后重试", error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise AccountError("无法连接账号服务，请检查网络；本地曲库仍可使用") from None

    def save_session(self, response):
        if not re.fullmatch(r"[a-f0-9]{32}", response["user"]["id"]):
            raise AccountError("账号标识无效")
        response = dict(response, api_url=self.api_url)
        data = protect_bytes(json.dumps(response).encode())
        path = self.root / "account-session.bin"
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        self.session = response
        self.restore_claims()

    def authenticate(self, mode, email, password, code=""):
        payload = {"email": email, "password": password, "client": "native"}
        if mode == "register":
            payload["code"] = code
        response = self.request("POST", "/auth/" + mode, payload)
        self.save_session(response)
        return response

    def logout(self):
        warning = ""
        try:
            self.request("POST", "/auth/logout", {})
        except AccountError:
            # 离线退出也移除本机凭据，不把网络故障变成无法退出。
            warning = "本机已退出；网络不可用，服务器会话将到期失效"
        (self.root / "account-session.bin").unlink(missing_ok=True)
        self.session = None
        return warning or "已退出，当前为游客模式"

    def restore_claims(self):
        if self.claims_error:
            return
        pending = self.state.get("pending")
        if not self.user or not pending or pending["user_id"] != self.user["id"]:
            return
        for name, owner in self.state["owners"].items():
            if name in pending["files"] and owner == self.user["id"] and Path(name).name == name:
                source = self.root / "songs" / name
                target = self.library_dir / name
                if source.is_file() and not source.is_symlink() and not target.exists():
                    shutil.copy2(source, target)

    def claim_guest(self):
        """先记录批次再申请归属，成功后复制本地文件，原文件保留供游客继续使用。"""
        if self.claims_error:
            raise AccountError(self.claims_error)
        if not self.user:
            raise AccountError("请先登录后合并游客曲库", 401)
        pending = self.state.get("pending")
        if pending and pending["user_id"] != self.user["id"]:
            raise AccountError("有其他账号的游客继承尚未完成，请先登录原账号继续")
        if not pending:
            pending = {"user_id": self.user["id"], "guest_token": secrets.token_urlsafe(32),
                       "files": [p.name for p in self.guest_files()]}
            if not pending["files"]:
                return 0
            self.state["pending"] = pending
            atomic_json(self.root / "guest-claims.json", self.state)
        self.request("POST", "/library/claim", {"guest_token": pending["guest_token"]})
        for name in pending["files"]:
            self.state["owners"][name] = self.user["id"]
        atomic_json(self.root / "guest-claims.json", self.state)
        self.restore_claims()
        # 已完成的副本不再自动恢复，用户之后主动删除本地曲目应当生效。
        count = len(pending["files"])
        self.state["pending"] = None
        atomic_json(self.root / "guest-claims.json", self.state)
        return count

    def sync(self):
        if not self.user:
            raise AccountError("云端曲库同步需要登录；游客可继续使用本地曲库", 401)
        remote = self.request("GET", "/library/songs")["songs"]
        remote_ids, local_ids = {item["id"] for item in remote}, set()
        uploaded, downloaded, errors = 0, 0, []
        for path in sorted(self.library_dir.iterdir()):
            if not path.is_file() or path.is_symlink() or path.suffix.lower() not in (".mid", ".midi", ".json"):
                continue
            try:
                score = read_local_score(path)
                sid = score_id(score)
                local_ids.add(sid)
                if sid not in remote_ids:
                    self.request("POST", "/library/songs", score)
                    remote_ids.add(sid)
                    uploaded += 1
            except AccountError:
                raise
            except (ValueError, KeyError, TypeError, OSError) as error:
                errors.append(f"{path.name}：{error}")
        for item in remote:
            sid = item["id"]
            if sid in local_ids:
                continue
            if not re.fullmatch(r"[a-f0-9]{64}", sid):
                raise AccountError("云端曲目标识无效")
            score = normalize_score(self.request("GET", "/library/songs/" + sid))
            if score_id(score) != sid:
                raise AccountError("云端曲谱内容校验失败")
            safe = "".join(c for c in score["title"] if c not in '<>:"/\\|?*').rstrip(" .")[:70] or "云端曲目"
            atomic_json(self.library_dir / f"{sid}__{safe}.json", score)
            downloaded += 1
        return {"uploaded": uploaded, "downloaded": downloaded, "errors": errors}


def read_local_score(path):
    from music import read_midi
    path = Path(path)
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("曲谱文件超过 10 MB")
    if path.suffix.lower() == ".json":
        return normalize_score(from_song(score_from_data(read_score_data(path))))
    song = read_midi(path)
    song.title = path.stem.split("__", 1)[-1]
    return from_song(song)
