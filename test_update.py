"""验证版本号和官网更新清单的解析。"""
import json
from unittest.mock import Mock, patch
import unittest

from app import APP_VERSION, fetch_update_manifest, parse_update_manifest, parse_version


class UpdateTests(unittest.TestCase):
    def test_version_parser_accepts_optional_prefix_and_compares_numeric_parts(self):
        self.assertEqual(parse_version("v0.10"), (0, 10))
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))
        self.assertGreater(parse_version("0.13"), parse_version(APP_VERSION))
        self.assertLess(parse_version("0.10"), parse_version(APP_VERSION))

    def test_manifest_requires_valid_version_and_normalizes_notes(self):
        manifest = parse_update_manifest({"version": "v0.13", "notes": "  新增更新检查。  "})
        self.assertEqual(manifest, {"version": "0.13", "version_tuple": (0, 13), "notes": "新增更新检查。"})
        for payload in ({}, {"version": "latest"}, {"version": "0.13", "notes": []}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_update_manifest(payload)

    def test_fetch_manifest_decodes_json_with_timeout(self):
        response = Mock()
        response.read.return_value = json.dumps({"version": "0.13", "notes": "修复问题"}).encode("utf-8")
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch("app.urllib.request.urlopen", return_value=response) as urlopen:
            manifest = fetch_update_manifest("https://example.test/version.json")
        self.assertEqual(manifest["version"], "0.13")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/version.json")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5)

    def test_update_notice_opens_official_page_after_confirmation(self):
        from app import App, UPDATE_PAGE_URL

        app = App.__new__(App)
        app.root = object()
        manifest = {"version": "0.13", "notes": "新增检查更新。"}
        with patch("app.messagebox.askyesno", return_value=True), patch("app.webbrowser.open") as open_page:
            App._show_update_notice(app, manifest)
        open_page.assert_called_once_with(UPDATE_PAGE_URL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
