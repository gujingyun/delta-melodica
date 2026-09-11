"""验证节奏、八键映射、变速 MIDI 和停止时的输入清理。"""
import ctypes
import io
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import mido
from music import Mapping, Note, Song, compile_plan, fingerings, monophonic, parse_jianpu, read_midi, piano_melody, recommend_track
from player import Player, release_time
from win_input import INPUT, WindowsOutput, keyboard_event, target_matches, permission_problem, process_elevated


class MusicTests(unittest.TestCase):
    def test_eight_keys_and_comma(self):
        lookup = fingerings(Mapping())
        for pitch, key in zip((60, 62, 64, 65, 67, 69, 71, 72), "zxcvbnm,"):
            self.assertEqual((lookup[pitch].key, lookup[pitch].buttons), (key, ()))
        self.assertEqual(lookup[48].buttons, ("left",))
        self.assertEqual(lookup[84].key, ",")
        self.assertEqual(lookup[84].buttons, ("right",))
        self.assertEqual(lookup[61].buttons, ("middle",))
        self.assertEqual(set(lookup[49].buttons), {"left", "middle"})

    def test_flat_modifier_and_bad_keys(self):
        self.assertEqual(fingerings(Mapping(half=-1))[61].key, "x")
        for keys in ("zxcvbnm", "zzcvbnm,", "zxcvbnm，", "zxcvbnm "):
            with self.assertRaises(ValueError):
                fingerings(Mapping(keys=keys))

    def test_jianpu_timing_accidentals_and_trailing_rest(self):
        song = parse_jianpu("1 #2:1/2 b3:0.5 | +1:2 -5 0:2", 120)
        self.assertEqual([n.pitch for n in song.notes], [60, 63, 63, 72, 55])
        self.assertEqual([n.start for n in song.notes], [0, 0.5, 0.75, 1, 2])
        self.assertAlmostEqual(song.duration, 3.5)
        for text in ("123", "8", "1:0", "1:1/0", "#0", "0"):
            with self.assertRaises(ValueError):
                parse_jianpu(text)

    def test_monophonic_resumes_lower_note_without_overlap(self):
        notes = monophonic([Note(0, 3, 60), Note(1, 2, 72), Note(2, 3, 67)])
        self.assertEqual([(n.start, n.end, n.pitch) for n in notes], [(0, 1, 60), (1, 2, 72), (2, 3, 67)])

    def test_repeated_same_pitch_is_retriggered(self):
        self.assertEqual(len(monophonic([Note(0, 1, 60), Note(1, 2, 60)])), 2)
        self.assertEqual(len(monophonic([Note(0, 4, 72), Note(1, 2, 60)])), 1)

    def test_speed_transpose_octave_fold_and_track(self):
        song = Song("测试", [Note(0, 2, 24, 1), Note(0, 1, 90, 2)], {1: "低", 2: "高"})
        plan = compile_plan(song, Mapping(), track=1, speed=2, transpose=1)
        self.assertEqual(plan.folded, 1)
        self.assertEqual(plan.notes[0].fingering.pitch, 49)
        self.assertEqual(plan.notes[0].end, 1)
        self.assertEqual(plan.duration, 1)

    def test_midi_global_tempo_and_drums(self):
        midi = mido.MidiFile(ticks_per_beat=480)
        tempo = mido.MidiTrack([
            mido.MetaMessage("set_tempo", tempo=500000, time=0),
            mido.MetaMessage("set_tempo", tempo=1000000, time=480)])
        melody = mido.MidiTrack([
            mido.MetaMessage("track_name", name="Melody", time=0),
            mido.Message("note_on", note=60, velocity=80, time=0),
            mido.Message("note_off", note=60, time=960),
            mido.Message("note_on", note=72, velocity=90, time=0),
            mido.Message("note_on", note=72, velocity=0, time=480)])
        drums = mido.MidiTrack([mido.Message("note_on", channel=9, note=40), mido.Message("note_off", channel=9, note=40, time=480)])
        midi.tracks.extend([tempo, melody, drums])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "tempo.mid")
            midi.save(path)
            song = read_midi(path)
        self.assertEqual(song.tracks, {1: "Melody"})
        self.assertEqual(len(song.notes), 2)
        self.assertAlmostEqual(song.notes[0].end, 1.5)
        self.assertAlmostEqual(song.notes[1].end, 2.5)

    def test_midi_type2_rejected(self):
        midi = mido.MidiFile(type=2)
        midi.tracks.append(mido.MidiTrack())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "type2.mid")
            midi.save(path)
            with self.assertRaises(ValueError):
                read_midi(path)


