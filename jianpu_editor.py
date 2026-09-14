"""简谱空间风格的原谱编辑辅助与可定位的谱面预览；不依赖网站脚本。"""
from dataclasses import dataclass
from bisect import bisect_right
import re
import tkinter as tk
from tkinter import font as tkfont

from music import (JIANPU_SPACE_KEY, JIANPU_SPACE_NOTE, JIANPU_SPACE_DURATION, SCALE, jianpu_space_lines, jianpu_lyric_syllables,
                   parse_jianpu_space, pitch_name)


@dataclass
class Glyph:
    kind: str
    text: str
    start: int
    end: int
    line: int
    parts: tuple = ()
    lyric: str = ""
    duration: str = ""


def score_glyphs(text):
    """把谱文拆成显示符号，沿用演奏解析器的音符、调号和字符定位规则。"""
    result, lyrics = [], []
    structure = re.compile(r"\|:|:\|:|:\||\[1|\[2|\|[|\]]?|[()~]")
    chord = re.compile(r"[A-G][#b]?(?:(?:maj|min|m|dim|aug|sus|add)?(?:[2-9]|11|13)?)(?:/[A-G][#b]?)?")
    for number, line, positions in jianpu_space_lines(text):
        if not line or line.startswith('//'):
            continue
        if line.startswith('L:'):
            try:
                lyrics.extend(jianpu_lyric_syllables(line[2:]))
            except ValueError:
                lyrics.append(line[2:])
            continue
        if re.fullmatch(r'bpm\s*[:=]?\s*\d+(?:\.\d+)?', line, re.I):
            result.append(Glyph('tempo', line, positions[0], positions[-1]+1, number))
            continue
        if all(chord.fullmatch(token) for token in line.split()):
            result.append(Glyph('annotation', line, positions[0], positions[-1]+1, number))
            continue
        index = 0
        while index < len(line):
            if line[index].isspace():
                index += 1
                continue
            match, kind = JIANPU_SPACE_KEY.match(line, index), 'key'
            if not match:
                match, kind = structure.match(line, index), 'structure'
            if not match:
                match, kind = JIANPU_SPACE_NOTE.match(line, index), 'note'
            if not match:
                match, kind = re.compile(r'[ac-mo-z]+|.').match(line, index), 'annotation'
            end = match.end()
            duration = JIANPU_SPACE_DURATION.match(line, end) if kind == 'note' else None
            if duration:
                end = duration.end()
            result.append(Glyph(kind, line[index:end], positions[index], positions[end-1]+1,
                                number, match.groups(), duration=duration[1] if duration else ''))
            index = end
    notes = [glyph for glyph in result if glyph.kind == 'note' and glyph.parts[1] not in ('0', '-')]
    for glyph, lyric in zip(notes, lyrics):
        glyph.lyric = '' if lyric in ('_', '*') else lyric.strip('"')
    return result


def score_metadata(text):
    glyphs = score_glyphs(text)
    key = next((g.parts[0].upper() + g.parts[1] + g.parts[2] for g in glyphs if g.kind == 'key'), 'C4')
    bpm = next((float(re.search(r'\d+(?:\.\d+)?', g.text)[0]) for g in glyphs if g.kind == 'tempo'), 120.0)
    return key, bpm


def replace_header(text, kind, value):
    """修改首个调号或速度标记，保留其他段落、歌词和换行。"""
    glyph = next((g for g in score_glyphs(text) if g.kind == kind), None)
    replacement = f'/key({value})' if kind == 'key' else f'bpm{value:g}'
    if glyph:
        return text[:glyph.start] + replacement + text[glyph.end:]
    return replacement + '\n' + text


