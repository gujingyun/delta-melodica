"""验证统一简谱编辑的节奏精度、旋律选择和无损文字移调。"""
import tempfile
from pathlib import Path
import unittest

import mido

from cloud_score import from_song, to_song
from music import Note, Song, parse_jianpu, song_to_jianpu, transpose_jianpu


class ScoreEditingTests(unittest.TestCase):
    def test_midi_tempo_changes_repeated_notes_and_rests_round_trip(self):
        midi = mido.MidiFile(ticks_per_beat=960)
        midi.tracks.append(mido.MidiTrack([
            mido.MetaMessage("set_tempo", tempo=500001),
            mido.MetaMessage("set_tempo", tempo=733333, time=960),
        ]))
        midi.tracks.append(mido.MidiTrack([
            mido.Message("note_on", note=61, time=120),
            mido.Message("note_off", note=61, time=600),
            mido.Message("note_on", note=61, time=240),
            mido.Message("note_off", note=61, time=1),
            mido.Message("note_on", note=97, time=479),
            mido.Message("note_off", note=97, time=480),
            mido.MetaMessage("end_of_track", time=240),
        ]))
        from music import read_midi
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "变速.mid")
            midi.save(path)
            original = path.read_bytes()
            song = read_midi(path)
            edited = parse_jianpu(song_to_jianpu(song), 120, song.title, precise=True)
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual([n.pitch for n in edited.notes], [61, 61, 97])
        for before, after in zip(song.notes, edited.notes):
            self.assertAlmostEqual(before.start, after.start, places=8)
            self.assertAlmostEqual(before.end, after.end, places=8)
        self.assertAlmostEqual(song.duration, edited.duration, places=8)
        self.assertEqual(from_song(edited), from_song(to_song(from_song(edited))))

    def test_selected_piano_melody_drops_accompaniment_tail(self):
        song = Song("双手", [Note(0, 1.1, 48, 0), Note(0, 1, 72, 0), Note(1.2, 2, 74, 0),
                             Note(0, 2, 90, 1)], {0: "主旋律", 1: "其他"}, 3)
        edited = parse_jianpu(song_to_jianpu(song, 0, "piano"), 120, precise=True)
        self.assertEqual([n.pitch for n in edited.notes], [72, 74])
        self.assertAlmostEqual(edited.notes[1].start, 1.2)
        self.assertEqual(edited.duration, 3)

    def test_full_pitch_range_long_rest_and_short_notes(self):
        song = Song("边界", [Note(40, 40.0005, 0), Note(40.0005, 41, 127)], duration=81)
        edited = parse_jianpu(song_to_jianpu(song), 120, precise=True)
        self.assertEqual([n.pitch for n in edited.notes], [0, 127])
        self.assertEqual(edited.duration, 81)
        self.assertAlmostEqual(edited.notes[0].end, 40.0005)
        with self.assertRaises(ValueError):
            parse_jianpu("1:0.001")

    def test_transpose_preserves_comments_spacing_and_rhythm(self):
        text = "1  #4:1/2 | 0:2\n+7  -1:0.125 // 第 1 段\n"
        result = transpose_jianpu(text, 1)
        self.assertEqual(result, "#1  5:1/2 | 0:2\n++1  -#1:0.125 // 第 1 段\n")
        before, after = parse_jianpu(text), parse_jianpu(result)
        self.assertEqual([n.pitch+1 for n in before.notes], [n.pitch for n in after.notes])
        self.assertEqual([n.start for n in before.notes], [n.start for n in after.notes])

    def test_invalid_edits_are_rejected(self):
        for score in ("1:0", "1:1/0", "------1", "+++++7", "1:nan", "123", "0:4"):
            with self.subTest(score=score), self.assertRaises(ValueError):
                parse_jianpu(score, precise=True)
        with self.assertRaises(ValueError):
            transpose_jianpu("-----1", -1)


if __name__ == "__main__":
    unittest.main()
