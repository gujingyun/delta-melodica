"""使用隔离曲库验证导入、重开、编辑、同步读取和错误曲目清理。"""
import gc
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from account_client import read_local_score
from app import App
from cloud_score import from_song
from music import parse_jianpu
from online_library import OnlineSong, download_online_song, validate_score_file
from test_online_library import Response


class ScoreFileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.app = App(self.root, Path(self.folder.name) / "profile", smoke=True)
        self.root.update()

    def tearDown(self):
        if self.app.score_editor:
            self.app.score_editor.close(force=True)
        self.app.close()
        self.app = self.root = None
        gc.collect()
        self.folder.cleanup()

    def import_score(self, data, encoding):
        source = Path(self.folder.name) / "导入样例.json"
        source.write_text(json.dumps(data, ensure_ascii=False), encoding=encoding)
        with patch("app.filedialog.askopenfilenames", return_value=[str(source)]), \
                patch("app.messagebox.showerror") as error:
            self.app.import_midi()
        error.assert_not_called()
        self.assertEqual(self.app.song.title, data["title"])
        return self.app.current_source[1]

    def assert_editable(self, text):
        self.app.edit_song()
        self.root.update()
        self.assertEqual(self.app.score_editor.text.get("1.0", "end-1c"), text)
        self.app.score_editor.close(force=True)

    def test_bom_import_survives_restart_edit_and_sync_read(self):
        data = from_song(parse_jianpu("1 0 2 2:2", 90, "带 BOM 的简谱"))
        data["editor"] = {"score": "1 0 2 2:2", "bpm": 90, "style": "original"}
        destination = self.import_score(data, "utf-8-sig")
        expected = read_local_score(destination)
        self.assertEqual(from_song(self.app.song), expected)
        self.assert_editable(data["editor"]["score"])
        self.app.close()
        self.app = self.root = None
        gc.collect()
        self.root = tk.Tk()
        self.app = App(self.root, Path(self.folder.name) / "profile", smoke=True)
        with patch("app.messagebox.showerror") as error:
            self.app._load_library(destination)
        error.assert_not_called()
        self.assertEqual(from_song(self.app.song), expected)
        self.assert_editable(data["editor"]["score"])

    def test_bom_download_preserves_bytes_and_loads(self):
        data = from_song(parse_jianpu("1 2 3", title="下载编码样例"))
        body = json.dumps(data, ensure_ascii=False).encode("utf-8-sig")
        song = OnlineSong("bom", data["title"], "https://example.test/score.json", format="score")
        with patch("online_library.urllib.request.urlopen", return_value=Response(body)):
            destination = download_online_song(song, self.app.library_dir)
        self.assertEqual(destination.read_bytes(), body)
        with patch("app.messagebox.showerror") as error:
            self.app._load_library(destination)
        error.assert_not_called()
        self.assertEqual(from_song(self.app.song), data)

    def test_legacy_import_preserves_original_text_and_bpm(self):
        data = {"title": "旧版简谱", "bpm": 90, "score": "1 0 2 2:2"}
        expected = from_song(parse_jianpu(data["score"], data["bpm"], data["title"]))
        for encoding in ("utf-8", "utf-8-sig"):
            with self.subTest(encoding=encoding):
                destination = self.import_score(data, encoding)
                self.assertEqual(from_song(self.app.song), expected)
                self.assertEqual(read_local_score(destination), expected)
                self.assert_editable(data["score"])

    def test_invalid_versions_and_editor_data_are_not_accepted_as_legacy(self):
        legacy = {"title": "无效格式", "bpm": 100, "score": "1 2 3"}
        standard = from_song(parse_jianpu("1 2 3", title="无效附注"))
        cases = [dict(legacy, version=version) for version in (None, 2, True, "1")]
        cases += [[], dict(legacy, score=3), dict(legacy, title=[]), dict(legacy, bpm=0),
                  dict(standard, editor={"score": "7", "bpm": 100})]
        path = Path(self.folder.name) / "invalid.json"
        for data in cases:
            with self.subTest(data=data):
                path.write_text(json.dumps(data), encoding="utf-8-sig")
                with self.assertRaises(ValueError):
                    validate_score_file(path)

    def test_broken_song_can_be_removed_without_affecting_original_or_other_songs(self):
        original = Path(self.folder.name) / "原始文件.json"
        original.write_text("{", encoding="utf-8")
        broken = self.app.library_dir / "broken.json"
        broken.write_bytes(original.read_bytes())
        good = self.app.library_dir / "good.json"
        good.write_text(json.dumps({"title": "正常曲目", "bpm": 100, "score": "1 2 3"}), encoding="utf-8")
        self.app.song_preferences["file:broken.json"] = {"speed": 1.5}
        with patch("app.messagebox.showerror") as error:
            self.app._load_library(broken)
        error.assert_called_once()
        self.assertIsNone(self.app.current_source)
        self.assertEqual(str(self.app.delete_button["state"]), "normal")
        self.assertEqual(str(self.app.edit_button["state"]), "disabled")
        with patch("app.messagebox.askyesno", return_value=False):
            self.app.delete_button.invoke()
        self.assertTrue(broken.exists())
        with patch("app.messagebox.askyesno", return_value=True):
            self.app.delete_button.invoke()
        self.assertFalse(broken.exists())
        self.assertEqual(original.read_text(encoding="utf-8"), "{")
        self.assertTrue(good.exists())
        self.assertNotIn("file:broken.json", self.app.song_preferences)
        self.app._load_library(good)
        self.assertEqual(self.app.song.title, "正常曲目")


if __name__ == "__main__":
    unittest.main(verbosity=2)
