"""验证扒谱旋律整理、独立进程退出、取消及曲库完整落盘。"""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from audio_transcription import AudioOptions, AudioTranscription
from cloud_score import to_song
from music import Mapping, transcribed_melody


class MelodyTranscriptionTests(unittest.TestCase):
    def test_strong_melody_wins_over_high_harmonic_and_preserves_repeated_notes(self):
        song = transcribed_melody([[0, .5, 60, .9], [0, 1, 84, .3], [.6, 1, 60, .8],
                                   [1.2, 1.7, 62, .95]], 2, "旋律")
        self.assertEqual([n.pitch for n in song.notes], [60, 84, 60, 62])
        self.assertEqual(song.notes[0].end, .5)
        self.assertEqual(song.notes[2].start, .6)
        self.assertEqual(song.duration, 2)

    def test_weak_short_notes_are_filtered_without_quantizing_timing(self):
        song = transcribed_melody([[.137, .487, 64, .85], [.55, .58, 70, .8], [.6, .8, 76, .1]], 1, "片段")
        self.assertEqual(len(song.notes), 1)
        self.assertAlmostEqual(song.notes[0].start, .137)
        self.assertAlmostEqual(song.notes[0].end, .487)

    def test_empty_and_invalid_result_is_rejected(self):
        for notes, duration in (([], 1), ([[0, 1, 60, .01]], 1), ([[0, 1, 60, 2]], 1),
                                ([[0, 1, 128, .8]], 1), ([[0, 1, 60, .8]], float("nan")),
                                ([[0, 2, 60, .8]], 1), ([[0, .5, 60.5, .9]], 1)):
            with self.subTest(notes=notes, duration=duration), self.assertRaises(ValueError):
                transcribed_melody(notes, duration, "测试")

    def test_options_reject_invalid_range(self):
        for options in (AudioOptions(start=-1), AudioOptions(duration=0), AudioOptions(duration=601),
                        AudioOptions(start=float("nan")), AudioOptions(mode="other")):
            with self.subTest(options=options), self.assertRaises(ValueError):
                options.validate()
        AudioOptions(duration=None).validate()

    def test_trim_leading_keeps_internal_rest_and_duration(self):
        song = transcribed_melody([[10, 10.5, 60, .9], [11, 11.5, 62, .9]], 12, "人声", trim_leading=True)
        self.assertEqual([(n.start, n.end) for n in song.notes], [(0, .5), (1, 1.5)])
        self.assertEqual(song.duration, 2)


class AudioProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.audio = self.folder / "带 空格中文.mp3"
        self.audio.write_bytes(b"test")
        self.script = self.folder / "engine.py"
        self.library = self.folder / "songs"
        self.job = None

    def tearDown(self):
        if self.job:
            self.job.cancel()
            if self.job.thread:
                self.job.thread.join(6)
        self.temp.cleanup()

    def run_engine(self, body, wait=True):
        self.script.write_text("import json, pathlib, sys, time\njob=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))\nfolder=pathlib.Path(job['folder'])\n" + body, encoding="utf-8")
        self.job = AudioTranscription(self.audio, self.library, Mapping(), AudioOptions("solo"),
                                      ([sys.executable, str(self.script)], self.folder))
        self.job.start()
        if wait:
            self.job.thread.join(6)
            self.assertFalse(self.job.active)
        return self.job

    def events(self):
        values = []
        while not self.job.events.empty():
            values.append(self.job.events.get_nowait())
        return values

    def test_success_writes_compatible_score_and_retains_original_audio(self):
        self.run_engine("(folder/'result.json').write_text(json.dumps({'duration':1,'notes':[[0,.8,60,.9]]}))\n")
        kind, (path, count, duration) = self.events()[-1]
        self.assertEqual((kind, count, duration), ("done", 1, 1))
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(to_song(data).notes[0].pitch, 60)
        self.assertEqual(data["transcription"]["source"], self.audio.name)
        self.assertEqual(self.audio.read_bytes(), b"test")
        self.assertEqual(list(self.library.iterdir()), [path])

    def test_cancel_terminates_worker_and_leaves_no_partial_score(self):
        self.run_engine("(folder/'progress.json').write_text('{\"message\":\"running\"}')\ntime.sleep(60)\n", wait=False)
        deadline = time.monotonic() + 3
        while self.job.process is None and time.monotonic() < deadline:
            time.sleep(.01)
        self.job.cancel()
        self.job.thread.join(6)
        self.assertFalse(self.job.active)
        self.assertIsNotNone(self.job.process.poll())
        self.assertEqual(list(self.library.iterdir()), [])
        self.assertEqual(self.events()[-1][0], "cancelled")

    def test_worker_error_and_invalid_results_do_not_enter_library(self):
        for body in ("(folder/'error.json').write_text('{\"message\":\"failed\"}')\nsys.exit(1)\n",
                     "(folder/'result.json').write_text('{\"duration\":1,\"notes\":[]}')\n"):
            with self.subTest(body=body):
                self.run_engine(body)
                self.assertEqual(self.events()[-1][0], "error")
                self.assertEqual(list(self.library.iterdir()), [])

    def test_no_engine_does_not_start_thread(self):
        job = AudioTranscription(self.audio, self.library, Mapping(), AudioOptions(), (["missing.exe"], self.folder))
        job.start()
        job.thread.join(3)
        self.assertEqual(job.events.get_nowait()[0], "error")


if __name__ == "__main__":
    unittest.main()
