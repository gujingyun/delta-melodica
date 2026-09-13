"""官网曲谱 JSON 在聚合搜索与下载之间保留格式和可编辑原谱。"""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from cloud_score import from_song
from music import Mapping, parse_jianpu_space
from online_library import OnlineSong
from resource_search import SearchSong, download_resource, search_source
from test_online_library import Response


class ImageScoreDownloadTests(unittest.TestCase):
    def test_search_preserves_explicit_json_format_for_extensionless_url(self):
        song = OnlineSong("image", "图片识谱", "https://example.test/download/1", format="score")
        with patch("resource_search.fetch_catalog", return_value=[song]):
            result = search_source("official", "图片")
        self.assertEqual(result.songs[0].format, "score")

    def test_json_download_deduplicates_without_converting_or_losing_source(self):
        source = "/key(D4)\nbpm90\n1_2_ 3~3 0 5,"
        data = from_song(parse_jianpu_space(source, "官网图片简谱")[0])
        data["editor"] = {"score": source, "format": "jianpu_space", "mode": "score", "style": "original"}
        body = json.dumps(data).encode()
        song = SearchSong("official", "官网图片简谱", "https://example.test/", "https://example.test/download/1",
                          size=len(body), sha256=hashlib.sha256(body).hexdigest(), format="score")
        with tempfile.TemporaryDirectory() as folder:
            with patch("online_library.urllib.request.urlopen", return_value=Response(body)):
                first = download_resource(song, Path(folder), Mapping(), threading.Event())
            with patch("online_library.urllib.request.urlopen", return_value=Response(body)):
                second = download_resource(song, Path(folder), Mapping(), threading.Event())
            self.assertEqual(first, second)
            self.assertEqual(first.suffix, ".json")
            self.assertEqual(first.read_bytes(), body)
            self.assertEqual(len(list(Path(folder).iterdir())), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
