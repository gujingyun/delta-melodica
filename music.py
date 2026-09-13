"""乐谱解析、单旋律整理与口风琴映射。"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict, deque
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
import math
import re

SCALE = (0, 2, 4, 5, 7, 9, 11)


@dataclass(frozen=True)
class Note:
    start: float
    end: float
    pitch: int
    track: int = 0


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
    tokens = clean.split()
    if len(tokens) > (60001 if precise else 30000):
        raise ValueError("乐谱最多支持 30000 个音符。")
    for token in tokens:
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
    if not notes:
        raise ValueError("乐谱中没有可演奏的音符。")
    if len(notes) > 30000:
        raise ValueError("乐谱最多支持 30000 个音符。")
    if cursor > 1800:
        raise ValueError("第一版支持最长 30 分钟的曲目。")
    return Song(title.strip() or "自定义简谱", notes, duration=cursor)


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

    for note in melody:
        start, end = round(note.start*bpm/60, 9), round(note.end*bpm/60, 9)
        if start > cursor:
            append_token("0", start-cursor)
        append_token(jianpu_pitch(note.pitch), max(0.000000001, end-start))
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
                result[-1] = Note(result[-1].start, time, source.pitch, source.track)
            else:
                result.append(Note(previous, time, source.pitch, source.track))
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
                result[-1] = Note(previous.start, note.start, previous.pitch, previous.track)
        result.append(note)
    return result


def bridge_short_gaps(notes: list[Note]) -> tuple[list[Note], int]:
    result, count = [], 0
    for index, note in enumerate(notes):
        if index+1 < len(notes):
            gap = notes[index+1].start-note.end
            # 仅连接短间隙，保留长休止和明显的短促奏法。
            if 1e-8 < gap <= min(0.120, (note.end-note.start)*0.35):
                note = Note(note.start, notes[index+1].start, note.pitch, note.track)
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
                    selected.append(Note(duration+max(note.start, start)-start,
                                         duration+min(note.end, end)-start, note.pitch, note.track))
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
        result.append(PlayNote(note.start/speed, note.end/speed, pitch, fingering))
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
