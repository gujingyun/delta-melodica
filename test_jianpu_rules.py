"""用自编旋律验证谱面结构、保存还原和实际播放计划，不访问外网、不向游戏发键。"""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from cloud_score import from_song, normalize_score, to_song
from music import Mapping, compile_plan, parse_jianpu, parse_jianpu_space, song_to_jianpu, transpose_jianpu
from player import Player, release_time
from resource_search import SearchSong, download_resource
from test_jianpu_search import score_page
from test_music import FakeOutput


class JianpuRuleTests(unittest.TestCase):
    def parse(self, text, **kwargs):
        return parse_jianpu_space('/key(C4)\nbpm120\n' + text, '自编规则测试', **kwargs)[0]

    def pitches(self, text, **kwargs):
        return [n.pitch for n in self.parse(text, **kwargs).notes]

    def test_repeat_nested_adjacent_and_implicit_starts(self):
        for text, pitches in (
                ('0 |:1 2:|3 0', [60, 62, 60, 62, 64]),
                ('|:1 |:2 3:|4:|5', [60, 62, 64, 62, 64, 65] * 2 + [67]),
                ('|:1:|:2:|', [60, 60, 62, 62]),
                ('1 2:|3 4:|5', [60, 62, 60, 62, 64, 65, 64, 65, 67])):
            with self.subTest(text=text):
                self.assertEqual(self.pitches(text), pitches)
        song = self.parse('0 |:1 2:|3 0')
        self.assertEqual((song.notes[0].start, song.duration), (.5, 3.5))

    def test_first_second_endings_and_dense_bar_lines(self):
        self.assertEqual(self.pitches('|:1 2[1 3:|[2 4|]5'), [60, 62, 64, 60, 62, 65, 67])
        self.assertEqual(self.pitches('1 2[1 3:|[2 4'), [60, 62, 64, 60, 62, 65])
        self.assertEqual(self.pitches('|:1 |:2[1 3:|[2 4 5:|6'),
                         [60, 62, 64, 62, 65, 67] * 2 + [69])
        self.assertEqual(self.pitches('|123|234||1|]'), [60, 62, 64, 62, 64, 65, 60])

    def test_repeat_restores_key_tempo_and_relative_lyric_shift(self):
        song = self.parse('|:1 /key(D4)2\nbpm60\n3:|4\nL:甲"(+1key)乙"丙丁')
        self.assertEqual([n.pitch for n in song.notes], [60, 65, 67, 60, 65, 67, 68])
        self.assertEqual([n.end - n.start for n in song.notes], [.5, .5, 1, .5, .5, 1, 1])
        self.assertEqual(song.duration, 5)

    def test_first_ending_changes_do_not_leak_into_second_pass(self):
        song = self.parse('|:1[1 /key(D4)2\nbpm60\n3:|[2 4')
        self.assertEqual([n.pitch for n in song.notes], [60, 64, 66, 60, 65])
        self.assertEqual([n.end - n.start for n in song.notes], [.5, .5, 1, .5, .5])

    def test_section_key_is_local_and_clears_previous_relative_shift(self):
        song = self.parse('1 2/key(D4)1 2\nL:甲"(+1key)乙"丙丁')
        self.assertEqual([n.pitch for n in song.notes], [60, 63, 62, 64])
        song, warnings = parse_jianpu_space('1/key(D4)1', '缺省调号')
        self.assertEqual([n.pitch for n in song.notes], [60, 62])
        self.assertTrue(any('1=C4' in warning for warning in warnings))

    def test_explicit_and_parenthesized_ties_hold_once_across_bars_and_tempo(self):
        song = self.parse('1_~|1.\nbpm60\n~1 0 (2_2) 3 3')
        self.assertEqual([(n.start, n.end, n.pitch, n.legato) for n in song.notes],
                         [(0, 2, 60, True), (3, 4.5, 62, True), (4.5, 5.5, 64, False), (5.5, 6.5, 64, False)])
        plan = compile_plan(song, Mapping())
        self.assertEqual(len(plan.notes), 4)
        self.assertEqual(release_time(plan.notes[0], plan.notes[1]), 2)
        self.assertEqual(release_time(plan.notes[1], plan.notes[2]), 4.475)

    def test_slurs_keep_different_pitches_repeated_notes_and_rests(self):
        song = self.parse('(1 2 2 0 3) 4')
        self.assertEqual([n.pitch for n in song.notes], [60, 62, 62, 64, 65])
        self.assertEqual([n.legato for n in song.notes], [True, True, True, True, False])
        plan = compile_plan(song, Mapping())
        self.assertAlmostEqual(release_time(plan.notes[0], plan.notes[1]), .475)
        self.assertEqual(release_time(plan.notes[2], plan.notes[3]), 1.5)
        self.assertEqual(release_time(plan.notes[-1]), 2.925)

    def test_nested_slurs_and_lyric_index_survive_merged_notes(self):
        song = self.parse('((1 1) 2) 3 4\nL:甲乙丙"(+1key)丁"戊')
        self.assertEqual([n.pitch for n in song.notes], [60, 62, 65, 66])
        self.assertEqual([n.legato for n in song.notes], [True, True, False, False])
        self.assertEqual(song.notes[0].end, 1)

    def test_source_mode_matches_website_ignoring_structure_and_global_last_key(self):
        # 源站 je.js 对以下自编片段的基准结果；一房子数字仍会被当作音符。
        for text, pitches in (
                ('|:1 2:|3', [60, 62, 64]),
                ('(1 2 3) 1~1', [60, 62, 64, 60, 60]),
                ('1/key(D4)2', [62, 64]),
                ('|:1[1 3:|[2 4', [60, 60, 64, 62, 65])):
            with self.subTest(text=text):
                self.assertEqual(self.pitches(text, mode='source'), pitches)
        self.assertTrue(all(not n.legato for n in self.parse('(1 2)', mode='source').notes))

    def test_invalid_structure_fails_with_a_reason(self):
        for text in ('|:1', '|::|', '|: /key(D4):|', '|:1[1:|[2 2', '|:1[1 2:|', '[2 1',
                     '|:1[1 2:|[2', '|:1[1 2[1 3:|[2 4', '1~', '~1', '1~~1', '1~2', '1~0',
                     '1~1/key(D4)~1', '(1', '1)', '()', '(0 1)', '(1 0)', '(1 0 1)',
                     '|:(1:|2)', '(1|:2):|', '|:- 1:|', '0|:- 1:|', '1 D.C.', '1 /tuplet(3)234',
                     '|:' * 9 + '1' + ':|' * 9, '(' * 9 + '1' + ')' * 9):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text)

    def test_expansion_limits_apply_after_repeats_and_tie_merges(self):
        for text in ('|:' * 8 + ('1' * 150) + ':|' * 8,
                     'bpm20\n|:' * 8 + '1---' + ':|' * 8,
                     '1' + '~1' * 4000):
            with self.subTest(length=len(text)), self.assertRaises(ValueError):
                self.parse(text)

    def test_local_json_editor_transposition_and_clip_preserve_articulation(self):
        song = self.parse('|:1~1 (2 3)[1 4:|[2 /key(D4)5 0')
        data = from_song(song)
        self.assertIn('legato', data)
        self.assertEqual(from_song(to_song(data)), data)
        notation = song_to_jianpu(to_song(data))
        edited = parse_jianpu(notation, 120, song.title, precise=True)
        self.assertEqual(from_song(edited), data)
        shifted = parse_jianpu(transpose_jianpu(notation, 1), 120, precise=True)
        self.assertEqual([n.legato for n in shifted.notes], [n.legato for n in song.notes])
        self.assertEqual([n.pitch for n in shifted.notes], [n.pitch + 1 for n in song.notes])
        plan = compile_plan(song, Mapping(), speed=2, segments=[(.25, 1.75)])
        self.assertTrue(all(n.legato for n in plan.notes))
        self.assertEqual(plan.duration, .75)
        self.assertTrue(compile_plan(song, Mapping(), style='piano').notes[0].legato)

    def test_json_articulation_validation_and_unsorted_input(self):
        data = {'version': 1, 'title': '次序', 'duration': 1000,
                'notes': [[500, 1000, 62, 0], [0, 500, 60, 0]], 'legato': [0]}
        self.assertEqual([n.legato for n in to_song(data).notes], [False, True])
        self.assertEqual(from_song(to_song(data))['legato'], [1])
        self.assertNotIn('legato', normalize_score(data))
        for invalid in (None, '0', [True], [-1], [2], [0, 0, 0]):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                to_song({**data, 'legato': invalid})

    def test_internal_slurs_hold_notes_without_merging_repeated_attacks(self):
        song = parse_jianpu('(1 1 2) 0 (3:2)', 120)
        self.assertEqual([n.pitch for n in song.notes], [60, 60, 62, 64])
        self.assertTrue(all(n.legato for n in song.notes))
        for text in ('(1', '1)', '()', '(' * 9 + '1' + ')' * 9):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_jianpu(text)

    def test_scheduler_retriggers_repeats_but_holds_ties_and_releases_on_stop(self):
        plan = compile_plan(self.parse('|:1~1 (2 2 3):|'), Mapping())
        for stop_at in (None, .6):
            clock, played, released, notifications = [100.0], [], [], []
            player = Player(lambda *event: notifications.append(event))

            class RecordedOutput(FakeOutput):
                def begin(self, fingering):
                    played.append((clock[0] - 100, fingering.pitch))
                    super().begin(fingering)

                def release(self):
                    if self.held:
                        released.append(clock[0] - 100)
                    super().release()

            output = RecordedOutput()

            def wait(deadline, output=None):
                clock[0] = deadline
                if stop_at is not None and clock[0] - 100 >= stop_at:
                    player.stop()

            with patch('player.time.perf_counter', side_effect=lambda: clock[0]), patch.object(player, '_wait', side_effect=wait):
                player._run(plan, lambda: output, 0, .85)
            self.assertTrue(output.closed)
            self.assertFalse(output.held)
            self.assertIsNone(notifications[-1][2][1])
            if stop_at is None:
                self.assertEqual([pitch for _, pitch in played], [60, 62, 62, 64] * 2)
                self.assertAlmostEqual(released[0], .975)
                self.assertAlmostEqual(released[1], 1.475)
                self.assertAlmostEqual(released[-1], 5)
            else:
                self.assertEqual(len(played), 1)
                self.assertAlmostEqual(released[0], .6, delta=.009)

    def test_import_modes_are_separate_editable_files(self):
        resource = SearchSong('jianpu', '自编演奏规则', 'https://jianpu.space/songList/42')
        source = '/key(C4)\nbpm120\n|:1~1 (2 3)[1 4:|[2 /key(D4)5'
        with tempfile.TemporaryDirectory() as folder, patch('resource_search._fetch_html', return_value=score_page(source)):
            paths = [download_resource(resource, Path(folder), Mapping(), threading.Event(), jianpu_mode=mode)
                     for mode in ('score', 'source')]
            self.assertNotEqual(*paths)
            for path, mode in zip(paths, ('score', 'source')):
                data = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(data['jianpu_source']['mode'], mode)
                expected = parse_jianpu_space(source, resource.title, mode=mode)[0]
                self.assertEqual(from_song(to_song(data)), from_song(expected))
                self.assertEqual(from_song(parse_jianpu(data['editor']['score'], 120, resource.title, precise=True)),
                                 from_song(expected))


if __name__ == '__main__':
    unittest.main(verbosity=2)
