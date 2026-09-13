"""三端共用的云端曲谱格式：整数毫秒、完整音符及音轨编号。"""
from __future__ import annotations

import hashlib
import json


MAX_SCORE_BYTES = 2 * 1024 * 1024


def normalize_score(value):
    """严格校验交换格式，不把服务器数据直接交给播放器。"""
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("不支持的云端曲谱版本")
    title, duration, notes = value.get("title"), value.get("duration"), value.get("notes")
    if not isinstance(title, str) or not title.strip() or len(title) > 100 or any(ord(c) < 32 for c in title):
        raise ValueError("曲名需为 1～100 个字符")
    if type(duration) is not int or not 1 <= duration <= 1800000:
        raise ValueError("曲目时长需在 30 分钟以内")
    if not isinstance(notes, list) or not 1 <= len(notes) <= 30000:
        raise ValueError("曲谱需包含 1～30000 个音符")
    for note in notes:
        if not isinstance(note, list) or len(note) != 4 or any(type(n) is not int for n in note):
            raise ValueError("音符需包含起点、终点、音高和音轨四个整数")
        start, end, pitch, track = note
        if not 0 <= start < end <= duration or not 0 <= pitch <= 127 or not 0 <= track <= 65535:
            raise ValueError("音符时值、音高或音轨越界")
    return {"version": 1, "title": title.strip(), "duration": duration, "notes": sorted(notes)}


def score_id(score):
    """内容一致的曲谱拥有同一编号，名称单独保存在账号曲库。"""
    score = normalize_score(score)
    content = json.dumps([score["duration"], score["notes"]], separators=(",", ":"))
    return hashlib.sha256(content.encode()).hexdigest()


def from_song(song):
    """桌面浮点秒转换为交换格式的整数毫秒。"""
    notes = [[round(n.start * 1000), max(round(n.start * 1000) + 1, round(n.end * 1000)), n.pitch, n.track]
             for n in song.notes]
    return normalize_score({"version": 1, "title": song.title[:100],
                            "duration": max(round(song.duration * 1000), max(n[1] for n in notes)), "notes": notes})


def to_song(value):
    """延迟导入桌面模型，使后端不依赖 MIDI 或 Windows。"""
    from music import Note, Song
    value = normalize_score(value)
    tracks = {n[3]: f"音轨 {n[3] + 1}" for n in value["notes"]}
    return Song(value["title"], [Note(a / 1000, b / 1000, p, t) for a, b, p, t in value["notes"]],
                tracks, value["duration"] / 1000)
