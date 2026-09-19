package top.aiygzn.melodica;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.TreeMap;
import java.util.TreeSet;

/** 桌面版的旋律整理、连奏和片段编排；时间均为原曲毫秒。 */
public final class ScoreTools {
    private ScoreTools() { }
    static Score.Note copy(Score.Note n, long start, long end, boolean legato) {
        return new Score.Note(start, end, n.pitch, n.track, legato);
    }
    public static Score melody(Score score, int track, boolean piano) {
        if (track == -2) track = score.recommendedTrack();
        List<Score.Note> input = new ArrayList<>();
        for (Score.Note n : score.notes) if (track < 0 || n.track == track) input.add(n);
        return new Score(score.title, piano ? piano(input) : original(input), score.duration);
    }
    private static List<Score.Note> original(List<Score.Note> input) {
        TreeMap<Long, List<Integer>> events = new TreeMap<>();
        for (int i = 0; i < input.size(); i++) {
            events.computeIfAbsent(input.get(i).start, k -> new ArrayList<>()).add(i + 1);
            events.computeIfAbsent(input.get(i).end, k -> new ArrayList<>()).add(-i - 1);
        }
        TreeSet<Integer> active = new TreeSet<>(Comparator.<Integer>comparingInt(i -> input.get(i).pitch).reversed()
            .thenComparing(Comparator.<Integer>comparingLong(i -> input.get(i).start).reversed()).thenComparingInt(i -> i));
        List<Score.Note> output = new ArrayList<>(); long previous = 0; int last = -1;
        for (var event : events.entrySet()) {
            if (!active.isEmpty() && event.getKey() > previous) {
                int winner = active.first(); Score.Note n = input.get(winner);
                long start = previous;
                if (last == winner && !output.isEmpty() && output.get(output.size() - 1).end == previous)
                    start = output.remove(output.size() - 1).start;
                output.add(copy(n, start, event.getKey(), n.legato)); last = winner;
            }
            for (int index : event.getValue()) { if (index > 0) active.add(index - 1); else active.remove(-index - 1); }
            previous = event.getKey();
        }
        return output;
    }
    private static List<Score.Note> piano(List<Score.Note> input) {
        input.sort(Comparator.comparingLong((Score.Note n) -> n.start).thenComparingInt(n -> n.pitch));
        List<List<Score.Note>> groups = new ArrayList<>();
        for (Score.Note n : input) {
            List<Score.Note> group = groups.isEmpty() ? null : groups.get(groups.size() - 1);
            boolean join = group != null && n.start - group.get(0).start <= 60 && n.end - n.start >= 100;
            if (join) for (Score.Note old : group)
                if (old.pitch == n.pitch || old.end - old.start < 100 || old.end <= n.start) { join = false; break; }
            if (!join) { group = new ArrayList<>(); groups.add(group); }
            group.add(n);
        }
        List<Score.Note> output = new ArrayList<>();
        for (List<Score.Note> group : groups) {
            Score.Note n = group.stream().max(Comparator.comparingInt((Score.Note v) -> v.pitch).thenComparingLong(v -> v.start)).get();
            if (!output.isEmpty()) {
                Score.Note previous = output.get(output.size() - 1);
                if (n.start < previous.end) {
                    if (n.pitch < previous.pitch && previous.end - n.start > 80) continue;
                    output.remove(output.size() - 1);
                    if (n.start > previous.start && !(n.start - previous.start < 40 && previous.end - previous.start >= 100))
                        output.add(copy(previous, previous.start, n.start, true));
                }
            }
            output.add(copy(n, n.start, n.end, true));
        }
        for (int i = 0; i + 1 < output.size(); i++) {
            Score.Note n = output.get(i); long next = output.get(i + 1).start, gap = next - n.end;
            if (gap > 0 && gap <= Math.min(120, (n.end - n.start) * .35)) output.set(i, copy(n, n.start, next, true));
        }
        return output;
    }
    public static final class Segment {
        public final long start, end;
        public final int repeat;
        public Segment(long start, long end, int repeat) {
            if (start < 0 || end <= start || repeat < 1 || repeat > 20) throw new IllegalArgumentException("片段需满足起点 < 终点，重复 1～20 次");
            this.start = start; this.end = end; this.repeat = repeat;
        }
    }
    public static Score arrange(Score score, List<Segment> segments) {
        if (segments.isEmpty()) return score;
        if (segments.size() > 100) throw new IllegalArgumentException("最多保存 100 个片段");
        List<Score.Note> output = new ArrayList<>(); long cursor = 0;
        for (Segment segment : segments) {
            if (segment.end > score.duration) throw new IllegalArgumentException("片段终点不能超过原曲时长");
            if (cursor + (segment.end - segment.start) * segment.repeat > 1800000) throw new IllegalArgumentException("编排后不能超过 30 分钟");
            for (int turn = 0; turn < segment.repeat; turn++) {
                for (Score.Note n : score.notes) {
                    if (n.start >= segment.end) break;
                    if (n.end > segment.start) output.add(copy(n, cursor + Math.max(n.start, segment.start) - segment.start,
                        cursor + Math.min(n.end, segment.end) - segment.start, n.legato));
                    if (output.size() > 30000) throw new IllegalArgumentException("编排后不能超过 30000 个音符");
                }
                cursor += segment.end - segment.start;
            }
        }
        return new Score(score.title, output, cursor);
    }
    public static long releaseAt(Score.Note note) {
        // 安卓手势每个音仍需释放；连奏缩小气口，重复音继续重新触发。
        return note.end - Math.min(note.legato ? 12 : 25, Math.max(1, (note.end - note.start) / 10));
    }
}