def transpose_source(text, semitones, mode):
    """整曲移调只改绝对调号，保持音阶数字、时值和歌词相对转调可读。"""
    parse_jianpu_space(text, '移调校验', mode=mode)
    glyphs = score_glyphs(text)
    keys = [g for g in glyphs if g.kind == 'key']
    result = text
    for glyph in reversed(keys):
        letter, accidental, octave = glyph.parts
        letter = letter.upper()
        octave = int(octave) if octave else (3 if letter in 'GAB' else 4)
        pitch = 12 * (octave+1) + dict(zip('CDEFGAB', SCALE))[letter] + {'': 0, '#': 1, 'b': -1}[accidental] + semitones
        if not 0 <= pitch <= 127:
            raise ValueError('移调后的调号超出 MIDI 音域。')
        result = result[:glyph.start] + f'/key({pitch_name(pitch)})' + result[glyph.end:]
    first_note = next((g for g in glyphs if g.kind == 'note'), None)
    if not keys or (mode == 'score' and first_note and first_note.start < keys[0].start):
        result = f'/key({pitch_name(60 + semitones)})\n' + result
    parse_jianpu_space(result, '移调校验', mode=mode)
    return result


class ScorePreview(tk.Frame):
    """把原简谱渲染成数字、八度点、减时线和歌词，点击符号定位编辑文字。"""
    PAGE_SIZE = 2000

    def __init__(self, parent, select):
        super().__init__(parent, bg='#faf7ed')
        self.select = select
        self.glyphs = []
        self.glyph_starts = []
        self.playing_index = None
        self.page = 0
        self.hit_items = {}
        self.font = tkfont.Font(self, family='Consolas', size=18, weight='bold')
        self.small = tkfont.Font(self, family='Microsoft YaHei UI', size=9)
        self.canvas = tk.Canvas(self, bg='#faf7ed', highlightthickness=0)
        scrollbar = tk.Scrollbar(self, command=self.canvas.yview)
        scrollbar.pack(side='right', fill='y')
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', self.draw)
        self.canvas.bind('<MouseWheel>', lambda e: self.canvas.yview_scroll(-int(e.delta / 120), 'units'))
        self.canvas.bind('<Button-1>', self.clicked)
        self.canvas.bind('<Motion>', self.hover)
        self.pages = tk.Frame(self, bg='#faf7ed')
        self.previous_page = tk.Button(self.pages, text='上一页', command=lambda: self.change_page(self.page-1))
        self.previous_page.pack(side='left')
        self.page_label = tk.Label(self.pages, bg='#faf7ed', fg='#486346')
        self.page_label.pack(side='left', expand=True)
        self.next_page = tk.Button(self.pages, text='下一页', command=lambda: self.change_page(self.page+1))
        self.next_page.pack(side='right')

    def show(self, text, error=None):
        self.glyphs = score_glyphs(text) if not error else []
        self.glyph_starts = [glyph.start for glyph in self.glyphs]
        self.playing_index = None
        self.page = min(self.page, max(0, (len(self.glyphs)-1)//self.PAGE_SIZE))
        self.error = error
        self.draw()

    def change_page(self, page):
        self.page = min(max(0, page), max(0, (len(self.glyphs)-1)//self.PAGE_SIZE))
        self.canvas.yview_moveto(0)
        self.draw()

    def mark_playing(self, span):
        """按源文位置找符号；反复回跳可复用同一符号，源站房子数字落在整个房子标记内。"""
        previous = self.hit_items.get(self.playing_index)
        if previous:
            self.canvas.itemconfigure(previous, fill='#faf7ed', outline='')
        index = bisect_right(self.glyph_starts, span[0])-1 if span else -1
        if index >= 0 and self.glyphs[index].end >= span[1]:
            self.playing_index = index
            if index // self.PAGE_SIZE != self.page:
                self.change_page(index // self.PAGE_SIZE)
        else:
            self.playing_index = None
        self.paint_playing()

    def paint_playing(self):
        item = self.hit_items.get(self.playing_index)
        if not item:
            return
        self.canvas.itemconfigure(item, fill='#c6ef86', outline='#4c782f', width=2)
        _, top, _, bottom = self.canvas.coords(item)
        visible_top = self.canvas.canvasy(0)
        visible_bottom = visible_top + self.canvas.winfo_height()
        if top < visible_top or bottom > visible_bottom:
            region = self.canvas.bbox('all')
            total = float(self.canvas.cget('scrollregion').split()[3]) if region else 1
            self.canvas.yview_moveto(max(0, top-18) / max(1, total))

    def metrics(self, glyph, width):
        duration, lyric = '', glyph.lyric
        if glyph.kind == 'note':
            length = glyph.parts[3]
            if length.startswith('-'):
                duration = ' '.join('-' * len(length)) if len(length) <= 6 else f'- - …({len(length)+1}拍)'
            lyric = lyric if len(lyric) <= 24 else lyric[:23] + '…'
            advance = max(40 + self.font.measure(duration), self.small.measure(lyric) + 12)
            if glyph.duration:
                advance = max(advance, self.small.measure(glyph.duration + '拍') + 12)
        else:
            label = '1=' + ''.join(glyph.parts) if glyph.kind == 'key' else glyph.text
            advance = max(24, self.small.measure(label) + 16)
        return min(advance, width-48), duration, lyric

    def draw(self, event=None):
        canvas = self.canvas
        canvas.delete('all')
        self.hit_items = {}
        width = max(200, canvas.winfo_width())
        count = max(1, (len(self.glyphs)+self.PAGE_SIZE-1)//self.PAGE_SIZE)
        if count > 1:
            self.pages.pack(side='bottom', fill='x', before=self.canvas)
            self.page_label.configure(text=f'{self.page+1} / {count} 页 · 试听自动翻页')
            self.previous_page.configure(state='normal' if self.page > 0 else 'disabled')
            self.next_page.configure(state='normal' if self.page+1 < count else 'disabled')
        else:
            self.pages.pack_forget()
        if getattr(self, 'error', None):
            canvas.create_text(18, 20, text='请先修正谱文\n' + self.error, anchor='nw', width=width-36,
                               fill='#9a431e', font=self.small)
            canvas.configure(scrollregion=(0, 0, width, 150))
            return
        height = self.font.metrics('linespace')
        step, x, y, previous_line = height * 2.8, 24, height * 1.3, None
        slurs, ties = [], []
        last_note = None
        previous_kind = None
        page_start = self.page * self.PAGE_SIZE
        displayed = self.glyphs[page_start:page_start+self.PAGE_SIZE]
        sizes = [self.metrics(glyph, width) for glyph in displayed]
        for index, glyph in enumerate(displayed):
            advance, duration_text, lyric_text = sizes[index]
            if glyph.kind == 'note':
                accidental, degree, octave, length, dots = glyph.parts
            # 小节能完整放进新行时，优先整节换行，避免把末尾一个音单独挤到下一行。
            measure_start = index > 0 and displayed[index-1].kind == 'structure' and '|' in displayed[index-1].text
            if measure_start and x > 24:
                measure_width = 0
                for next_index in range(index, len(displayed)):
                    following = displayed[next_index]
                    if following.line != glyph.line:
                        break
                    measure_width += sizes[next_index][0]
                    if following.kind == 'structure' and '|' in following.text:
                        break
                if x + measure_width > width-20 and measure_width <= width-44:
                    x, y = 24, y+step
            header_pair = previous_kind in ('key', 'tempo') and glyph.kind in ('key', 'tempo')
            if ((previous_line is not None and glyph.line != previous_line and not header_pair)
                    or x + advance > width - 20) and x > 24:
                x, y = 24, y + step
            previous_line, previous_kind = glyph.line, glyph.kind
            tag = f'g{page_start+index}'
            self.hit_items[page_start+index] = canvas.create_rectangle(
                x-4, y-height*1.2, x+advance-4, y+height*1.5,
                fill='#faf7ed', outline='', tags=(tag, 'hit'))
            if glyph.kind == 'note':
                center = x + 14
                slurs = [(center, y) if point is None else point for point in slurs]
                canvas.create_text(center, y, text=degree, font=self.font, fill='#252b24', tags=tag)
                if glyph.duration:
                    # 非二分时值直接标明拍数，避免把三连音画成普通四分音符。
                    canvas.create_text(x+advance/2-4, y-height*1.12, text=glyph.duration+'拍',
                                       font=self.small, fill='#486346', tags=(tag, 'precise_duration'))
                if accidental:
                    label = accidental.replace('#', '♯').replace('b', '♭').replace('n', '♮')
                    canvas.create_text(center-12, y-height*.35, text=label, font=self.small, anchor='e', tags=tag)
                lines = 2 * length.count('=') + length.count('_')
                for j in range(lines):
                    canvas.create_line(center-9, y+height*.48+j*4, center+9, y+height*.48+j*4,
                                       fill='#252b24', width=1.4, tags=tag)
                for j in range(len(octave)):
                    dot_y = y-height*.65-j*5 if octave.startswith("'") else y+height*.62+lines*4+j*5
                    canvas.create_oval(center-1.7, dot_y-1.7, center+1.7, dot_y+1.7, fill='#252b24', outline='', tags=tag)
                for j in range(len(dots)):
                    canvas.create_oval(center+12+j*5, y-2, center+15+j*5, y+1, fill='#252b24', outline='', tags=tag)
                if length.startswith('-'):
                    canvas.create_text(center+19, y, text=duration_text, anchor='w', font=self.font, tags=tag)
                if glyph.lyric:
                    canvas.create_text(x+advance/2-4, y+height*1.05, text=lyric_text, font=self.small,
                                       fill='#646b5e', width=advance, tags=tag)
                if ties:
                    left = ties.pop()
                    self.arc(left, (center, y), width, step, height)
                last_note = (center, y)
            elif glyph.text in ('(', ')', '~'):
                if glyph.text == '(':
                    slurs.append(None)
                elif glyph.text == ')' and slurs and last_note:
                    self.arc(slurs.pop(), last_note, width, step, height)
                elif glyph.text == '~' and last_note:
                    ties.append(last_note)
            elif glyph.kind == 'structure' and '|' in glyph.text:
                canvas.create_line(x+8, y-height*.55, x+8, y+height*.55, fill='#66705e', tags=tag)
                if glyph.text != '|':
                    canvas.create_line(x+12, y-height*.55, x+12, y+height*.55, fill='#66705e', tags=tag)
                if ':' in glyph.text:
                    for side in ([-1] if glyph.text == ':|' else [1] if glyph.text == '|:' else [-1, 1]):
                        for vertical in (-5, 5):
                            cx, cy = x+10+side*9, y+vertical
                            canvas.create_oval(cx-1.5, cy-1.5, cx+1.5, cy+1.5, fill='#252b24', tags=tag)
            else:
                label = '1=' + ''.join(glyph.parts) if glyph.kind == 'key' else glyph.text
                if glyph.text in ('[1', '[2'):
                    label = glyph.text[1] + '.'
                    canvas.create_line(x, y-height*.8, x+advance+10, y-height*.8, fill='#66705e', tags=tag)
                canvas.create_text(x, y, text=label, anchor='w', font=self.small,
                                   fill='#486346' if glyph.kind != 'annotation' else '#9a6c38', tags=tag)
            x += advance
        canvas.configure(scrollregion=(0, 0, width, y+step))
        self.paint_playing()

    def arc(self, start, end, width, step, height):
        x, y = start
        right, bottom = end
        while y <= bottom + 1:
            stop = right if abs(y-bottom) < 1 else width-20
            if stop > x:
                top = y-height*.95
                self.canvas.create_line(x, top, (x+stop)/2, top-12, stop, top, smooth=True,
                                        fill='#66705e', width=1.2)
            x, y = 24, y+step

    def current(self):
        for tag in self.canvas.gettags('current'):
            if tag.startswith('g') and tag[1:].isdigit():
                return self.glyphs[int(tag[1:])]
        return None

    def clicked(self, event):
        glyph = self.current()
        if glyph:
            self.select(glyph.start, glyph.end)

    def hover(self, event):
        self.canvas.configure(cursor='hand2' if self.current() else '')
