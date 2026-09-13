"""乐谱解析、单旋律整理与口风琴映射。"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from fractions import Fraction
from pathlib import Path
import math
import re
import unicodedata

SCALE = (0, 2, 4, 5, 7, 9, 11)
JIANPU_SPACE_NOTE = re.compile(r"(#{1,2}|b{1,2}|n)?([0-7]|-)((?:'+|,+)?)(-+|=*_?)(\.{0,2})")
JIANPU_SPACE_KEY = re.compile(r"/key\(([A-Ga-g])([#b]?)([0-9]?)\)")


@dataclass(frozen=True)
class Note:
    start: float
    end: float
    pitch: int
    track: int = 0
    legato: bool = False


@dataclass
class Song:
    title: str
    notes: list[Note]
    tracks: dict[int, str] = field(default_factory=lambda: {0: "主旋律"})
    duration: float = 0.0

    def __post_init__(self):
        self.duration = max(self.duration, max((n.end for n in self.notes), default=0))


@dataclass(frozen=True)
class Mapping:
    keys: str = "zxcvbnm,"
    base: int = 60
    low: int = -12
    high: int = 12
    half: int = 1

    def validate(self):
        if len(self.keys) != 8 or len(set(self.keys.lower())) != 8 or any(k not in "abcdefghijklmnopqrstuvwxyz,./;[]-=" for k in self.keys.lower()):
            raise ValueError("音阶键必须是 8 个不同的英文字母或标点，例如 zxcvbnm,（末尾为英文逗号）。")
        if not 24 <= self.base <= 96:
            raise ValueError("中央 1 的 MIDI 音高必须在 24～96 之间。")
        if not all(-24 <= x <= 24 for x in (self.low, self.high)) or self.half not in (-1, 1):
            raise ValueError("左／右键偏移需在 -24～24 半音之间，中键为 +1 或 -1。")


@dataclass(frozen=True)
class Fingering:
    key: str
    buttons: tuple[str, ...]
    pitch: int

    @property
    def label(self):
        names = {"left": "左", "middle": "中", "right": "右"}
        return " + ".join([*(names[b] for b in self.buttons), self.key.upper()])


@dataclass(frozen=True)
class PlayNote:
    start: float
    end: float
    source_pitch: int
    fingering: Fingering
    legato: bool = False


@dataclass
class Plan:
    notes: list[PlayNote]
    duration: float
    folded: int
    source_count: int
    style: str = "original"
    cleaned: int = 0
    bridged: int = 0
    track: int | None = None


def pitch_name(pitch: int) -> str:
    return ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")[pitch % 12] + str(pitch // 12 - 1)


def parse_jianpu(text: str, bpm: float = 100, title: str = "自定义简谱", *, precise=False) -> Song:
    if not math.isfinite(bpm) or not 20 <= bpm <= 300:
        raise ValueError("速度需在 20～300 BPM 之间。")
    notes, cursor = [], 0.0
    pattern = re.compile(r"(\+{0,5}|-{1,5})([#b]?)([0-7])(?::(\d+(?:/\d+|\.\d+)?))?")
    clean = re.sub(r"//[^\n]*", "", text).replace("|", " ").replace("，", " ")
    tokens = clean.replace("(", " ( ").replace(")", " ) ").split()
    if len(tokens) > (120002 if precise else 90000):
        raise ValueError("乐谱最多支持 30000 个音符。")
    slurs = []
    for token in tokens:
        if token == "(":
            if len(slurs) >= 8:
                raise ValueError("连线最多嵌套 8 层。")
            slurs.append(len(notes))
            continue
        if token == ")":
            if not slurs or slurs[-1] == len(notes):
                raise ValueError("连线括号不配对或没有音符。")
            start = slurs.pop()
            # 编辑器括号仅标记连奏；导入的同音延音已合并为一个长音。
            notes[start:] = [replace(note, legato=True) for note in notes[start:]]
            continue
        match = pattern.fullmatch(token)
        if not match:
            raise ValueError(f"无法识别「{token}」。请用空格分隔，例如：1 2 3:2 +1 -5 #4 0。")
        octave, accidental, degree, duration = match.groups()
        try:
            beats = float(Fraction(duration or "1"))
        except (ValueError, ZeroDivisionError, OverflowError):
            raise ValueError(f"「{token}」的时值不正确。") from None
        minimum, maximum = (0.000000001, 9000) if precise else (0.03125, 64)
        if not minimum <= beats <= maximum:
            raise ValueError("音符时值必须大于零且不超过 9000 拍。" if precise else "每个音符的时值需在 1/32～64 拍之间。")
        end = cursor + beats * 60 / bpm
        if degree != "0":
            pitch = 60 + SCALE[int(degree)-1] + (octave.count("+")-octave.count("-"))*12
            pitch += {"": 0, "#": 1, "b": -1}[accidental]
            if not 0 <= pitch <= 127:
                raise ValueError(f"「{token}」超出 MIDI 音高 0～127 的范围。")
            notes.append(Note(cursor, end, pitch))
        elif octave or accidental:
            raise ValueError("休止符 0 不需要八度或升降号。")
        cursor = end
    if slurs:
        raise ValueError("连线缺少右括号。")
    if not notes:
        raise ValueError("乐谱中没有可演奏的音符。")
    if len(notes) > 30000:
        raise ValueError("乐谱最多支持 30000 个音符。")
    if cursor > 1800:
        raise ValueError("第一版支持最长 30 分钟的曲目。")
    return Song(title.strip() or "自定义简谱", notes, duration=cursor)


def jianpu_lyric_syllables(line):
    """预览与转调共用歌词分词；引号短语、星号、下划线各占一个音。"""
    # 覆盖汉字基本区、兼容区和扩展区，英文单词与标点沿用谱源的音节边界。
    han = "\u2e80-\u2fff\u3005\u3007\u3021-\u3029\u3038-\u303b\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af"
    token_pattern = re.compile(rf'"(?:[^"]|"")+"|[{han}][^-\s{han}_*"]*|[^\s{han}_*\-"]+|[_*]|-')
    index = 0
    while index < len(line):
        if line[index].isspace():
            index += 1
            continue
        match = token_pattern.match(line, index)
        if not match:
            raise ValueError("歌词引号不完整，无法定位音节。")
        if match[0] != "-":
            yield match[0]
        index = match.end()


def _jianpu_lyric_key_changes(lines: list[tuple[int, str]]) -> dict[int, int]:
    """按原谱歌词音节定位相对转调，不让休止或延音占用歌词编号。"""
    changes, position = {}, 0
    change_pattern = re.compile(r"\(([升降+\-])(\d+)key\)", re.IGNORECASE)
    for line_number, line in lines:
        try:
            tokens = list(jianpu_lyric_syllables(line))
        except ValueError as error:
            raise ValueError(f"第 {line_number} 行{error}") from None
        for token in tokens:
            commands = list(change_pattern.finditer(token))
            if len(commands) > 1:
                raise ValueError(f"第 {line_number} 行同一音节含多个转调指令，请核对原谱。")
            if commands:
                direction, value = commands[0].groups()
                changes[position] = int(value) * (1 if direction in ("升", "+") else -1)
            position += 1
    return changes


@dataclass(frozen=True)
class _JianpuEvent:
    kind: str
    value: object = None
    line: int = 0
    position: int = -1
    span: tuple[int, int] = (-1, -1)


def jianpu_space_lines(text):
    """全角字符按谱源语法归一化，同时保留每个字符在编辑文字中的位置。"""
    offset = 0
    for number, raw in enumerate(text.splitlines(keepends=True), 1):
        characters, positions = [], []
        for index, char in enumerate(raw):
            normalized = unicodedata.normalize("NFKC", char)
            characters.extend(normalized)
            positions.extend([offset + index] * len(normalized))
        line = "".join(characters)
        left, right = len(line) - len(line.lstrip()), len(line.rstrip())
        yield number, line[left:right], positions[left:right]
        offset += len(raw)


def _jianpu_repeats(events: list[_JianpuEvent]) -> list[_JianpuEvent]:
    """把反复和一、二房子整理成有限的结构，展开时再恢复段首调号和速度。"""
    index = 0

    def sequence(depth=0, explicit=False):
        nonlocal index
        body, first = [], None
        while index < len(events):
            event = events[index]
            index += 1
            if event.kind == "repeat_start":
                if depth >= 8:
                    raise ValueError(f"第 {event.line} 行反复最多嵌套 8 层。")
                repeated = sequence(depth + 1, True)
                (body if first is None else first).append(_JianpuEvent("repeat", repeated, event.line))
            elif event.kind == "ending1":
                if first is not None:
                    raise ValueError(f"第 {event.line} 行一房子重复出现。")
                first = []
            elif event.kind == "repeat_end":
                if not body or first == []:
                    raise ValueError(f"第 {event.line} 行反复段或一房子为空。")
                if first is not None:
                    if index >= len(events) or events[index].kind != "ending2":
                        raise ValueError(f"第 {event.line} 行一房子结束后需要 [2 二房子。")
                    index += 1
                    if index >= len(events) or events[index].kind in ("repeat_end", "ending1", "ending2"):
                        raise ValueError(f"第 {event.line} 行二房子没有内容。")
                if explicit:
                    return body, first
                # 缺省起始反复号时，从曲首（或上一个已完成的反复段之后）重复。
                after = max((i + 1 for i, item in enumerate(body) if item.kind == "repeat"), default=0)
                if not body[after:]:
                    raise ValueError(f"第 {event.line} 行反复段为空，请补写 |: 起点。")
                body = body[:after] + [_JianpuEvent("repeat", (body[after:], first), event.line)]
                first = None
            elif event.kind == "ending2":
                raise ValueError(f"第 {event.line} 行二房子前缺少 [1 和 :|。")
            else:
                (body if first is None else first).append(event)
        if explicit or first is not None:
            raise ValueError("反复段缺少结束符 :|。")
        return body

    return sequence()


def parse_jianpu_space(text: str, title: str, *, mode="score", trace=None) -> tuple[Song, list[str]]:
    """读取文字简谱；谱面模式补齐演奏结构，源站模式保留已核对的播放差异。"""
    if mode not in ("score", "source"):
        raise ValueError("请选择按谱面规则或跟随源站播放。")
    if len(text) > 200000:
        raise ValueError("简谱文字不能超过 20 万个字符。")
    music_lines, lyric_lines = [], []
    for line_number, line, positions in jianpu_space_lines(text):
        if line.startswith("L:"):
            lyric_lines.append((line_number, line[2:]))
        else:
            music_lines.append((line_number, line, positions))
    has_changes = any(re.search(r"\([升降+\-]\d+key\)", line, re.IGNORECASE) for _, line in lyric_lines)
    key_changes = _jianpu_lyric_key_changes(lyric_lines) if has_changes else {}
    key_pattern, token_pattern = JIANPU_SPACE_KEY, JIANPU_SPACE_NOTE
    bar_pattern = re.compile(r"\|[|\]]?")
    annotation_pattern = re.compile(r"[ac-mo-z]+")
    chord_pattern = re.compile(r"[A-G][#b]?(?:(?:maj|min|m|dim|aug|sus|add)?(?:[2-9]|11|13)?)(?:/[A-G][#b]?)?")
    events, keys, annotations, warnings = [], [], [], []
    source_count, skipped_chords, ignored_structure = 0, False, False
    structures = {"|:": "repeat_start", ":|": "repeat_end", "[1": "ending1", "[2": "ending2",
                  "(": "slur_start", ")": "slur_end", "~": "tie"}
    for line_number, line, positions in music_lines:
        if not line:
            continue
        tempo = re.fullmatch(r"bpm\s*[:=]?\s*(\d+(?:\.\d+)?)", line, re.IGNORECASE)
        if tempo:
            bpm = float(tempo[1])
            if not 20 <= bpm <= 500:
                raise ValueError(f"第 {line_number} 行速度需在 20～500 BPM 之间。")
            events.append(_JianpuEvent("tempo", bpm, line_number))
            continue
        if all(chord_pattern.fullmatch(chord) for chord in line.split()):
            skipped_chords = True
            continue
        index = 0
        while index < len(line):
            if line[index].isspace():
                index += 1
                continue
            key = key_pattern.match(line, index)
            if key:
                letter, accidental, octave = key.groups()
                letter = letter.upper()
                # 沿用谱源缺省音区：G、A、B 为第三组，其余为第四组。
                octave = int(octave) if octave else (3 if letter in "GAB" else 4)
                base = 12 * (octave + 1) + dict(zip("CDEFGAB", SCALE))[letter]
                base += {"": 0, "#": 1, "b": -1}[accidental]
                if not 0 <= base <= 127:
                    raise ValueError(f"第 {line_number} 行调号超出 MIDI 0～127 的范围。")
                keys.append(base)
                events.append(_JianpuEvent("key", base, line_number))
                index = key.end()
                continue
            if mode == "source" and line[index] in ":()~[]":
                ignored_structure = True
                index += 1
                continue
            if mode == "score":
                # 避免把常用的紧邻小节线「|1」误读成一房子。
                symbol = next((symbol for symbol in structures if line.startswith(symbol, index)), None)
                if symbol:
                    events.append(_JianpuEvent(structures[symbol], line=line_number))
                    index += len(symbol)
                    if symbol == ":|" and line[index:index+1] == ":":
                        events.append(_JianpuEvent("repeat_start", line=line_number))
                        index += 1
                    continue
            bar = bar_pattern.match(line, index)
            if bar:
                index = bar.end()
                continue
            match = token_pattern.match(line, index)
            if not match:
                annotation = annotation_pattern.match(line, index)
                if annotation:
                    annotations.append(f"第 {line_number} 行「{annotation[0][:20]}」")
                    index = annotation.end()
                    continue
                raise ValueError(f"第 {line_number} 行第 {index + 1} 字附近「{line[index:index+16]}」含暂不支持的记谱，请打开源谱校对。")
            accidental, degree, octave, length, dots = match.groups()
            if degree in ("0", "-") and (accidental or octave):
                raise ValueError(f"第 {line_number} 行休止或延音不能带升降号、八度点。")
            if len(length) > 63 or length.count("=") > 5:
                raise ValueError(f"第 {line_number} 行音符时值超出支持范围。")
            beats = 1 + len(length) if length.startswith("-") else 0.5 ** (2 * length.count("=") + length.count("_"))
            beats *= 2 - 0.5 ** len(dots)
            offset = 12 * (octave.count("'") - octave.count(","))
            offset += (accidental or "").count("#") - (accidental or "").count("b")
            events.append(_JianpuEvent("note", (degree, offset, beats), line_number, source_count,
                                       (positions[index], positions[match.end()-1]+1)))
            if degree not in ("0", "-"):
                source_count += 1
            index = match.end()
    if key_changes and max(key_changes) >= source_count:
        raise ValueError("歌词中的转调指令没有对应音符，请核对原谱的歌词占位。")
    if source_count > 30000:
        raise ValueError("简谱最多支持 30000 个音符、30 分钟。")
    if mode == "score":
        events = _jianpu_repeats(events)
    base = keys[-1] if keys and mode == "source" else 60
    state = {"base": base, "bpm": 120.0, "tempo_set": False, "transpose": 0,
             "key_set": bool(keys) and mode == "source"}
    notes, slurs = [], []
    cursor, steps, repeats, ties, phrases = 0.0, 0, 0, 0, 0
    previous_is_note, can_extend, pending_tie = False, False, False
    used_default_tempo, used_default_key = False, not keys

    def boundary():
        if slurs or pending_tie:
            raise ValueError("连线不能跨越反复跳转或房子边界，请在各段内写完整连线。")

    def perform(items):
        nonlocal cursor, steps, repeats, ties, phrases, previous_is_note, can_extend, pending_tie
        nonlocal used_default_tempo, used_default_key
        for event in items:
            steps += 1
            if steps > 120000:
                raise ValueError("反复展开后的记谱过多，请减少嵌套。")
            kind, value = event.kind, event.value
            if kind == "repeat":
                boundary()
                snapshot = state.copy()
                body, first = value
                repeats += 1
                for turn in range(2):
                    state.update(snapshot)
                    previous_is_note = False
                    can_extend = False
                    before = cursor
                    perform(body)
                    if cursor == before:
                        raise ValueError("反复段需要音符或休止符。")
                    boundary()
                    if turn == 0 and first is not None:
                        perform(first)
                        boundary()
                continue
            if kind == "key":
                if mode == "score":
                    state["base"] = value
                    state["key_set"] = True
                    # 绝对调号开始新段，不继续叠加前一段歌词的相对转调。
                    state["transpose"] = 0
                continue
            if kind == "tempo":
                state["bpm"], state["tempo_set"] = value, True
                continue
            if kind == "slur_start":
                if len(slurs) >= 8 or pending_tie:
                    raise ValueError(f"第 {event.line} 行连线嵌套过深或与延音线交叉。")
                slurs.append((len(notes), cursor))
                continue
            if kind == "slur_end":
                if not slurs or pending_tie:
                    raise ValueError(f"第 {event.line} 行连线括号不配对或延音线未结束。")
                start, onset = slurs.pop()
                group = notes[start:]
                if not group or abs(group[0].start - onset) > 1e-8 or abs(group[-1].end - cursor) > 1e-8:
                    raise ValueError(f"第 {event.line} 行连线两端需要音符。")
                if all(n.pitch == group[0].pitch for n in group):
                    if any(abs(a.end - b.start) > 1e-8 for a, b in zip(group, group[1:])):
                        raise ValueError(f"第 {event.line} 行同音延音线不能跨越休止。")
                    notes[start:] = [replace(group[0], end=group[-1].end, legato=True)]
                    ties += 1
                else:
                    notes[start:] = [replace(n, legato=True) for n in group]
                    phrases += 1
                continue
            if kind == "tie":
                if pending_tie or not previous_is_note:
                    raise ValueError(f"第 {event.line} 行延音线 ~ 前需要音符。")
                pending_tie = True
                continue
            degree, offset, beats = value
            end = cursor + beats * 60 / state["bpm"]
            if trace is not None:
                trace.append((*event.span, cursor, end))
            used_default_tempo |= not state["tempo_set"]
            used_default_key |= not state["key_set"]
            if degree == "-":
                if not can_extend:
                    raise ValueError("曲首或反复段首不能以延音线开头。")
                if pending_tie:
                    raise ValueError(f"第 {event.line} 行 ~ 后需要同音高音符。")
                if previous_is_note:
                    notes[-1] = replace(notes[-1], end=end)
            elif degree == "0":
                if pending_tie:
                    raise ValueError(f"第 {event.line} 行延音线不能连接休止符。")
                previous_is_note = False
            else:
                state["transpose"] += key_changes.get(event.position, 0)
                pitch = state["base"] + SCALE[int(degree) - 1] + offset + state["transpose"]
                if not 0 <= pitch <= 127:
                    raise ValueError(f"第 {event.line} 行音高超出 MIDI 0～127 的范围。")
                if pending_tie:
                    if notes[-1].pitch != pitch or abs(notes[-1].end - cursor) > 1e-8:
                        raise ValueError(f"第 {event.line} 行延音线 ~ 只能连接相邻的同音高音符。")
                    notes[-1] = replace(notes[-1], end=end, legato=True)
                    pending_tie = False
                    ties += 1
                else:
                    notes.append(Note(cursor, end, pitch))
                previous_is_note = True
            cursor = end
            can_extend = True
            if cursor > 1800 or len(notes) > 30000:
                raise ValueError("简谱最多支持 30000 个音符、30 分钟。")

    perform(events)
    if pending_tie or slurs:
        raise ValueError("连线缺少结束音符或右括号。")
    if not notes:
        raise ValueError("简谱中没有可演奏的音符。")
    if used_default_tempo:
        warnings.append("未标速度的部分按 120 BPM 导入，可在编辑器调整。")
    if used_default_key:
        warnings.append("未标调号的部分按 1=C4 导入，可在主界面移调。")
    if key_changes:
        warnings.append(f"已按歌词对应音符处理 {len(key_changes)} 处转调。")
    if len(keys) > 1:
        warnings.append("已按标记位置处理段落调号。" if mode == "score" else "跟随源站：最后一个 /key 调号用于全曲。")
    if repeats or ties or phrases:
        warnings.append(f"按谱面规则：展开 {repeats} 个反复段，处理 {ties} 处同音延音、{phrases} 处连奏。")
    if ignored_structure:
        warnings.append("跟随源站：忽略反复、房子和圆弧／~ 连线标记。")
    if annotations:
        warnings.append(f"已忽略 {len(annotations)} 处普通字母：{'、'.join(annotations[:3])}，请对照源谱试听。")
    if skipped_chords:
        warnings.append("独立和弦标记不演奏，仅导入简谱主旋律。")
    return Song(title.strip() or "在线简谱", notes, duration=cursor), warnings


def select_jianpu_space(text, title, start, end, *, mode="score"):
    """从完整解析的时间轴裁出选中文字，保留上下文调号、歌词转调及反复次数。"""
    trace = []
    song, _ = parse_jianpu_space(text, title, mode=mode, trace=trace)
    intervals = []
    for left, right, onset, release in trace:
        if left < end and right > start:
            if left < start or right > end:
                raise ValueError("请选中完整音符，包括升降号、八度点和时值符号。")
            if intervals and abs(intervals[-1][1] - onset) < 1e-8:
                intervals[-1] = (intervals[-1][0], release)
            else:
                intervals.append((onset, release))
    notes, cursor = [], 0.0
    starts = [note.start for note in song.notes]
    for onset, release in intervals:
        for index in range(max(0, bisect_right(starts, onset)-1), len(song.notes)):
            note = song.notes[index]
            if note.start >= release:
                break
            if note.start < release and note.end > onset:
                notes.append(replace(note, start=cursor + max(note.start, onset) - onset,
                                     end=cursor + min(note.end, release) - onset))
        cursor += release - onset
    if not notes:
        raise ValueError("选中的内容没有可试听的音符。")
    return Song(title, notes, song.tracks, cursor)



def jianpu_pitch(pitch: int) -> str:
    """使用重复的八度符号表达完整 MIDI 音域，不提前折回游戏音域。"""
    if not 0 <= pitch <= 127:
        raise ValueError("移调后超出 MIDI 音高 0～127 的范围。")
    octave = pitch // 12 - 5
    prefix = "+"*octave if octave >= 0 else "-"*(-octave)
    return prefix + ("1", "#1", "2", "#2", "3", "4", "#4", "5", "#5", "6", "#6", "7")[pitch % 12]


def song_to_jianpu(song: Song, track: int | str | None = "auto", style="original", bpm=120) -> str:
    """按所选音轨提取完整原速旋律，精确拍数承载 MIDI 的变速和休止。"""
    if not math.isfinite(bpm) or not 20 <= bpm <= 300:
        raise ValueError("速度需在 20～300 BPM 之间。")
    if style not in ("original", "piano"):
        raise ValueError("请选择原谱分音或钢琴适配连奏。")
    if track == "auto":
        track = recommend_track(song)
    source = [note for note in song.notes if track is None or note.track == track]
    melody = piano_melody(source) if style == "piano" else monophonic(source)
    if not melody:
        raise ValueError("所选音轨没有音符。")
    tokens, cursor = [], 0.0

    def append_token(pitch, beats):
        duration = f"{beats:.9f}".rstrip("0").rstrip(".")
        tokens.append(pitch if duration == "1" else f"{pitch}:{duration}")

    for index, note in enumerate(melody):
        start, end = round(note.start*bpm/60, 9), round(note.end*bpm/60, 9)
        if start > cursor:
            append_token("0", start-cursor)
        if note.legato and (index == 0 or not melody[index-1].legato or start > cursor):
            tokens.append("(")
        append_token(jianpu_pitch(note.pitch), max(0.000000001, end-start))
        if note.legato and (index+1 == len(melody) or not melody[index+1].legato
                            or round(melody[index+1].start*bpm/60, 9) > end):
            tokens.append(")")
        cursor = end
    end = round(song.duration*bpm/60, 9)
    if end > cursor:
        append_token("0", end-cursor)
    return "\n".join("  ".join(tokens[index:index+8]) for index in range(0, len(tokens), 8))


def transpose_jianpu(text: str, semitones: int) -> str:
    """只修改音高，保留原有时值、休止、分节和中文注释。"""
    parse_jianpu(text, 300, precise=True)

    def replace(match):
        token = match.group()
        if token.startswith("//") or token.startswith("0"):
            return token
        pitch = parse_jianpu(token, 300, precise=True).notes[0].pitch
        return jianpu_pitch(pitch+semitones) + (":"+token.split(":", 1)[1] if ":" in token else "")

    return re.sub(r"//[^\n]*|(?:\+{0,5}|-{1,5})[#b]?[0-7](?::\d+(?:/\d+|\.\d+)?)?", replace, text)


def _decode_track_name(name: str) -> str:
    """从无损 Latin-1 字符串恢复常见的 UTF-8 和中文 MIDI 音轨名。"""
    raw = name.encode("latin1")
    try:
        return raw.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        pass
    try:
        decoded = raw.decode("gb18030")
    except UnicodeDecodeError:
        return name.strip()
    chinese = sum("\u3400" <= char <= "\u9fff" or "\U00020000" <= char <= "\U000323af" for char in decoded)
    # 单个西文重音字母也可能与后面的 ASCII 组成 GBK 字符，避免误改 Réverb 等名称。
    if chinese and (sum(byte >= 0x80 for byte in raw) > chinese or any(0x80 <= byte <= 0x9f for byte in raw)):
        return decoded.strip()
    return name.strip()


def read_midi(path: str | Path) -> Song:
    import mido
    path = Path(path)
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("MIDI 文件不能超过 10 MB。")
    # 先按单字节编码无损读取，再逐条解码名称，兼容同一文件内混用编码。
    midi = mido.MidiFile(path, charset="latin1")
    if midi.type == 2 or midi.ticks_per_beat <= 0:
        raise ValueError("请使用 PPQ 时间格式的 MIDI 0／1 型文件，不支持独立序列或 SMPTE 时间格式。")
    tempos, events, tracks, last_tick = [(0, -1, 500000)], [], {}, 0
    count = 0
    for track_index, track in enumerate(midi.tracks):
        tick, name = 0, f"音轨 {track_index + 1}"
        for msg in track:
            count += 1
            if count > 200000:
                raise ValueError("MIDI 事件过多，请先导出需要的旋律音轨。")
            tick += msg.time
            if msg.type == "track_name":
                decoded = _decode_track_name(msg.name)
                if decoded:
                    name = decoded
            if msg.type == "set_tempo":
                if msg.tempo <= 0:
                    raise ValueError("MIDI 中包含无效速度。")
                tempos.append((tick, count, msg.tempo))
            if msg.type in ("note_on", "note_off") and msg.channel != 9:
                events.append((tick, count, track_index, msg))
        tracks[track_index] = name
        last_tick = max(last_tick, tick)
    # 先建立全局速度表，使其他音轨上的变速也能正确影响旋律。
    ticks, times, rates = [0], [0.0], [500000]
    for tick, _, tempo in sorted(tempos):
        elapsed = times[-1] + (tick - ticks[-1]) * rates[-1] / midi.ticks_per_beat / 1_000_000
        ticks.append(tick)
        times.append(elapsed)
        rates.append(tempo)

    def seconds(tick):
        index = bisect_right(ticks, tick) - 1
        return times[index] + (tick-ticks[index]) * rates[index] / midi.ticks_per_beat / 1_000_000

    duration = seconds(last_tick)
    if duration > 1800:
        raise ValueError("第一版支持最长 30 分钟的 MIDI。")
    active, notes = defaultdict(deque), []
    for tick, _, track, msg in sorted(events):
        key = (track, msg.channel, msg.note)
        if msg.type == "note_on" and msg.velocity > 0:
            active[key].append(tick)
        elif active[key]:
            start = active[key].popleft()
            if tick > start:
                notes.append(Note(seconds(start), seconds(tick), msg.note, track))
    for (track, _, pitch), starts in active.items():
        for start in starts:
            if last_tick > start:
                notes.append(Note(seconds(start), seconds(last_tick), pitch, track))
    if not notes:
        raise ValueError("没有找到旋律音符，打击乐通道已自动忽略。")
    if len(notes) > 30000:
        raise ValueError("旋律音符超过 30000 个，请先精简 MIDI。")
    used = {n.track for n in notes}
    return Song(path.stem, sorted(notes, key=lambda n: (n.start, n.pitch)), {k: v for k, v in tracks.items() if k in used}, duration)


def monophonic(notes: list[Note]) -> list[Note]:
    # 每个时间段取仍在发声的最高音，避免不同八度修饰键互相冲突。
    import heapq
    events = defaultdict(list)
    for index, note in enumerate(notes):
        events[note.start].append((True, index))
        events[note.end].append((False, index))
    heap, active, result = [], set(), []
    previous, winner = None, None
    last_id = None
    for time in sorted(events):
        if previous is not None and winner is not None and time > previous:
            source = notes[winner]
            if result and last_id == winner and abs(result[-1].end-previous) < 1e-8:
                result[-1] = replace(source, start=result[-1].start, end=time)
            else:
                result.append(replace(source, start=previous, end=time))
            last_id = winner
        for on, index in events[time]:
            if on:
                active.add(index)
                heapq.heappush(heap, (-notes[index].pitch, -notes[index].start, index))
            else:
                active.discard(index)
        while heap and heap[0][2] not in active:
            heapq.heappop(heap)
        winner = heap[0][2] if heap else None
        previous = time
    return result


def recommend_track(song: Song) -> int:
    """优先有旋律名称的音轨，否则从音符较充足的音轨中推荐高声部。"""
    groups = defaultdict(list)
    for note in song.notes:
        groups[note.track].append(note)
    largest = max(len(notes) for notes in groups.values())
    candidates = [track for track, notes in groups.items() if len(notes) >= max(1, largest * 0.2)]

    def score(track):
        name = song.tracks.get(track, "").lower()
        named = any(word in name for word in ("melody", "vocal", "lead", "主旋律", "人声"))
        notes = groups[track]
        weights = [min(n.end-n.start, 1.0) for n in notes]
        return named, sum(n.pitch*w for n, w in zip(notes, weights))/sum(weights), -track

    return max(candidates, key=score)


def piano_melody(notes: list[Note]) -> list[Note]:
    """整理钢琴高声部，避免伴奏尾音回填和和弦手指错位产生的碎音。"""
    groups = []
    for note in sorted(notes, key=lambda n: (n.start, n.pitch)):
        # 只合并重叠长音的近同时起音；真正的快速短音、重复音仍保留。
        if (groups and note.start-groups[-1][0].start <= 0.060
                and note.pitch not in {n.pitch for n in groups[-1]}
                and note.end-note.start >= 0.1
                and all(n.end-n.start >= 0.1 and n.end > note.start for n in groups[-1])):
            groups[-1].append(note)
        else:
            groups.append([note])
    result = []
    for group in groups:
        note = max(group, key=lambda n: (n.pitch, n.start))
        if result and note.start < result[-1].end:
            previous = result[-1]
            # 下行连奏允许少量重叠；持续高音下的新伴奏不打断旋律。
            if note.pitch < previous.pitch and previous.end-note.start > 0.080:
                continue
            if (note.start <= previous.start or
                    (note.start-previous.start < 0.040 and previous.end-previous.start >= 0.1)):
                result.pop()
            else:
                result[-1] = replace(previous, end=note.start)
        result.append(note)
    return result


def bridge_short_gaps(notes: list[Note]) -> tuple[list[Note], int]:
    result, count = [], 0
    for index, note in enumerate(notes):
        if index+1 < len(notes):
            gap = notes[index+1].start-note.end
            # 仅连接短间隙，保留长休止和明显的短促奏法。
            if 1e-8 < gap <= min(0.120, (note.end-note.start)*0.35):
                note = replace(note, end=notes[index+1].start)
                count += 1
        result.append(note)
    return result, count


def fingerings(mapping: Mapping) -> dict[int, Fingering]:
    mapping.validate()
    result = {}
    # 优先不用鼠标的指法，其次仅八度键，最后半音组合。
    choices = [(0, ()), (mapping.low, ("left",)), (mapping.high, ("right",))]
    choices += [(offset + mapping.half, buttons + ("middle",)) for offset, buttons in list(choices)]
    for offset, buttons in choices:
        for key, degree in zip(mapping.keys.lower(), (*SCALE, 12)):
            pitch = mapping.base + degree + offset
            if 0 <= pitch <= 127:
                result.setdefault(pitch, Fingering(key, buttons, pitch))
    return result


def validate_segments(segments, duration):
    """片段按原曲秒数保存，空列表表示全曲，保留用户编排的先后顺序。"""
    if not isinstance(segments, (list, tuple)) or len(segments) > 100:
        raise ValueError("每首曲目最多支持 100 个片段。")
    result = []
    for index, segment in enumerate(segments, 1):
        if not isinstance(segment, (list, tuple)) or len(segment) != 2:
            raise ValueError(f"第 {index} 个片段需要起点和终点。")
        start, end = segment
        if not all(type(value) in (int, float) and math.isfinite(value) for value in (start, end)):
            raise ValueError(f"第 {index} 个片段的时间必须是有效数字。")
        if not 0 <= start < end <= duration:
            raise ValueError(f"第 {index} 个片段需满足 0 ≤ 起点 < 终点 ≤ 原曲时长。")
        result.append((float(start), float(end)))
    return result


def segment_source_position(position, segments, duration):
    """把原速的拼接进度还原为原曲位置；片段交界处属于下一片段。"""
    remaining = max(0.0, position)
    for start, end in segments:
        length = end-start
        if remaining < length:
            return start+remaining
        remaining -= length
    return segments[-1][1] if segments else min(duration, remaining)


def compile_plan(song: Song, mapping: Mapping, track: int | str | None = None, speed: float = 1, transpose: int = 0, style: str = "original", segments=None) -> Plan:
    if not math.isfinite(speed) or not 0.25 <= speed <= 2:
        raise ValueError("速度倍率需在 0.25～2.00 之间。")
    if not -24 <= transpose <= 24:
        raise ValueError("移调需在 -24～24 半音之间。")
    if style not in ("original", "piano"):
        raise ValueError("请选择原谱分音或钢琴适配连奏。")
    segments = validate_segments([] if segments is None else segments, song.duration)
    if track == "auto":
        track = recommend_track(song)
    lookup = fingerings(mapping)
    source = [n for n in song.notes if track is None or n.track == track]
    if not source:
        raise ValueError("所选音轨没有音符。")
    melody = monophonic(source)
    cleaned, bridged = 0, 0
    if style == "piano":
        adapted = piano_melody(source)
        cleaned = max(0, len(melody)-len(adapted))
        melody, bridged = bridge_short_gaps(adapted)
    duration, source_count = song.duration, len(source)
    if segments:
        selected, duration, source_count = [], 0.0, 0
        # 先整理完整旋律再裁切，片段起点不会让已被过滤的伴奏重新发声。
        for start, end in segments:
            for note in melody:
                if note.start < end and note.end > start:
                    selected.append(replace(note, start=duration+max(note.start, start)-start,
                                            end=duration+min(note.end, end)-start))
            source_count += sum(note.start < end and note.end > start for note in source)
            duration += end-start
        melody = selected
        if not melody:
            raise ValueError("所选片段在当前音轨和演奏方式下没有可演奏的音符，请调整范围或音轨。")
    result, folded = [], 0
    for note in melody:
        pitch = note.pitch + transpose
        fingering = lookup.get(pitch)
        if fingering is None:
            candidates = [p for p in lookup if p % 12 == pitch % 12]
            if not candidates:
                raise ValueError(f"当前映射无法演奏 {pitch_name(pitch)}，请调整鼠标半音／八度设置。")
            fingering = lookup[min(candidates, key=lambda p: (abs(p-pitch), p))]
            folded += 1
        result.append(PlayNote(note.start/speed, note.end/speed, pitch, fingering, note.legato))
    return Plan(result, duration/speed, folded, source_count, style, cleaned, bridged, track)


DEMO_SCORES = {
    "小星星": (100, "1 1 5 5 6 6 5:2 | 4 4 3 3 2 2 1:2 | 5 5 4 4 3 3 2:2 | 5 5 4 4 3 3 2:2 | 1 1 5 5 6 6 5:2 | 4 4 3 3 2 2 1:2"),
    "欢乐颂": (112, "3 3 4 5 | 5 4 3 2 | 1 1 2 3 | 3:1.5 2:0.5 2:2 | 3 3 4 5 | 5 4 3 2 | 1 1 2 3 | 2:1.5 1:0.5 1:2"),
    "两只老虎": (110, "1 2 3 1 | 1 2 3 1 | 3 4 5:2 | 3 4 5:2 | 5:0.5 6:0.5 5:0.5 4:0.5 3 1 | 5:0.5 6:0.5 5:0.5 4:0.5 3 1 | 1 -5 1:2 | 1 -5 1:2"),
    "乐曲解锁-夜莺": (100, "7 6 7 6 | 3 5 4"),
    "乐曲解锁-守望": (100, "5 1 2 3 | 5 4 3 1 | 2 3"),
    "乐曲解锁-风起": (100, "6 7 1 2 | 1 7 1"),
    "乐曲解锁-破晓": (100, "7 6 3 6 | 7 6 7 +1 | +4 +3 +4"),
    "音阶校准 · 低中高与半音": (90, "-1 -2 -3 -4 -5 -6 -7 | 1 2 3 4 5 6 7 | +1 +2 +3 +4 +5 +6 +7 | 1 #1 2 #2 3 4 #4 5 #5 6 #6 7 +1:2"),
}
