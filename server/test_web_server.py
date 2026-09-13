"""浏览器联调专用服务：隔离数据库、虚构邮件，禁止作为生产入口。"""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn
from server.accounts import Config, create_app


def main():
    root = Path(__file__).resolve().parents[1]
    artifacts = root / "work/accounts-web"
    artifacts.mkdir(parents=True, exist_ok=True)
    def mailer(email, purpose, code):
        (artifacts / "mail-test.json").write_text(json.dumps({"email": email, "purpose": purpose, "code": code}), encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="melodica-web-test-") as folder:
        api = create_app(Config(Path(folder), origin="http://127.0.0.1:8767", secure_cookie=False), mailer)
        limit = api.state.store.limit
        # 浏览器测试加速发送间隔；生产限流由 test_accounts 独立验证，不修改正式服务。
        api.state.store.limit = lambda key, count, seconds: None if key.startswith("mail-cooldown:") else limit(key, count, seconds)
        app = FastAPI()
        app.mount("/melodica/account-api", api)
        app.mount("/melodica", StaticFiles(directory=root / "website", html=True))
        uvicorn.run(app, host="127.0.0.1", port=8767, access_log=False)


if __name__ == "__main__":
    main()
