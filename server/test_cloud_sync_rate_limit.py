"""验证同步路由保留路径及账号防护，异常配置不被误改。"""

import unittest
from server.fix_cloud_sync_rate_limit import patch_config, patch_zones, ZONE


class CloudSyncRateLimitTest(unittest.TestCase):
    def test_sync_keeps_library_path_and_login_limits(self):
        original = """location /melodica/account-api/ {
    proxy_pass http://127.0.0.1:3003/;
    proxy_set_header Authorization $http_authorization;
    limit_req zone=delta_api_guard burst=8 nodelay;
    limit_req_status 429;
    limit_conn delta_conn_guard 8;
}
"""
        result = patch_config(original)
        self.assertTrue(result.startswith(original.rstrip()))
        sync = result.split("location ^~", 1)[1]
        self.assertIn("proxy_pass http://127.0.0.1:3003/library/;", sync)
        self.assertIn("Authorization $http_authorization", sync)
        self.assertIn("limit_conn delta_conn_guard 8;", sync)
        self.assertIn("limit_req zone=delta_sync_guard burst=30;", sync)
        self.assertNotIn("nodelay", sync)
        self.assertNotIn("delta_api_guard", sync)
        self.assertEqual(result, patch_config(result))

    def test_zone_is_independent_and_idempotent(self):
        original = "limit_req_zone $binary_remote_addr zone=delta_api_guard:16m rate=1r/s;\n"
        result = patch_zones(original)
        self.assertTrue(result.startswith(original))
        self.assertIn(ZONE, result)
        self.assertEqual(result, patch_zones(result))

    def test_unexpected_config_is_rejected(self):
        for text in ("", "location /melodica/account-api/ { proxy_pass http://localhost/; }"):
            with self.assertRaises(ValueError):
                patch_config(text)
        with self.assertRaises(ValueError):
            patch_zones("limit_req_zone $binary_remote_addr zone=delta_sync_guard:16m rate=1r/s;")
