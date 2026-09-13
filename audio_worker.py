"""独立扒谱引擎：解码音频、分离人声并识别音符，不访问桌面或游戏输入。"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys
import traceback


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def transcribe(job):
    """模型仅在引擎进程加载；读取限定片段，避免整首解码占满内存。"""
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    folder = Path(job["folder"])
    def report(message):
        write_json(folder / "progress.json", {"message": message})

    report("正在解码音频片段…")
    with sf.SoundFile(job["input"]) as audio:
        if not 8000 <= audio.samplerate <= 192000 or not 1 <= audio.channels <= 8:
            raise ValueError("音频采样率或声道数不支持，请换用常规 MP3 / WAV 文件。")
        total = len(audio) / audio.samplerate
        start = job["start"]
        duration = total - start if job["duration"] is None else min(job["duration"], total - start)
        if duration <= 0:
            raise ValueError("起点已超过音频末尾，请减小起点。")
        if duration > 600:
            raise ValueError("一次最多提取 10 分钟，请填写片段时长。")
        audio.seek(round(start * audio.samplerate))
        wave = audio.read(round(duration * audio.samplerate), dtype="float32", always_2d=True)
        rate = audio.samplerate
    if not len(wave) or not np.isfinite(wave).all() or np.max(np.abs(wave)) < 0.0001:
        raise ValueError("此片段没有可识别的声音，请选择有旋律的部分。")
    wave = wave[:, :2]
    if rate != 44100:
        factor = math.gcd(rate, 44100)
        wave = resample_poly(wave, 44100 // factor, rate // factor, axis=0).astype(np.float32)
    duration = len(wave) / 44100
    sf.write(folder / "original.wav", wave, 44100)

    if job["mode"] == "vocal":
        report("正在加载人声分离模型…")
        import torch
        from demucs.pretrained import get_model
        from demucs.apply import apply_model
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        model_dir = Path(job["models"])
        if not (model_dir / "htdemucs.yaml").is_file():
            raise ValueError("缺少人声分离模型，请使用带 audio-engine 文件夹的完整扒谱版。")
        model = get_model("htdemucs", repo=model_dir)
        mix = torch.from_numpy(wave.T.copy())
        if mix.shape[0] == 1:
            mix = mix.repeat(2, 1)
        reference = mix.mean(0)
        mean, std = reference.mean(), reference.std().clamp_min(1e-6)
        mix = (mix - mean) / std
        report("正在分离人声，长片段需要稍等；可随时取消…")
        with torch.inference_mode():
            stems = apply_model(model, mix[None], device="cpu", shifts=0, split=True,
                                overlap=0.25, segment=7.5, num_workers=0)[0]
        wave = (stems[model.sources.index("vocals")] * std + mean).numpy().T
        del stems, model, mix
    mono = wave.mean(axis=1)
    if job["mode"] == "vocal":
        from scipy.ndimage import uniform_filter1d
        # 识别模型会把每个小窗归一化，先压掉分离后极弱的伴奏残留，避免静音变成低音。
        energy = np.sqrt(np.maximum(0, uniform_filter1d(mono * mono, size=4410)))
        floor = max(0.0001, float(np.percentile(energy, 99)) * 0.02)
        mono = mono * np.clip((energy - floor) / floor, 0, 1)
    if np.max(np.abs(mono)) < 0.0001:
        raise ValueError("此片段没有检测到清晰人声，可调整片段或改用独奏模式。")
    sf.write(folder / "melody.wav", mono, 44100)
    report("正在加载音高识别模型…")
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import Model, predict
    model = Model(ICASSP_2022_MODEL_PATH)
    report("正在识别音高和时值…")
    _, _, events = predict(folder / "melody.wav", model_or_model_path=model,
                           onset_threshold=0.55, frame_threshold=0.30, minimum_note_length=120,
                           minimum_frequency=65.4, maximum_frequency=2093.1,
                           multiple_pitch_bends=False)
    notes = [[float(a), float(b), int(p), float(v)] for a, b, p, v, _ in events]
    if not notes:
        raise ValueError("未识别到稳定旋律，请选择更清晰的片段或改用独奏模式。")
    if len(notes) > 60000:
        raise ValueError("识别音符过多，请缩短片段。")
    write_json(folder / "result.json", {"duration": duration, "notes": notes})
    report("音符识别完成，正在整理曲谱…")


def main():
    job_path = Path(sys.argv[1])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    try:
        transcribe(job)
    except Exception as error:
        write_json(Path(job["folder"]) / "error.json", {"message": str(error) or type(error).__name__})
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
