"""验证原谱编辑、音符定位和选段上下文；使用自编谱和隔离曲库。"""
import json
import unittest
from unittest.mock import patch, PropertyMock

from account_client import atomic_json
from cloud_score import from_song
from jianpu_editor import replace_header, score_glyphs, score_metadata, transpose_source
from music import parse_jianpu_space, select_jianpu_space, song_to_jianpu
from test_score_editor import ScoreEditorTests


SOURCE = '/key(A3)\nｂｐｍ108\n1_2_3-|1\nL:甲乙丙"(+1key)丁"\n/key(C4)\nbpm60\n|:(2 3)[1 4:|[2 5'


class SourceNotationTests(unittest.TestCase):
    def test_glyph_positions_match_original_fullwidth_and_lyrics(self):
        text = '  /key(A3)\r\nｂｐｍ１０８\r\n  １_２,３\nL:"前奏😊"*甲'
        glyphs = score_glyphs(text)
        self.assertEqual(score_metadata(text), ('A3', 108))
        notes = [g for g in glyphs if g.kind == 'note']
        self.assertEqual([text[g.start:g.end] for g in notes], ['１_', '２,', '３'])
        self.assertEqual([g.lyric for g in notes], ['前奏😊', '', '甲'])

    def test_headers_preserve_later_tempo_keys_and_lyrics(self):
        changed = replace_header(SOURCE, 'key', 'Bb3')
        changed = replace_header(changed, 'tempo', 90)
        self.assertTrue(changed.startswith('/key(Bb3)\nbpm90\n'))
        self.assertIn('/key(C4)\nbpm60', changed)
        self.assertIn('L:甲乙丙"(+1key)丁"', changed)
        self.assertEqual(replace_header('1 2', 'tempo', 108), 'bpm108\n1 2')

    def test_transposition_changes_keys_without_rewriting_rhythm_or_lyrics(self):
        for source in (SOURCE, '1 2 /key(D4)3', '1 2 3', '/key(G)1 2'):
            for mode in ('score', 'source'):
                with self.subTest(source=source[:20], mode=mode):
                    before = parse_jianpu_space(source, '原谱', mode=mode)[0]
                    result = transpose_source(source, 1, mode)
                    after = parse_jianpu_space(result, '原谱', mode=mode)[0]
                    self.assertEqual([n.pitch+1 for n in before.notes], [n.pitch for n in after.notes])
                    self.assertEqual([n.start for n in before.notes], [n.start for n in after.notes])
                    self.assertEqual([n.end for n in before.notes], [n.end for n in after.notes])
                    self.assertIn(source[source.index('1'):].split('/key')[0], result)
        with self.assertRaises(ValueError):
            transpose_source('/key(C9)7', 12, 'score')

    def test_selection_keeps_lyric_shift_tempo_and_repeat_occurrences(self):
        start = SOURCE.index('|1') + 1
        song = select_jianpu_space(SOURCE, '片段', start, start+1)
        self.assertEqual([n.pitch for n in song.notes], [58])
        self.assertAlmostEqual(song.duration, 60/108)
        start = SOURCE.index('(2')+1
        song = select_jianpu_space(SOURCE, '片段', start, start+3)
        self.assertEqual([n.pitch for n in song.notes], [62, 64, 62, 64])
        self.assertEqual(song.duration, 4)
        self.assertTrue(all(n.legato for n in song.notes))

    def test_selection_clips_holds_and_rests_without_retriggering(self):
        text = '/key(D4)\nbpm60\n1~1| - 0 2'
        start = text.index('~1') + 1
        song = select_jianpu_space(text, '片段', start, text.index(' 2'))
        self.assertEqual([(n.start, n.end, n.pitch, n.legato) for n in song.notes], [(0, 2, 62, True)])
        self.assertEqual(song.duration, 3)
        for a, b in ((0, 5), (text.index(' 0')+1, text.index(' 0')+2)):
            with self.assertRaises(ValueError):
                select_jianpu_space(text, '空片段', a, b)
        with self.assertRaisesRegex(ValueError, '完整音符'):
            select_jianpu_space('1_2_', '半个符号', 0, 1)

    def test_selected_trace_rebases_repeated_ties_rests_and_tempo_changes(self):
        text = '/key(C4)\nbpm60\n7 |: 1~1 - 0 [1 2 :| [2 3\n/key(D4)\nbpm120\n4_5_'
        trace = []
        start, end = text.index('1~'), text.index('[1')
        song = select_jianpu_space(text, '选段', start, end, trace=trace)
        self.assertEqual([text[left:right] for left, right, _, _ in trace], ['1', '1', '-', '0']*2)
        self.assertEqual([(a, b) for _, _, a, b in trace], [(i, i+1) for i in range(8)])
        self.assertEqual(song.duration, 8)
        self.assertEqual([(n.start, n.end) for n in song.notes], [(0, 3), (4, 7)])
        tail = []
        selected = select_jianpu_space(text, '尾段', text.index('4_'), len(text), trace=tail)
        self.assertEqual([n.pitch for n in selected.notes], [67, 69])
        self.assertEqual([(a, b) for _, _, a, b in tail], [(0, .25), (.25, .5)])


