"""验证线上曲库目录校验和 MIDI 下载。"""
from __future__ import annotations

from hashlib import sha256
import io
import json
import time
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
import urllib.parse
from unittest.mock import Mock, patch

import mido

from music import read_midi
from app import App
from online_library import (OnlineSong, download_online_song, fetch_catalog,
                            parse_catalog)


def midi_bytes():
    """生成一个最小有效 MIDI，避免测试依赖仓库外部文件。"""
    midi = mido.MidiFile(type=0, ticks_per_beat=480)
    track = mido.MidiTrack([
        mido.MetaMessage("track_name", name="Test Melody"),
        mido.Message("note_on", note=60, velocity=80),
        mido.Message("note_off", note=60, time=480),
    ])
    midi.tracks.append(track)
    output = io.BytesIO()
    midi.save(file=output)
    return output.getvalue()


class Response:
    def __init__(self, body, headers=None):
        self.stream = io.BytesIO(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.stream.read(size)


class OnlineLibraryTests(unittest.TestCase):
    def test_catalog_resolves_relative_url_and_preserves_metadata(self):
        songs = parse_catalog({"songs": [{
            "id": "demo-1", "title": "测试曲", "artist": "测试作者",
            "description": "适合试听", "url": "songs/demo.mid",
            "size": 123, "sha256": "A" * 64,
        }]}, "https://example.test/melodica/songs.json")
        self.assertEqual(songs[0].url, "https://example.test/melodica/songs/demo.mid")
        self.assertEqual(songs[0].artist, "测试作者")
        self.assertEqual(songs[0].sha256, "a" * 64)

    def test_catalog_rejects_duplicate_or_unsafe_entries(self):
        for payload in (
            {"songs": [{"id": "same", "title": "一", "url": "a.mid"},
                       {"id": "same", "title": "二", "url": "b.mid"}]},
            {"songs": [{"id": "bad/id", "title": "一", "url": "a.mid"}]},
            {"songs": [{"id": "bad", "title": "一", "url": "file:///a.mid"}]},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_catalog(payload, "https://example.test/songs.json")

    def test_published_catalog_matches_bundled_midi_files(self):
        root = Path(__file__).parent
        payload = json.loads((root / "website" / "songs.json").read_text(encoding="utf-8"))
        songs = parse_catalog(payload, "https://aiygzn.top/melodica/songs.json")
        for song in songs:
            with self.subTest(song=song.song_id):
                filename = urllib.parse.unquote(urllib.parse.urlparse(song.url).path).split("/songs/", 1)[1]
                path = root / "website" / "songs" / filename
                body = path.read_bytes()
                self.assertEqual(len(body), song.size)
                self.assertEqual(sha256(body).hexdigest(), song.sha256.lower())

    def test_fetch_catalog_limits_response_and_uses_request_headers(self):
        body = b'{"songs": []}'
        with patch("online_library.urllib.request.urlopen", return_value=Response(body)) as urlopen:
            self.assertEqual(fetch_catalog("https://example.test/songs.json"), [])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/songs.json")
        self.assertEqual(request.get_header("User-agent"), "DeltaMelodica/0.13")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 8)

    def test_download_validates_hash_and_writes_readable_midi(self):
        body = midi_bytes()
        song = OnlineSong("demo-1", "测试/曲名", "https://example.test/demo.mid",
                          size=len(body), sha256=sha256(body).hexdigest())
        with tempfile.TemporaryDirectory() as folder, \
                patch("online_library.urllib.request.urlopen", return_value=Response(body)):
            destination = download_online_song(song, folder)
            self.assertTrue(destination.name.endswith("__测试曲名.mid"))
            self.assertTrue(read_midi(destination).notes)
            self.assertEqual(list(Path(folder).glob(".online-*.tmp")), [])

    def test_download_failure_removes_temporary_file(self):
        body = midi_bytes()
        song = OnlineSong("demo-1", "坏文件", "https://example.test/demo.mid",
                          sha256="0" * 64)
        with tempfile.TemporaryDirectory() as folder, \
                patch("online_library.urllib.request.urlopen", return_value=Response(body)), \
                self.assertRaisesRegex(ValueError, "SHA-256"):
            download_online_song(song, folder)
        self.assertEqual(list(Path(folder).glob(".online-*.tmp")), [])


class OnlineLibraryDialogTests(unittest.TestCase):
    """验证线上曲库对话框能把下载结果接回现有曲库。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.app = App(self.root, self.folder.name, smoke=True)
        self.app.overlay.enabled = False
        self.root.update()

    def tearDown(self):
        self.app.close()
        self.folder.cleanup()

    def wait_until(self, predicate):
        for _ in range(100):
            self.root.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("等待线上曲库界面事件超时")

    def test_dialog_fetches_catalog_and_loads_downloaded_song(self):
        online_song = OnlineSong("dialog-demo", "线上测试曲", "https://example.test/demo.mid")
        destination = Path(self.app.library_dir, "dialog-demo__线上测试曲.mid")
        destination.write_bytes(midi_bytes())
        with patch("app.fetch_catalog", return_value=[online_song]):
            self.app.online_library_dialog()
            self.wait_until(lambda: self.app.online_catalog_list and self.app.online_catalog_list.size() == 1)
        with patch("app.download_online_song", return_value=destination):
            self.app.download_online_selected()
            self.wait_until(lambda: self.app.current_source == ("file", destination))
        self.assertEqual(self.app.title.get(), "线上测试曲")
        self.assertIn("已下载", self.app.online_catalog_status.get())

    def test_dialog_searches_by_name_and_pages_results(self):
        songs = [OnlineSong(f"song-{index}", f"曲目 {index:02d}", "https://example.test/demo.mid")
                 for index in range(12)]
        with patch("app.fetch_catalog", return_value=songs):
            self.app.online_library_dialog()
            self.wait_until(lambda: self.app.online_catalog_list and self.app.online_catalog_list.size() == 10)
        self.assertEqual(self.app.online_page_label.get(), "第 1 / 2 页 · 共 12 首")
        self.app.change_online_page(1)
        self.root.update()
        self.assertEqual(self.app.online_catalog_list.size(), 2)
        self.assertEqual(self.app.online_visible_songs[0].title, "曲目 10")
        self.app.online_search.set("曲目 11")
        self.app.apply_online_search()
        self.root.update()
        self.assertEqual(self.app.online_catalog_list.size(), 1)
        self.assertEqual(self.app.online_visible_songs[0].title, "曲目 11")
        self.app.online_search.set("不存在")
        self.app.apply_online_search()
        self.root.update()
        self.assertEqual(self.app.online_catalog_list.size(), 0)
        self.assertIn("没有匹配", self.app.online_page_label.get())


if __name__ == "__main__":
    unittest.main(verbosity=2)
