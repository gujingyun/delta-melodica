"""使用独立曲库验证每首曲目的参数保存与恢复。"""
import gc
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

import mido

from app import App


class SongSettingsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.app = App(self.root, self.folder.name, smoke=True)
        self.app.overlay.enabled = False
        self.root.update()

    def tearDown(self):
        self.app.close()
        self.app = self.root = None
        gc.collect()
        self.folder.cleanup()

    def select(self, index):
        self.app.library.selection_clear(0, "end")
        self.app.library.selection_set(index)
        self.app.select_song()

    def restart(self):
        self.app.close()
        self.app = self.root = None
        gc.collect()
        self.root = tk.Tk()
        self.app = App(self.root, self.folder.name, smoke=True)
        self.app.overlay.enabled = False
        self.root.update()

    def add_midi(self, name):
        midi = mido.MidiFile()
        for pitch in (60, 72):
            midi.tracks.append(mido.MidiTrack([
                mido.Message("note_on", note=pitch),
                mido.Message("note_off", note=pitch, time=3840),
            ]))
        path = self.app.library_dir / name
        midi.save(path)
        return path

    def test_song_switch_and_restart_restore_independent_parameters(self):
        self.app.change_speed(1)
        self.app.change_transpose(3)
        self.app.track_combo.current(1)
        self.app.arrangement.set("钢琴适配 · 连奏")
        self.app.rebuild_plan()
        self.select(1)
        self.assertEqual((self.app.speed.get(), self.app.transpose.get()), ("1.00", "0"))
        self.app.change_speed(-1)
        self.app.change_transpose(-2)
        self.select(0)
        self.assertEqual((self.app.speed.get(), self.app.transpose.get()), ("1.25", "3"))
        self.assertEqual(self.app.track_combo.current(), 1)
        self.assertEqual(self.app.plan.style, "piano")
        self.restart()
        self.assertEqual((self.app.speed.get(), self.app.transpose.get()), ("1.25", "3"))
        self.assertIsNone(self.app.plan.track)
        self.assertEqual(self.app.plan.style, "piano")
        self.select(1)
        self.assertEqual((self.app.speed.get(), self.app.transpose.get()), ("0.75", "-2"))

    def test_same_named_midi_entries_keep_separate_track_and_style(self):
        first = self.add_midi("11111111__同名.mid")
        second = self.add_midi("22222222__同名.mid")
        self.app._load_library(first)
        self.app.track_combo.current(self.app.track_ids.index(0))
        self.app.arrangement.set("原谱 · 分音")
        self.app.rebuild_plan()
        self.app._load_library(second)
        self.assertEqual(self.app.track_combo.current(), 0)
        self.assertEqual(self.app.plan.style, "piano")
        self.app.change_transpose(5)
        self.app._load_library(first)
        self.assertEqual(self.app.plan.track, 0)
        self.assertEqual(self.app.plan.style, "original")
        self.assertEqual(self.app.transpose.get(), "0")
        self.restart()
        self.app._load_library(second)
        self.assertEqual(self.app.transpose.get(), "5")

    def test_invalid_saved_values_fall_back_without_overwriting_file(self):
        path = Path(self.folder.name, "song-settings.json")
        data = {self.app.song_preference_key(): {
            "speed": "nan", "transpose": True, "track": 999, "style": ["piano"],
        }}
        original = json.dumps(data)
        path.write_text(original, encoding="utf-8")
        self.restart()
        self.assertEqual((self.app.speed.get(), self.app.transpose.get()), ("1.00", "0"))
        self.assertEqual(self.app.track_combo.current(), 0)
        self.assertEqual(self.app.plan.style, "original")
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_corrupt_preferences_do_not_prevent_startup(self):
        Path(self.folder.name, "song-settings.json").write_text("{", encoding="utf-8")
        self.restart()
        self.assertTrue(self.app.plan.notes)
        self.assertIn("曲目设置读取失败", self.app.detail.get())

    def test_failed_save_keeps_plan_and_previous_file_with_visible_error(self):
        self.app.change_speed(1)
        path = Path(self.folder.name, "song-settings.json")
        original = path.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("模拟磁盘写入失败")):
            self.app.change_transpose(1)
        self.assertEqual(self.app.plan.notes[0].source_pitch, 61)
        self.assertEqual(path.read_bytes(), original)
        self.assertIn("曲目设置未保存", self.app.detail.get())


if __name__ == "__main__":
    unittest.main(verbosity=2)
