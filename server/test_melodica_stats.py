"""在临时目录和回环端口验证统计服务，不触碰线上数据。"""

from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest

try:
    import fcntl
except ImportError:
    fcntl = None

if fcntl is not None:
    from server import melodica_stats as stats


@unittest.skipIf(fcntl is None, "需要 Linux 的真实文件锁，请在 Linux 运行")
class StatsTests(unittest.TestCase):
    """覆盖旧数据迁移、两端隔离、请求方法与并发写入。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="melodica-stats-test-")
        self.addCleanup(self.folder.cleanup)
        self.old_dir, self.old_file = stats.DATA_DIR, stats.DATA_FILE
        stats.DATA_DIR = Path(self.folder.name)
        stats.DATA_FILE = stats.DATA_DIR / "stats.json"
        self.addCleanup(self.restore_paths)

        class QuietHandler(stats.StatsHandler):
            def log_message(self, format, *args):
                """隔离测试不输出每条请求。"""

        self.server = stats.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def restore_paths(self):
        stats.DATA_DIR, stats.DATA_FILE = self.old_dir, self.old_file

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path):
        connection = HTTPConnection(*self.server.server_address, timeout=10)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def seed_legacy(self):
        legacy = {"views": 285, "downloads": 185, "created_at": "2026-09-11T15:35:54+00:00", "updated_at": None}
        stats.DATA_FILE.write_text(json.dumps(legacy), encoding="utf-8")
        return stats.DATA_FILE.read_bytes()

    def test_legacy_read_preserves_history_without_rewriting(self):
        before = self.seed_legacy()
        status, _, body = self.request("GET", "/stats")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual((data["downloads_windows"], data["downloads_android"], data["downloads"]), (185, 0, 185))
        self.assertEqual(data["views"], 285)
        self.assertEqual(stats.DATA_FILE.read_bytes(), before)

    def test_first_android_and_windows_downloads_migrate_once(self):
        self.seed_legacy()
        for path, target, expected in [
            ("/download/android?source=website", stats.ANDROID_DOWNLOAD_LOCATION, (185, 1, 186)),
            ("/download", stats.DOWNLOAD_LOCATION, (186, 1, 187)),
            ("/download/android", stats.ANDROID_DOWNLOAD_LOCATION, (186, 2, 188)),
        ]:
            status, headers, body = self.request("GET", path)
            self.assertEqual(status, 302)
            self.assertEqual(headers["Location"], target)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(body, b"")
            data = json.loads(stats.DATA_FILE.read_text(encoding="utf-8"))
            self.assertEqual((data["downloads_windows"], data["downloads_android"], data["downloads"]), expected)
            self.assertEqual(data["created_at"], "2026-09-11T15:35:54+00:00")
            self.assertEqual(data["views"], 285)

    def test_head_probes_do_not_count(self):
        before = self.seed_legacy()
        for path, target in [("/download", stats.DOWNLOAD_LOCATION), ("/download/android", stats.ANDROID_DOWNLOAD_LOCATION)]:
            status, headers, body = self.request("HEAD", path)
            self.assertEqual((status, headers["Location"], body), (302, target, b""))
        self.assertEqual(stats.DATA_FILE.read_bytes(), before)

    def test_other_routes_and_methods_do_not_count(self):
        before = self.seed_legacy()
        for method, path, expected in [
            ("GET", "/health", 200), ("GET", "/stats?ts=1", 200),
            ("GET", "/download/unknown", 404), ("GET", "/download/android/extra", 404),
            ("POST", "/download/android", 404), ("HEAD", "/download/unknown", 404),
        ]:
            self.assertEqual(self.request(method, path)[0], expected)
        self.assertEqual(stats.DATA_FILE.read_bytes(), before)

    def test_view_migration_does_not_change_downloads(self):
        self.seed_legacy()
        self.assertEqual(self.request("POST", "/view")[0], 204)
        data = stats.read_stats()
        self.assertEqual((data["views"], data["downloads_windows"], data["downloads_android"], data["downloads"]), (286, 185, 0, 185))

    def test_fresh_install_starts_at_zero(self):
        self.assertEqual(stats.read_stats()["downloads"], 0)
        self.request("GET", "/download/android")
        data = stats.read_stats()
        self.assertEqual((data["downloads_windows"], data["downloads_android"], data["downloads"]), (0, 1, 1))

    def test_concurrent_requests_preserve_both_platform_counts(self):
        self.seed_legacy()
        paths = ["/download", "/download/android", "/view"] * 20
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda path: self.request("POST" if path == "/view" else "GET", path)[0], paths))
        self.assertEqual(responses.count(302), 40)
        self.assertEqual(responses.count(204), 20)
        data = stats.read_stats()
        self.assertEqual((data["views"], data["downloads_windows"], data["downloads_android"], data["downloads"]), (305, 205, 20, 225))


if __name__ == "__main__":
    unittest.main()
