package top.aiygzn.melodica;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** 与安卓界面无关的曲谱、旋律整理和八键映射。 */
public final class Score {
    public static final int[] SCALE = {0, 2, 4, 5, 7, 9, 11, 12};
    public static final int LOW = 8, HIGH = 9, HALF = 10, NATURAL = 11;
    public static final String[] LABELS = {"1", "2", "3", "4", "5", "6", "7", "高1", "降调", "升调", "半音", "自然音"};
    public static final int[] CALIBRATION_ORDER = {0, 1, 2, 3, 4, 5, 6, 7, HALF, HIGH, NATURAL, LOW};
    public static final String STAR = "1 1 5 5 6 6 5:2 | 4 4 3 3 2 2 1:2 | 5 5 4 4 3 3 2:2 | 5 5 4 4 3 3 2:2 | 1 1 5 5 6 6 5:2 | 4 4 3 3 2 2 1:2";
    public static final String UNLOCK_NIGHTINGALE = "7 6 7 6 | 3 5 4";
    public static final String UNLOCK_WATCH = "5 1 2 3 | 5 4 3 1 | 2 3";
    public static final String UNLOCK_WIND = "6 7 1 2 | 1 7 1";
    public static final String UNLOCK_DAWN = "7 6 3 6 | 7 6 7 +1 | +4 +3 +4";
    public static final class Note {
        public final long start, end;
        public final int pitch, track;
        public Note(long start, long end, int pitch, int track) {
            if (start < 0 || end <= start || end > 1800000 || pitch < 0 || pitch > 127)
                throw new IllegalArgumentException("音符时值或音高越界（最长 30 分钟）");
            this.start = start; this.end = end; this.pitch = pitch; this.track = track;
        }
    }
    public final String title;
    public final List<Note> notes;
    public final long duration;
    public Score(String title, List<Note> notes, long duration) {
        if (notes.isEmpty() || notes.size() > 30000) throw new IllegalArgumentException("曲谱需包含 1～30000 个音符");
        this.title = title;
        ArrayList<Note> sorted = new ArrayList<>(notes);
        sorted.sort(Comparator.comparingLong(n -> n.start));
        this.notes = java.util.Collections.unmodifiableList(sorted);
        this.duration = Math.max(duration, sorted.stream().mapToLong(n -> n.end).max().orElse(0));
        if (this.duration > 1800000) throw new IllegalArgumentException("曲目不能超过 30 分钟");
    }
    public static Score jianpu(String text, double bpm, String title) {
        if (!Double.isFinite(bpm) || bpm < 20 || bpm > 300) throw new IllegalArgumentException("速度需在 20～300 BPM 之间");
        String[] tokens = text.replaceAll("//[^\n]*", "").replace('|', ' ').replace('，', ' ').trim().split("\\s+");
        if (tokens.length > 30000) throw new IllegalArgumentException("简谱最多 30000 项");
        Pattern pattern = Pattern.compile("([+-]?)([#b]?)([0-7])(?::(\\d+(?:/\\d+|\\.\\d+)?))?");
        List<Note> notes = new ArrayList<>();
        double cursor = 0;
        for (String token : tokens) {
            Matcher match = pattern.matcher(token);
            if (!match.matches()) throw new IllegalArgumentException("无法识别「" + token + "」，请用空格分隔音符");
            double beats = 1;
            if (match.group(4) != null) {
                String[] fraction = match.group(4).split("/");
                beats = Double.parseDouble(fraction[0]);
                if (fraction.length == 2) beats /= Double.parseDouble(fraction[1]);
            }
            if (!Double.isFinite(beats) || beats < 1.0 / 32 || beats > 64) throw new IllegalArgumentException("音符时值需为 1/32～64 拍");
            int degree = Integer.parseInt(match.group(3));
            double end = cursor + beats * 60000 / bpm;
            if (degree == 0) {
                if (!match.group(1).isEmpty() || !match.group(2).isEmpty()) throw new IllegalArgumentException("休止符不能带升降号或八度");
            } else {
                int pitch = 60 + SCALE[degree - 1] + (match.group(1).equals("+") ? 12 : match.group(1).equals("-") ? -12 : 0)
                    + (match.group(2).equals("#") ? 1 : match.group(2).equals("b") ? -1 : 0);
                notes.add(new Note(Math.round(cursor), Math.round(end), pitch, 0));
            }
            cursor = end;
            if (cursor > 1800000) throw new IllegalArgumentException("曲目不能超过 30 分钟");
        }
        return new Score(title, notes, Math.round(cursor));
    }
    public int recommendedTrack() {
        TreeMap<Integer, List<Note>> tracks = new TreeMap<>();
        for (Note n : notes) tracks.computeIfAbsent(n.track, k -> new ArrayList<>()).add(n);
        int maxCount = tracks.values().stream().mapToInt(List::size).max().orElse(1);
        int selected = tracks.firstKey(); double best = -1;
        for (var entry : tracks.entrySet()) {
            if (entry.getValue().size() < Math.min(8, maxCount) || entry.getValue().size() < maxCount * .15) continue;
            double mean = entry.getValue().stream().mapToInt(n -> n.pitch).average().orElse(0);
            if (mean > best) { best = mean; selected = entry.getKey(); }
        }
        return selected;
    }
    public Score melody(int track) {
        // 近同时和弦只保留高声部，不在高音结束后补吹旧伴奏尾音。
        List<Note> input = new ArrayList<>();
        for (Note n : notes) if (track < 0 || n.track == track) input.add(n);
        List<Note> grouped = new ArrayList<>();
        for (int i = 0; i < input.size();) {
            Note first = input.get(i++), chosen = first;
            while (i < input.size() && input.get(i).start - first.start <= 30) {
                Note other = input.get(i++);
                if (other.pitch > chosen.pitch) chosen = other;
            }
            grouped.add(new Note(first.start, Math.max(first.start + 1, chosen.end), chosen.pitch, chosen.track));
        }
        List<Note> output = new ArrayList<>();
        for (int i = 0; i < grouped.size(); i++) {
            Note n = grouped.get(i);
            long end = i + 1 < grouped.size() ? Math.min(n.end, grouped.get(i + 1).start) : n.end;
            output.add(new Note(n.start, end, n.pitch, n.track));
        }
        return new Score(title, output, duration);
    }
    public static final class Fingering {
        public final int key, octave, half, pitch;
        Fingering(int key, int octave, int half, int pitch) { this.key = key; this.octave = octave; this.half = half; this.pitch = pitch; }
        public int tonePoint() { return octave < 0 ? LOW : octave > 0 ? HIGH : NATURAL; }
    }
    public static Fingering map(int pitch, int base, boolean low, boolean high, boolean half) {
        Fingering best = null; int cost = Integer.MAX_VALUE;
        for (int octave : new int[]{0, -12, 12}) {
            if (octave < 0 && !low || octave > 0 && !high) continue;
            for (int sharp = 0; sharp <= (half ? 1 : 0); sharp++) for (int key = 0; key < 8; key++) {
                int candidate = base + SCALE[key] + octave + sharp;
                int difference = Math.abs(candidate - pitch);
                if (difference % 12 != 0) continue;
                int score = difference * 100 + (octave == 0 ? 0 : 2) + sharp;
                if (score < cost) { cost = score; best = new Fingering(key, octave, sharp, candidate); }
            }
        }
        if (best == null) throw new IllegalArgumentException("当前映射范围无法表达曲目中的半音");
        return best;
    }
}