class SourceEditorTests(ScoreEditorTests):
    # 复用窗口、隔离目录与事件泵；这里只收集本类新增的测试。
    def source_editor(self, source=SOURCE, mode='score'):
        song = parse_jianpu_space(source, '原谱测试', mode=mode)[0]
        data = from_song(song)
        data['jianpu_source'] = {'text': source, 'mode': mode, 'url': 'https://jianpu.space/songList/42'}
        # 模拟旧版导入的文件，带有难读的精确音符文字。
        data['editor'] = {'score': song_to_jianpu(song), 'bpm': 120, 'style': 'original'}
        path = self.app.library_dir / 'original__原谱测试.json'
        atomic_json(path, data)
        self.app._load_library(path)
        return self.editor(), data, path

    def test_legacy_import_recovers_readable_source_and_saves_reopens_it(self):
        editor, data, path = self.source_editor()
        self.assertTrue(editor.is_source)
        self.assertEqual(editor.text.get('1.0', 'end-1c'), SOURCE)
        self.assertEqual(editor.bpm.get(), '108')
        self.assertEqual(from_song(editor.parsed()), {**from_song(self.app.song), 'title': editor.name.get()})
        original = path.read_bytes()
        self.replace(editor, SOURCE.replace('1_2_', '1_3_', 1))
        expected = from_song(editor.parsed())
        editor.save()
        saved = json.loads(editor.saved_path.read_text(encoding='utf-8'))
        self.assertEqual(saved['editor']['format'], 'jianpu_space')
        self.assertEqual(saved['editor']['mode'], 'score')
        self.assertEqual(saved['editor']['bpm'], 108)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(from_song(self.app.song), expected)
        reopened = self.editor()
        self.assertTrue(reopened.is_source)
        self.assertEqual(reopened.text.get('1.0', 'end-1c'), saved['editor']['score'])
        self.assertEqual(from_song(reopened.parsed()), expected)

    def test_preview_click_range_and_toolbar_modify_complete_tokens_with_undo(self):
        editor, _, _ = self.source_editor('/key(A3)\nbpm108\n1_2=3-\nL:"前奏😊"甲乙')
        glyph = next(g for g in editor.score_preview.glyphs if g.kind == 'note')
        editor.select_range(glyph.start, glyph.end)
        self.assertEqual(editor.text.get('sel.first', 'sel.last'), '1_')
        editor.symbol_buttons["'"].invoke()
        self.root.update()
        self.assertIn("1'_2=3-", editor.text.get('1.0', 'end-1c'))
        editor.history('undo')
        self.assertIn('1_2=3-', editor.text.get('1.0', 'end-1c'))
        text = 'L:"😊"\n/key(C4)\n1_ 2'
        self.replace(editor, text)
        start = text.index('1_')
        editor.select_range(start, start+2)
        self.assertEqual(editor.text.get('sel.first', 'sel.last'), '1_')

    def test_selected_preview_uses_full_context_and_stops_on_edit(self):
        from test_music import FakeOutput
        editor, _, _ = self.source_editor()
        start = SOURCE.index('|1') + 1
        editor.select_range(start, start+1)
        output = FakeOutput()
        with patch('score_editor.PreviewOutput', return_value=output), patch('app.WindowsOutput') as game:
            editor.preview(True)
            self.assertTrue(output.started.wait(1))
            self.assertEqual(editor.player._plan.notes[0].source_pitch, 58)
            self.replace(editor, SOURCE.replace('bpm60', 'bpm80'))
            editor.player.thread.join(1)
            self.assertFalse(output.held)
            game.assert_not_called()

    def test_source_mode_persists_without_changing_website_playback(self):
        editor, _, _ = self.source_editor('/key(C4)\nbpm108\n|:(1 2):|/key(D4)3', mode='source')
        before = from_song(editor.parsed())
        editor.save()
        reopened = self.editor()
        self.assertEqual(reopened.source_mode, 'source')
        self.assertEqual(from_song(reopened.parsed()), before)

    def test_header_dialogs_change_only_the_requested_first_marker(self):
        editor, _, _ = self.source_editor()
        with patch('score_editor.simpledialog.askfloat', return_value=90):
            editor.edit_header('tempo')
        with patch('score_editor.simpledialog.askstring', return_value='Bb3'):
            editor.edit_header('key')
        editor.validate()
        text = editor.text.get('1.0', 'end-1c')
        self.assertEqual(score_metadata(text), ('Bb3', 90))
        self.assertIn('/key(C4)\nbpm60', text)
        self.assertEqual(editor.bpm.get(), '90')

    def test_mismatched_original_is_not_used_to_overwrite_saved_music(self):
        editor, _, path = self.source_editor()
        editor.close(force=True)
        data = json.loads(path.read_text(encoding='utf-8'))
        data['jianpu_source']['text'] = '/key(C4)\nbpm120\n1 2'
        atomic_json(path, data)
        self.app._load_library(path)
        reopened = self.editor()
        self.assertFalse(reopened.is_source)
        self.assertEqual(from_song(reopened.parsed()), {**from_song(self.app.song), 'title': reopened.name.get()})

    def test_invalid_edit_clears_stale_preview_and_prevents_save(self):
        editor, _, _ = self.source_editor()
        self.replace(editor, '/key(C4)\n1 & 2')
        editor.validate()
        self.assertEqual(editor.score_preview.glyphs, [])
        self.assertTrue(editor.text.tag_ranges('error'))
        with patch('score_editor.messagebox.showerror') as error:
            editor.save()
        error.assert_called_once()
        self.assertIsNone(editor.saved_path)

    def test_source_editor_layout_keeps_controls_and_both_panes_visible(self):
        for scaling in (4/3, 2):
            self.root.tk.call('tk', 'scaling', scaling)
            editor, _, _ = self.source_editor()
            for geometry in ('1180x800', '960x720'):
                editor.dialog.geometry(geometry)
                self.root.update()
                self.assertGreater(editor.text.winfo_height(), 120)
                self.assertGreater(editor.score_preview.canvas.winfo_width(), 250)
                for button in (*editor.symbol_buttons.values(), editor.save_button):
                    self.assertTrue(button.winfo_ismapped())
                    self.assertLessEqual(button.winfo_rootx()+button.winfo_width(),
                                         editor.dialog.winfo_rootx()+editor.dialog.winfo_width())
                    self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),
                                         editor.dialog.winfo_rooty()+editor.dialog.winfo_height())
            editor.close(force=True)

    def test_editor_maximizes_and_restores_with_modal_grab(self):
        for source in (False, True):
            editor = self.source_editor()[0] if source else self.editor()
            self.assertFalse(editor.dialog.transient())
            normal = (editor.dialog.winfo_width(), editor.dialog.winfo_height())
            editor.dialog.state('zoomed')
            self.root.update()
            self.assertEqual(editor.dialog.state(), 'zoomed')
            self.assertGreater(editor.dialog.winfo_width(), normal[0])
            self.assertEqual(editor.dialog.grab_current(), editor.dialog)
            editor.dialog.state('normal')
            self.root.update()
            self.assertEqual((editor.dialog.winfo_width(), editor.dialog.winfo_height()), normal)
            editor.close(force=True)

    def test_playing_mark_tracks_repeats_holds_rests_and_keeps_selection(self):
        from test_music import FakeOutput
        text = '/key(C4)\nbpm60\n|: 1~1 - 0 [1 2 :| [2 3\n/key(D4)\nbpm120\n4_5_'
        editor, _, _ = self.source_editor(text)
        editor.select_range(text.index('1~'), text.index('[1'))
        selection = editor.text.get('sel.first', 'sel.last')
        insert = editor.text.index('insert')
        with patch('score_editor.PreviewOutput', return_value=FakeOutput()):
            editor.preview()
        expected = ['1', '1', '-', '0', '2', '1', '1', '-', '0', '3', '4_', '5_']
        self.assertEqual([text[a:b] for a, b, _, _ in editor.preview_trace], expected)
        for a, b, onset, end in editor.preview_trace:
            with patch('score_editor.Player.position', new_callable=PropertyMock, return_value=(onset+end)/2):
                editor.update_playing_position()
            self.assertEqual(editor.playing_span, (a, b))
            preview = editor.score_preview
            self.assertEqual(preview.glyphs[preview.playing_index].start, a)
            self.assertEqual(preview.canvas.itemcget(preview.hit_items[preview.playing_index], 'fill'), '#c6ef86')
            self.assertEqual(editor.text.get('playing.first', 'playing.last'), text[a:b])
        self.assertEqual(editor.text.get('sel.first', 'sel.last'), selection)
        self.assertEqual(editor.text.index('insert'), insert)
        first_run = editor.preview_run_id
        editor.stop_preview()
        editor.update_playing_position()
        self.assertIsNone(editor.playing_span)
        self.assertIsNone(editor.score_preview.playing_index)
        self.assertFalse(editor.text.tag_ranges('playing'))
        editor.player.thread.join(1)
        with patch('score_editor.PreviewOutput', return_value=FakeOutput()):
            editor.preview(True)
        editor.events.put((first_run, 'done', ('旧试听完成', None)))
        with patch('score_editor.Player.position', new_callable=PropertyMock, return_value=4.5):
            editor.dialog.after_cancel(editor.poll_timer)
            editor.poll()
        self.assertEqual(editor.playing_span, (text.index('1~'), text.index('1~')+1))
        self.assertIn('选中片段', editor.status.get())
        self.assertEqual(editor.preview_trace[-1][3], 8)
        self.replace(editor, text.replace('bpm60', 'bpm90'))
        self.pump(lambda: not editor.player.active and editor.playing_span is None)

    def test_mark_clears_after_completion_and_output_failure(self):
        from test_music import FakeOutput
        editor, _, _ = self.source_editor('bpm300\n1 2')
        with patch('score_editor.PreviewOutput', return_value=FakeOutput()):
            editor.preview()
        self.pump(lambda: editor.playing_span is not None)
        self.pump(lambda: not editor.player.active and editor.playing_span is None
                  and editor.status.get() == '演奏完成')
        with patch('score_editor.PreviewOutput', side_effect=RuntimeError('输出设备不可用')):
            editor.preview()
        self.pump(lambda: '输出设备不可用' in editor.status.get())
        self.assertIsNone(editor.score_preview.playing_index)
        self.assertFalse(editor.text.tag_ranges('playing'))

    def test_preview_scrolls_and_preserves_mark_across_resize_and_pages(self):
        text = 'bpm300\n' + '1_2_3_4_|\n'*405
        editor, _, _ = self.source_editor(text)
        preview = editor.score_preview
        for index in (180, 2003, 3):
            glyph = preview.glyphs[index]
            preview.mark_playing((glyph.start, glyph.end))
            self.root.update()
            self.assertEqual(preview.playing_index, index)
            self.assertEqual(preview.page, index//preview.PAGE_SIZE)
            self.assertTrue(preview.pages.winfo_ismapped())
            editor.dialog.state('zoomed' if index == 2003 else 'normal')
            self.root.update()
            item = preview.hit_items[index]
            self.assertEqual(preview.canvas.itemcget(item, 'fill'), '#c6ef86')
            _, top, _, bottom = preview.canvas.coords(item)
            visible_top = preview.canvas.canvasy(0)
            self.assertGreaterEqual(top, visible_top)
            self.assertLessEqual(bottom, visible_top+preview.canvas.winfo_height())
        preview.next_page.invoke()
        self.assertEqual(preview.page, 1)
        preview.previous_page.invoke()
        self.assertEqual(preview.page, 0)

    def test_source_mode_marks_the_enclosing_ending_symbol(self):
        from test_music import FakeOutput
        text = 'bpm60\n|: 1 [1 2 :| [2 3'
        editor, _, _ = self.source_editor(text, mode='source')
        with patch('score_editor.PreviewOutput', return_value=FakeOutput()):
            editor.preview()
        with patch('score_editor.Player.position', new_callable=PropertyMock, return_value=1.5):
            editor.update_playing_position()
        preview = editor.score_preview
        self.assertEqual(preview.glyphs[preview.playing_index].text, '[1')


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite(loader.loadTestsFromTestCase(SourceNotationTests))
    for name in SourceEditorTests.__dict__:
        if name.startswith('test_'):
            suite.addTest(SourceEditorTests(name))
    return suite


if __name__ == '__main__':
    unittest.main(verbosity=2)