class PianoTests(unittest.TestCase):
    def test_accompaniment_tail_is_not_restarted(self):
        notes = [Note(0, 1.05, 48), Note(0, 1, 72), Note(1.1, 2, 74)]
        self.assertEqual([n.pitch for n in monophonic(notes)], [72, 48, 74])
        self.assertEqual([n.pitch for n in piano_melody(notes)], [72, 74])

    def test_staggered_chord_keeps_high_note_at_its_original_onset(self):
        notes = [Note(0, 0.5, 60), Note(0.028, 0.52, 64), Note(0.055, 0.54, 72)]
        self.assertEqual(piano_melody(notes), [notes[2]])

    def test_sustained_melody_ignores_new_bass_but_allows_descending_legato(self):
        notes = [Note(0, 1, 76), Note(0.4, 0.7, 48), Note(0.95, 1.5, 74)]
        self.assertEqual(piano_melody(notes), [Note(0, 0.95, 76), notes[2]])

    def test_real_fast_notes_and_repeated_notes_are_kept(self):
        notes = [Note(0, 0.04, 72), Note(0.04, 0.08, 74), Note(0.08, 0.12, 74)]
        self.assertEqual(piano_melody(notes), notes)
        repeated = [Note(0, 0.5, 72), Note(0.5, 1, 72)]
        self.assertEqual(piano_melody(repeated), repeated)

    def test_bridges_short_gaps_without_erasing_phrase_rests(self):
        song = Song("间隙测试", [Note(0, 0.5, 60), Note(0.56, 1, 62), Note(1.3, 1.8, 64)])
        plan = compile_plan(song, Mapping(), style="piano", speed=2)
        self.assertEqual(plan.bridged, 1)
        self.assertEqual([(n.start, n.end) for n in plan.notes], [(0, 0.28), (0.28, 0.5), (0.65, 0.9)])
        self.assertEqual(plan.duration, 0.9)

    def test_auto_track_chooses_high_voice_and_respects_manual_selection(self):
        song = Song("双手钢琴", [Note(0, 1, 48, 2), Note(0, 1, 72, 1)], {1: "Track 1", 2: "Track 2"})
        self.assertEqual(recommend_track(song), 1)
        self.assertEqual(compile_plan(song, Mapping(), track="auto", style="piano").notes[0].source_pitch, 72)
        self.assertEqual(compile_plan(song, Mapping(), track=2, style="piano").notes[0].source_pitch, 48)
        song.tracks[2] = "Vocal"
        self.assertEqual(recommend_track(song), 2)

    def test_long_notes_use_fixed_retrigger_gap_and_final_note_is_complete(self):
        plan = compile_plan(parse_jianpu("1:4 1:4 0:2 2:4", 120), Mapping(), style="piano")
        a, b, c = plan.notes
        self.assertAlmostEqual(release_time(a, b, legato=True), 1.975)
        self.assertEqual(release_time(b, c, legato=True), 4)
        self.assertEqual(release_time(c, legato=True), 7)
        self.assertEqual(release_time(a, b, gate=0.85), 1.7)

    def test_actual_scheduler_retriggers_and_releases_legato_modifiers(self):
        plan = compile_plan(parse_jianpu("-1:2 #1:2 #1:2", 120), Mapping(), style="piano")
        clock, sent = [100.0], []
        class RecordedOutput(FakeOutput):
            def begin(self, fingering):
                sent.append(("on", clock[0], fingering.buttons))
                super().begin(fingering)

            def release(self):
                if self.held:
                    sent.append(("off", clock[0]))
                super().release()

        output = RecordedOutput()
        player = Player(lambda *_: None)
        player._wait = lambda deadline, output=None: clock.__setitem__(0, deadline)
        with patch("player.time.perf_counter", side_effect=lambda: clock[0]):
            player._run(plan, lambda: output, 0, 0.5)
        self.assertEqual([event[0] for event in sent], ["on", "off", "on", "off", "on", "off"])
        self.assertEqual([event[2] for event in sent if event[0] == "on"], [("left",), ("middle",), ("middle",)])
        for event, expected in zip(sent, [100, 100.975, 101, 101.975, 102, 103]):
            self.assertAlmostEqual(event[1], expected)
        self.assertTrue(output.closed)


