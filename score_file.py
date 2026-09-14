"""曲谱文件读取、旧格式兼容及导入校验，不改写源文件。"""
import json
from pathlib import Path

from cloud_score import MAX_SCORE_BYTES, from_song, to_song
from music import parse_jianpu, parse_jianpu_space


def read_score_data(path, maximum=10 * 1024 * 1024):
    """本地沿用 10 MB 上限；导入和下载可使用交换格式的 2 MB 上限。"""
    with Path(path).open("rb") as stream:
        body = stream.read(maximum + 1)
    if len(body) > maximum:
        raise ValueError(f"曲谱 JSON 不能超过 {maximum // (1024 * 1024)} MB")
    data = json.loads(body.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("曲谱 JSON 必须是对象")
    return data


def score_from_data(data):
    """仅没有版本字段的文件按旧版文本简谱解释，未知版本不能回退。"""
    if "version" in data:
        return to_song(data)
    if not isinstance(data.get("title"), str) or not isinstance(data.get("score"), str):
        raise ValueError("旧版简谱需要有效的曲名和谱文")
    try:
        bpm = float(data["bpm"])
    except (KeyError, ValueError, TypeError, OverflowError):
        raise ValueError("旧版简谱需要有效的 BPM") from None
    return parse_jianpu(data["score"], bpm, data["title"])


def validate_score_file(path):
    """导入时核对音符和编辑附注，既有曲库读取仍允许编辑器恢复过期附注。"""
    data = read_score_data(path, MAX_SCORE_BYTES)
    song = score_from_data(data)
    editor = data.get("editor")
    if editor is not None:
        if not isinstance(editor, dict) or editor.get("style", "original") not in ("original", "piano"):
            raise ValueError("曲谱编辑信息格式不正确")
        try:
            if editor.get("format") == "jianpu_space":
                parsed = parse_jianpu_space(editor["score"], song.title, mode=editor.get("mode", "score"))[0]
            else:
                parsed = parse_jianpu(editor["score"], float(editor["bpm"]), song.title, precise=True)
            if from_song(parsed) != from_song(song):
                raise ValueError("曲谱的原谱文字与音符不一致")
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("曲谱编辑信息缺少有效的谱文或速度") from error
    return song
