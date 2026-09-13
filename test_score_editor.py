"""使用独立曲库和本机窗口验证编辑、另存、试听释放与界面布局。"""
import gc
import json
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

import mido

from account_client import atomic_json, read_local_score
from app import App
from cloud_score import from_song, normalize_score
from test_music import FakeOutput


class ScoreEditorTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.scaling = self.root.tk.call("tk", "scaling")
        self.app = App(self.root, self.folder.name, smoke=True)
        self.app.overlay.enabled = False
        self.root.update()

    def tearDown(self):
        if not self.app.closing:
            self.root.tk.call("tk", "scaling", self.scaling)
        self.app.close()
        self.app = self.root = None
        gc.collect()
        self.folder.cleanup()

    def editor(self):
        self.app.edit_song()
        self.root.update()
        self.assertIsNotNone(self.app.score_editor)
        return self.app.score_editor

    def replace(self, editor, score):
        editor.text.delete("1.0", "end")
        editor.text.insert("1.0", score)
        self.root.update()

    def pump(self, condition, timeout=2):
        deadline = time.monotonic()+timeout
        while not condition() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(condition())

    def test_demo_edit_save_reopen_and_cloud_compatibility(self):
        source, original = self.app.current_source, self.app.song
        editor = self.editor()
        self.replace(editor, "1 #4:1/2 0:2 +1:2 // 我的修改")
        editor.name.set("练习曲 · 修改版")
        editor.bpm.set("90")
        editor.style.set("钢琴适配 · 连奏")
        expected = from_song(editor.parsed())
        editor.save_button.invoke()
        path = editor.saved_path
        self.assertIsNone(self.app.score_editor)
        self.assertEqual(self.app.plan.style, "piano")
        self.assertEqual(self.app.speed.get(), "1.00")
        self.assertEqual(from_song(self.app.song), expected)
        self.assertEqual(read_local_score(path), expected)
        self.assertEqual(self.app.current_source, ("file", path))
        self.assertTrue(self.app.library.get(self.app.library.curselection()[0]).startswith("[简谱]"))
        self.assertIn((original.title, source), self.app.entries)
        reopened = self.editor()
        self.assertEqual(reopened.bpm.get(), "90.0")
        self.assertIn("// 我的修改", reopened.text.get("1.0", "end"))
        self.assertEqual(reopened.name.get(), "练习曲 · 修改版")
        self.assertEqual(reopened.style.get(), "钢琴适配 · 连奏")

    def test_midi_edit_uses_selected_track_and_full_original_time(self):
        midi = mido.MidiFile()
        for pitch in (60, 72):
            midi.tracks.append(mido.MidiTrack([
                mido.Message("note_on", note=pitch, time=480),
                mido.Message("note_off", note=pitch, time=480),
                mido.MetaMessage("end_of_track", time=480),
            ]))
        path = self.app.library_dir / "sample__多音轨.mid"
        midi.save(path)
        original = path.read_bytes()
        self.app._load_library(path)
        self.app.track_combo.current(self.app.track_ids.index(0))
        self.app.speed.set("2.00")
        self.app.transpose.set("5")
        self.app.rebuild_plan(segments=[(0.6, 0.8)])
        editor = self.editor()
        song = editor.parsed()
        self.assertEqual([n.pitch for n in song.notes], [60])
        self.assertEqual((song.notes[0].start, song.notes[0].end, song.duration), (0.5, 1, 1.5))
        editor.save()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.app.segments, [])
        self.assertEqual((self.app.speed.get(), self.app.transpose.get()), ("1.00", "0"))
        self.assertEqual(self.app.plan.style, "piano")

    def test_legacy_jianpu_keeps_bpm_and_source_file(self):
        path = self.app.library_dir / "legacy__原曲.json"
        atomic_json(path, {"title": "原曲", "bpm": 85, "score": "1 0:2 +1:1/2"})
        original = path.read_bytes()
        self.app._load_library(path)
        editor = self.editor()
        self.assertEqual(editor.bpm.get(), "85")
        self.assertEqual(editor.text.get("1.0", "end-1c"), "1 0:2 +1:1/2")
        editor.save()
        self.assertEqual(path.read_bytes(), original)
        self.assertNotEqual(editor.saved_path, path)

    def test_transpose_is_one_undo_step_and_redo_restores_it(self):
        editor = self.editor()
        original = editor.text.get("1.0", "end-1c")
        editor.shift.set("1")
        editor.transpose()
        transposed = editor.text.get("1.0", "end-1c")
        self.assertNotEqual(original, transposed)
        editor.history("undo")
        self.assertEqual(editor.text.get("1.0", "end-1c"), original)
        editor.history("redo")
        self.assertEqual(editor.text.get("1.0", "end-1c"), transposed)

    def test_invalid_save_and_disk_failure_keep_editor_and_library(self):
        editor = self.editor()
        files = list(self.app.library_dir.iterdir())
        self.replace(editor, "1:0")
        with patch("score_editor.messagebox.showerror") as error:
            editor.save()
            error.assert_called_once()
        self.assertIs(self.app.score_editor, editor)
        self.assertEqual(list(self.app.library_dir.iterdir()), files)
        self.replace(editor, "1 2")
        with patch("score_editor.atomic_json", side_effect=OSError("模拟磁盘写入失败")), patch("score_editor.messagebox.showerror"):
            editor.save()
        self.assertIs(self.app.score_editor, editor)
        self.assertEqual(list(self.app.library_dir.iterdir()), files)

    def test_close_cancel_keeps_edits_and_confirm_discards_copy(self):
        editor = self.editor()
        self.replace(editor, "1 2 3")
        with patch("score_editor.messagebox.askyesno", return_value=False):
            editor.close()
        self.assertFalse(editor.closed)
        with patch("score_editor.messagebox.askyesno", return_value=True):
            editor.close()
        self.assertTrue(editor.closed)
        self.assertFalse(list(self.app.library_dir.iterdir()))

    def test_selection_preview_f9_releases_output_and_blocks_game_start(self):
        editor = self.editor()
        self.replace(editor, "1:8 2:8")
        editor.text.tag_add("sel", "1.4", "1.7")
        output = FakeOutput()
        with patch("score_editor.PreviewOutput", return_value=output), patch("app.WindowsOutput") as game:
            editor.preview(True)
            self.assertTrue(output.started.wait(1))
            self.assertEqual(editor.player._plan.notes[0].source_pitch, 62)
            self.assertEqual(len(editor.player._plan.notes), 1)
            self.app.play(False)
            game.assert_not_called()
            self.app.stop("F9")
            self.pump(lambda: not editor.player.active)
        self.assertTrue(output.closed)
        self.assertFalse(output.held)
        self.assertFalse(self.app.player.active)

    def test_editing_and_app_exit_stop_preview_and_release_output(self):
        editor = self.editor()
        self.replace(editor, "1:16")
        for action in (lambda: self.replace(editor, "2:16"), self.app.close):
            output = FakeOutput()
            with patch("score_editor.PreviewOutput", return_value=output):
                editor.preview()
                self.assertTrue(output.started.wait(1))
                action()
                editor.player.thread.join(1)
            self.assertFalse(editor.player.active)
            self.assertTrue(output.closed)
            self.assertFalse(output.held)

    def test_metadata_mismatch_uses_actual_notes(self):
        path = self.app.library_dir / "cloud__云端.json"
        data = from_song(self.app.song)
        data["editor"] = {"score": "7:8", "bpm": 100, "style": "piano"}
        atomic_json(path, data)
        self.app._load_library(path)
        editor = self.editor()
        self.assertEqual(from_song(editor.parsed())["notes"], normalize_score(data)["notes"])

    def test_footer_and_text_remain_visible_at_common_scaling(self):
        for scaling in (4/3, 2):
            self.root.tk.call("tk", "scaling", scaling)
            editor = self.editor()
            for geometry in ("820x650", "920x710"):
                editor.dialog.geometry(geometry)
                self.root.update()
                with self.subTest(scaling=scaling, geometry=geometry):
                    self.assertTrue(editor.save_button.winfo_ismapped())
                    self.assertGreaterEqual(editor.save_button.winfo_height(), editor.save_button.winfo_reqheight())
                    self.assertLessEqual(editor.save_button.winfo_rooty()+editor.save_button.winfo_height(),
                                         editor.dialog.winfo_rooty()+editor.dialog.winfo_height())
                    self.assertGreater(editor.text.winfo_height(), 70)
                    self.assertLessEqual(editor.text.winfo_rooty()+editor.text.winfo_height(), editor.save_button.winfo_rooty())
            editor.close(force=True)


if __name__ == "__main__":
    unittest.main()