class InputTests(unittest.TestCase):
    def test_elevated_game_requires_matching_permission(self):
        self.assertIn("管理员", permission_problem(123, query=lambda pid=None: pid == 123))
        self.assertIsNone(permission_problem(123, query=lambda pid=None: True))
        self.assertIsNone(permission_problem(123, query=lambda pid=None: False))

    def test_unknown_permission_is_not_reported_as_confirmed_mismatch(self):
        self.assertIsNone(permission_problem(123, query=lambda pid=None: None))
        self.assertIsNone(permission_problem(123, query=lambda pid=None: False if pid is None else None))

    def test_own_permission_query_succeeds(self):
        self.assertIsInstance(process_elevated(), bool)

    def test_windows_structure_and_comma_scancode(self):
        self.assertEqual(ctypes.sizeof(INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
        self.assertEqual(keyboard_event(",", True).ki.wScan, 0x33)
        self.assertEqual(keyboard_event(",", False).ki.dwFlags, 0x000A)

    def test_target_filter(self):
        self.assertTrue(target_matches((123, os.getpid()+1, "Delta Force"), "三角洲|Delta Force"))
        self.assertFalse(target_matches((123, os.getpid(), "Delta Force"), "Delta"))
        self.assertFalse(target_matches((123, os.getpid()+1, "Notepad"), "Delta"))
        self.assertFalse(target_matches((123, os.getpid()+1, "Delta Force"), "|"))

    def test_release_key_before_modifiers(self):
        sent = []
        target = (123, 456, "测试窗口")
        output = WindowsOutput(target, send=lambda events: sent.extend(events), get_foreground=lambda: target)
        output.begin(fingerings(Mapping())[49])
        output.close()
        self.assertEqual([e.type for e in sent], [0, 0, 1, 1, 0, 0])
        self.assertEqual(sent[3].ki.dwFlags, 0x000A)
        self.assertEqual([sent[4].mi.dwFlags, sent[5].mi.dwFlags], [0x40, 0x04])
        self.assertEqual(output.held, [])

    def test_partial_failure_releases_possible_pressed_key(self):
        sent = []
        target = (123, 456, "测试窗口")
        def send(events):
            sent.extend(events)
            if len(sent) == 2:
                raise OSError("模拟部分失败")
        output = WindowsOutput(target, send=send, get_foreground=lambda: target)
        with self.assertRaises(OSError):
            output.begin(fingerings(Mapping())[49])
        output.close()
        self.assertEqual(output.held, [])
        self.assertEqual(len(sent), 4)

    def test_focus_loss_blocks_further_note_down(self):
        output = WindowsOutput((1, 2, "游戏"), send=lambda _: self.fail("不应发送"), get_foreground=lambda: (3, 4, "其他窗口"))
        with self.assertRaises(RuntimeError):
            output.begin(fingerings(Mapping())[60])


class FakeOutput:
    def __init__(self):
        self.started = threading.Event()
        self.closed = False
        self.held = False
        self.focus = True

    def check(self):
        if not self.focus:
            raise RuntimeError("焦点切换")

    def begin(self, fingering):
        self.held = True
        self.started.set()

    def release(self):
        self.held = False

    def close(self):
        self.release()
        self.closed = True


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.player = Player(lambda kind, value: self.events.append((kind, value)))
        self.output = FakeOutput()
        self.plan = compile_plan(parse_jianpu("1:8", 120), Mapping())

    def tearDown(self):
        self.player.close()

    def test_cancel_countdown_never_opens_output(self):
        self.player.start(self.plan, lambda: self.fail("倒计时取消不应打开输出"), countdown=2)
        self.player.stop()
        self.player.thread.join(1)
        self.assertFalse(self.player.active)
        self.assertEqual(self.events[-1], ("done", ("已停止", None)))

    def test_stop_releases_held_note_promptly(self):
        self.player.start(self.plan, lambda: self.output)
        self.assertTrue(self.output.started.wait(1))
        before = time.perf_counter()
        self.player.stop()
        self.player.thread.join(0.5)
        self.assertLess(time.perf_counter()-before, 0.5)
        self.assertTrue(self.output.closed)
        self.assertFalse(self.output.held)

    def test_focus_loss_releases_held_note(self):
        self.player.start(self.plan, lambda: self.output)
        self.assertTrue(self.output.started.wait(1))
        self.output.focus = False
        self.player.thread.join(0.5)
        self.assertFalse(self.player.active)
        self.assertFalse(self.output.held)
        self.assertIn("焦点切换", self.events[-1][1][1])

    def test_completed_song_and_repeat(self):
        short = compile_plan(parse_jianpu("1:1/8 1:1/8 0:1/8", 300), Mapping())
        for _ in range(2):
            self.player.start(short, FakeOutput)
            self.player.thread.join(1)
            self.assertFalse(self.player.active)
            self.assertEqual(self.events[-1], ("done", ("演奏完成", None)))

    def test_output_error_still_closes(self):
        def failure(fingering):
            self.output.held = True
            raise OSError("发送失败")
        self.output.begin = failure
        self.player.start(self.plan, lambda: self.output)
        self.player.thread.join(1)
        self.assertTrue(self.output.closed)
        self.assertFalse(self.output.held)
        self.assertIn("发送失败", self.events[-1][1][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
