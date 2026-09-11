"""将随附简谱导出为可导入的标准 MIDI 示例。"""
from pathlib import Path
import sys
import mido
from music import DEMO_SCORES, parse_jianpu


def export(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for title, (bpm, score) in DEMO_SCORES.items():
        song = parse_jianpu(score, bpm, title)
        midi = mido.MidiFile(type=0, ticks_per_beat=480)
        track = mido.MidiTrack()
        midi.tracks.append(track)
        tempo = mido.bpm2tempo(bpm)
        track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
        track.append(mido.MetaMessage("track_name", name="Melody", time=0))
        events = []
        for note in song.notes:
            start = round(mido.second2tick(note.start, midi.ticks_per_beat, tempo))
            end = round(mido.second2tick(note.end, midi.ticks_per_beat, tempo))
            events.extend([(start, 1, note.pitch), (end, 0, note.pitch)])
        previous = 0
        for tick, on, pitch in sorted(events):
            track.append(mido.Message("note_on" if on else "note_off", note=pitch, velocity=90 if on else 0, time=tick-previous))
            previous = tick
        track.append(mido.MetaMessage("end_of_track", time=0))
        midi.save(destination / (title + ".mid"))


if __name__ == "__main__":
    export(sys.argv[1] if len(sys.argv) > 1 else "示例 MIDI")
