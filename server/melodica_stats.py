#!/usr/bin/env python3
"""三角洲口风琴官网的最小统计服务。"""

import fcntl
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Dict
from urllib.parse import urlsplit


HOST = "127.0.0.1"
PORT = 3002
DATA_DIR = Path(os.environ.get("MELODICA_STATS_DIR", "/var/lib/delta-melodica-stats"))
DATA_FILE = DATA_DIR / "stats.json"
DOWNLOAD_LOCATION = "/melodica/downloads/delta-melodica-v0.15.exe"


def now_text() -> str:
    """返回便于后台显示的 UTC 时间。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_stats() -> Dict[str, Any]:
    """返回初始统计数据。"""
    return {"views": 0, "downloads": 0, "created_at": now_text(), "updated_at": None}


def change_counter(field: str) -> Dict[str, Any]:
    """在文件锁内递增一个统计字段。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        try:
            stats = json.load(handle)
        except (json.JSONDecodeError, ValueError):
            stats = default_stats()
        stats[field] = int(stats.get(field, 0)) + 1
        stats["updated_at"] = now_text()
        handle.seek(0)
        handle.truncate()
        json.dump(stats, handle, ensure_ascii=False, indent=2)
        handle.flush()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return stats


def read_stats() -> Dict[str, Any]:
    """读取当前统计数据。"""
    if not DATA_FILE.exists():
        return default_stats()
    with DATA_FILE.open("r", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            return json.load(handle)
        except (json.JSONDecodeError, ValueError):
            return default_stats()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """兼容旧版 Python 的线程 HTTP 服务。"""

    daemon_threads = True


class StatsHandler(BaseHTTPRequestHandler):
    """处理公开计数入口和私有统计接口。"""

    def send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/download":
            change_counter("downloads")
            self.send_response(302)
            self.send_header("Location", DOWNLOAD_LOCATION)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path == "/stats":
            self.send_json(read_stats())
            return
        if path == "/health":
            self.send_json({"status": "ok"})
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/view":
            change_counter("views")
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        """保留简洁的服务日志，避免记录请求体或曲谱内容。"""
        print(f"{self.address_string()} - {format % args}", flush=True)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        DATA_FILE.write_text(json.dumps(default_stats(), ensure_ascii=False, indent=2), encoding="utf-8")
    server = ThreadingHTTPServer((HOST, PORT), StatsHandler)
    print(f"统计服务监听 {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
