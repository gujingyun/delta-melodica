"""验证公开曲库后台上传接口的鉴权、校验、脱敏和原子发布。"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

import mido
from fastapi.testclient import TestClient

from cloud_score import from_song
from music import parse_jianpu
from online_library import parse_catalog
from server.public_library import (Config, MAX_ONLINE_SONG_BYTES, build_public_plan,
                                   create_app)


ADMIN_TOKEN = "a" * 32


def midi_bytes() -> bytes:
    """生成最小有效 MIDI，避免测试依赖线上或仓库外部曲目。"""
    midi = mido.MidiFile(type=0, ticks_per_beat=480)
    midi.tracks.append(mido.MidiTrack([
        mido.MetaMessage("track_name", name="Test Melody"),
        mido.Message("note_on", note=60, velocity=80),
        mido.Message("note_off", note=60, time=480),
    ]))
    output = BytesIO()
    midi.save(file=output)
    return output.getvalue()


class PublicLibraryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        (self.root / "songs").mkdir()
        (self.root / "songs.json").write_text(json.dumps({"version": 2, "songs": []}), encoding="utf-8")
        config = Config(self.root, "https://example.test/melodica/songs.json",
                        self.root / "state" / "publish.lock", ADMIN_TOKEN)
        self.app = create_app(config)
        self.client = TestClient(self.app, base_url="https://example.test")
        self.headers = {"Authorization": "Bearer " + ADMIN_TOKEN}

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def upload(self, filename, body, data=None, headers=None):
        return self.client.post(
            "/library/songs",
            files={"file": (filename, body, "application/octet-stream")},
            data=data or {},
            headers=headers or self.headers,
        )

    def test_requires_admin_token_and_does_not_echo_it(self):
        response = self.upload("demo.mid", midi_bytes(), headers={"Authorization": "Bearer wrong"})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(ADMIN_TOKEN, response.text)
        self.assertFalse(list((self.root / "songs").iterdir()))

    def test_uploads_midi_and_retry_is_idempotent(self):
        body = midi_bytes()
        first = self.upload("../../private-name.mid", body, {"title": "公开曲目", "artist": "测试作者"})
        self.assertEqual(first.status_code, 201, first.text)
        result = first.json()
        self.assertFalse(result["already_exists"])
        self.assertEqual(result["size"], len(body))
        self.assertEqual(result["sha256"], sha256(body).hexdigest())

        second = self.upload("demo.mid", body, {"title": "忽略的新标题"})
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json()["already_exists"])
        self.assertEqual(second.json()["title"], "公开曲目")

        catalog = json.loads((self.root / "songs.json").read_text(encoding="utf-8"))
        self.assertEqual(len(catalog["songs"]), 1)
        entry = catalog["songs"][0]
        self.assertEqual(entry["title"], "公开曲目")
        self.assertEqual((self.root / "songs" / f"{entry['id']}.mid").read_bytes(), body)

    def test_json_upload_removes_private_metadata_and_keeps_editor(self):
        source = from_song(parse_jianpu("1 2 3", 120, "原始曲名"))
        source["editor"] = {
            "score": "1 2 3", "bpm": 120, "style": "original",
            "source_url": "https://private.example/source",
        }
        source["image_score"] = {"artist": "默认作者", "description": "公开说明",
                                  "local_path": "D:/private-path"}
        body = json.dumps(source, ensure_ascii=False).encode("utf-8")
        response = self.upload("score.json", body)
        self.assertEqual(response.status_code, 201, response.text)

        entry = response.json()
        public_body = (self.root / "songs" / f"{entry['id']}.json").read_bytes()
        public = json.loads(public_body)
        self.assertEqual(public["editor"], {"score": "1 2 3", "bpm": 120, "style": "original"})
        self.assertNotIn("image_score", public)
        self.assertNotIn("source_url", public["editor"])
        self.assertNotIn("D:/private-path", public_body.decode("utf-8"))
        self.assertEqual(parse_catalog(json.loads((self.root / "songs.json").read_text(encoding="utf-8")),
                                       "https://example.test/melodica/songs.json")[0].format, "score")

    def test_invalid_upload_is_rejected_without_catalog_change(self):
        before = (self.root / "songs.json").read_bytes()
        response = self.upload("broken.mid", b"not a midi")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("MThd", response.text)
        self.assertEqual((self.root / "songs.json").read_bytes(), before)
        self.assertFalse(list((self.root / "songs").iterdir()))

    def test_catalog_error_returns_service_error_and_list_requires_auth(self):
        self.assertEqual(self.client.get("/library/songs").status_code, 401)
        (self.root / "songs.json").write_text("not-json", encoding="utf-8")
        response = self.client.get("/library/songs", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("not-json", response.text)

    def test_local_plan_rejects_oversized_upload_before_parsing(self):
        with self.assertRaisesRegex(ValueError, "10 MB"):
            build_public_plan("big.mid", b"x" * (MAX_ONLINE_SONG_BYTES + 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
