"""使用独立曲库验证每首曲目的参数保存与恢复。"""
import gc
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

import mido

from app import App, parse_clock, precise_clock_label


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

    def test_delete_imported_song_removes_file_and_its_saved_preferences(self):
        path = self.add_midi("33333333__待删除.mid")
        self.app._load_library(path)
        self.app.change_speed(1)
        self.app.change_transpose(2)
        self.app.rebuild_plan(segments=[(0, 1)])
        preference_key = self.app.song_preference_key()
        self.assertIn(preference_key, self.app.song_preferences)
        with patch("app.messagebox.askyesno", return_value=False):
            self.app.delete_song()
        self.assertTrue(path.exists())
        with patch("app.messagebox.askyesno", return_value=True):
            self.app.delete_song()
        self.assertFalse(path.exists())
        self.assertNotIn(preference_key, self.app.song_preferences)
        self.assertTrue(self.app.current_source[0] == "demo")
        self.assertEqual(str(self.app.delete_button["state"]), "disabled")

    def test_demo_song_cannot_be_deleted_and_outside_path_is_rejected(self):
        self.assertEqual(self.app.current_source[0], "demo")
        self.app.delete_song()
        self.assertIn("内置示例曲目不能删除", self.app.detail.get())
        outside = Path(self.folder.name).parent / "不能删除.mid"
        outside.write_bytes(b"MIDI")
        try:
            self.app.entries.append(("外部文件", ("file", outside)))
            self.app.library.insert("end", "  外部文件")
            self.app.library.selection_clear(0, "end")
            self.app.library.selection_set(self.app.library.size()-1)
            self.app.current_source = ("file", outside)
            self.app._update_delete_button()
            self.app.delete_song()
            self.assertTrue(outside.exists())
            self.assertIn("不在本地曲库目录", self.app.detail.get())
        finally:
            outside.unlink(missing_ok=True)

    def test_failed_save_keeps_plan_and_previous_file_with_visible_error(self):
        self.app.change_speed(1)
        path = Path(self.folder.name, "song-settings.json")
        original = path.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("模拟磁盘写入失败")):
            self.app.change_transpose(1)
        self.assertEqual(self.app.plan.notes[0].source_pitch, 61)
        self.assertEqual(path.read_bytes(), original)
        self.assertIn("曲目设置未保存", self.app.detail.get())

    def test_segments_persist_in_original_time_and_clear_only_current_song(self):
        first = [(4.25, 7.5), (0, 2)]
        self.app.rebuild_plan(segments=first)
        self.app.change_speed(3)
        self.select(1)
        self.assertEqual(self.app.segments, [])
        self.app.rebuild_plan(segments=[(2, 4)])
        self.restart()
        self.assertEqual(self.app.segments, first)
        self.assertEqual(self.app.speed.get(), "1.75")
        self.assertEqual(self.app.plan.duration, 5.25/1.75)
        self.app.rebuild_plan(segments=[])
        self.assertEqual(self.app.plan.duration, self.app.song.duration/1.75)
        self.select(1)
        self.assertEqual(self.app.segments, [(2, 4)])
        self.restart()
        self.assertEqual(self.app.segments, [])

    def test_outdated_segments_fall_back_to_full_song_with_warning(self):
        self.app.rebuild_plan(segments=[(1, 2)])
        path = Path(self.folder.name, "song-settings.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        data[self.app.song_preference_key()]["segments"] = [[1, 9999]]
        path.write_text(json.dumps(data), encoding="utf-8")
        self.restart()
        self.assertEqual(self.app.segments, [])
        self.assertTrue(self.app.plan.notes)
        self.assertIn("已保存的片段不可用", self.app.detail.get())

    def test_time_entry_accepts_minutes_or_seconds_and_rejects_bad_values(self):
        for value in ("01:23.500", "83.5", "1：23.5"):
            self.assertEqual(parse_clock(value), 83.5)
        self.assertEqual(precise_clock_label(83.5008), "01:23.500")
        for value in ("nan", "inf", "-1", "1:60", "1:2:3", "", "1.2345"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_clock(value)

    def dialog_widgets(self, dialog):
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        widgets = list(descendants(dialog))
        return ([widget for widget in widgets if isinstance(widget, ttk.Entry)],
                next(widget for widget in widgets if isinstance(widget, ttk.Treeview)),
                {str(widget["text"]): widget for widget in widgets if isinstance(widget, ttk.Button)})

    def test_dialog_add_reorder_update_remove_and_save(self):
        dialog = self.app.segments_dialog()
        self.root.update()
        entries, table, buttons = self.dialog_widgets(dialog)

        def fill(start, end):
            for entry, value in zip(entries, (start, end)):
                entry.delete(0, "end")
                entry.insert(0, value)

        fill("1", "3")
        buttons["添加到列表"].invoke()
        self.root.update()
        fill("8", "10")
        buttons["添加到列表"].invoke()
        self.root.update()
        buttons["上移"].invoke()
        self.root.update()
        self.assertEqual(table.item("0", "values")[1], "00:08.000")
        fill("9", "11")
        buttons["更新选中"].invoke()
        self.root.update()
        buttons["保存片段"].invoke()
        self.assertEqual(self.app.segments, [(9, 11), (1, 3)])
        self.assertEqual(self.app.plan.duration, 4)
        dialog = self.app.segments_dialog()
        self.root.update()
        _, table, buttons = self.dialog_widgets(dialog)
        table.selection_set("0")
        buttons["删除"].invoke()
        buttons["保存片段"].invoke()
        self.assertEqual(self.app.segments, [(1, 3)])

    def test_dialog_cancel_keeps_saved_ranges_and_invalid_input_keeps_list(self):
        self.app.rebuild_plan(segments=[(1, 3)])
        dialog = self.app.segments_dialog()
        self.root.update()
        entries, table, buttons = self.dialog_widgets(dialog)
        entries[0].delete(0, "end")
        entries[0].insert(0, "nan")
        buttons["添加到列表"].invoke()
        self.assertEqual(len(table.get_children()), 1)
        buttons["清空 / 全曲"].invoke()
        buttons["取消"].invoke()
        self.assertEqual(self.app.segments, [(1, 3)])

    def test_dialog_exports_unsaved_segments_as_json(self):
        dialog = self.app.segments_dialog()
        self.root.update()
        entries, table, buttons = self.dialog_widgets(dialog)
        for entry, value in zip(entries, ("1.25", "3.5")):
            entry.delete(0, "end")
            entry.insert(0, value)
        buttons["添加到列表"].invoke()
        destination = Path(self.folder.name, "导出演出片段.json")
        with patch("app.filedialog.asksaveasfilename", return_value=str(destination)):
            buttons["导出片段"].invoke()
        payload = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(payload["format"], "三角洲口风琴演出片段")
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["song"]["title"], "小星星")
        self.assertEqual(payload["segments"], [[1.25, 3.5]])
        self.assertFalse(payload["empty_means_full_song"])
        self.assertEqual(self.app.segments, [])
        dialog.destroy()

    def test_dialog_export_cancel_does_not_change_saved_segments(self):
        self.app.rebuild_plan(segments=[(1, 3)])
        dialog = self.app.segments_dialog()
        self.root.update()
        _, _, buttons = self.dialog_widgets(dialog)
        with patch("app.filedialog.asksaveasfilename", return_value=""):
            buttons["导出片段"].invoke()
        self.assertTrue(dialog.winfo_exists())
        self.assertEqual(self.app.segments, [(1, 3)])
        dialog.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
