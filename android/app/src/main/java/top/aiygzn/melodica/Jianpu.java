package top.aiygzn.melodica;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** 与桌面一致的文字简谱规则，保留原文位置用于谱面点选和试听跟随。 */
public final class Jianpu {
    public static final Pattern KEY = Pattern.compile("/key\\(([A-Ga-g])([#b]?)([0-9]?)\\)");
    public static final Pattern NOTE = Pattern.compile("(#{1,2}|b{1,2}|n)?([0-7]|-)((?:'+|,+)?)(-+|=*_?)(\\.{0,2})");
    public static final Pattern PRECISE = Pattern.compile("(\\+{0,5}|-{1,5})([#b]?)([0-7])(?::(\\d+(?:/\\d+|\\.\\d+)?))?");
    private static final Pattern TEMPO = Pattern.compile("bpm\\s*[:=]?\\s*(\\d+(?:\\.\\d+)?)", Pattern.CASE_INSENSITIVE);
    private static final Pattern CHANGE = Pattern.compile("\\(([升降+\\-])(\\d+)key\\)", Pattern.CASE_INSENSITIVE);
    public static final class Span {
        public final int left, right;
        public final long start, end;
        Span(int left, int right, long start, long end) { this.left = left; this.right = right; this.start = start; this.end = end; }
    }
    public static final class Result {
        public final Score score;
        public final List<Span> spans;
        public final List<String> warnings;
        Result(Score score, List<Span> spans, List<String> warnings) { this.score = score; this.spans = spans; this.warnings = warnings; }
        public Result selection(int left, int right) {
            List<ScoreTools.Segment> ranges = new ArrayList<>(); List<Span> selected = new ArrayList<>(); long cursor = 0;
            for (Span span : spans) if (span.left < right && span.right > left) {
                if (span.left < left || span.right > right) throw new IllegalArgumentException("请选中完整音符，包括升降号、八度和时值");
                selected.add(new Span(span.left, span.right, cursor, cursor + span.end - span.start)); cursor += span.end - span.start;
                if (!ranges.isEmpty() && ranges.get(ranges.size() - 1).end == span.start) {
                    ScoreTools.Segment old = ranges.remove(ranges.size() - 1); ranges.add(new ScoreTools.Segment(old.start, span.end, 1));
                } else ranges.add(new ScoreTools.Segment(span.start, span.end, 1));
            }
            if (ranges.isEmpty()) throw new IllegalArgumentException("选中的内容没有可试听的音符");
            // 选段可含超过 100 次反复，独立于用户编排的片段数量限制。
            List<Score.Note> notes = new ArrayList<>(); cursor = 0;
            for (ScoreTools.Segment range : ranges) {
                for (Score.Note n : score.notes) {
                    if (n.start >= range.end) break;
                    if (n.end > range.start) notes.add(ScoreTools.copy(n, cursor + Math.max(n.start, range.start) - range.start,
                        cursor + Math.min(n.end, range.end) - range.start, n.legato));
                }
                cursor += range.end - range.start;
            }
            return new Result(new Score(score.title, notes, cursor), selected, warnings);
        }
    }
    private Jianpu() { }
    static int count(String text, char c) { int total = 0; for (int i = 0; i < text.length(); i++) if (text.charAt(i) == c) total++; return total; }
    static Matcher at(Pattern pattern, String text, int index) { Matcher m = pattern.matcher(text); m.region(index, text.length()); return m; }
    static void limit(String text) { if (text.length() > 200000) throw new IllegalArgumentException("简谱文字不能超过 20 万个字符"); }
    static IllegalArgumentException error(int line, String message) { return new IllegalArgumentException("第 " + line + " 行：" + message); }
    public static Result precise(String text, double bpm, String title) {
        limit(text);
        if (!Double.isFinite(bpm) || bpm < 20 || bpm > 300) throw new IllegalArgumentException("速度需在 20～300 BPM 之间");
        List<Score.Note> notes = new ArrayList<>(); List<Span> spans = new ArrayList<>(); List<Integer> slurs = new ArrayList<>(); double cursor = 0;
        Pattern token = Pattern.compile("//[^\\n]*|[()|，]|[^\\s()|，]+"); Matcher tokens = token.matcher(text);
        while (tokens.find()) {
            String item = tokens.group();
            if (item.startsWith("//") || item.equals("|") || item.equals("，")) continue;
            if (item.equals("(")) { if (slurs.size() >= 8) throw new IllegalArgumentException("连线最多嵌套 8 层"); slurs.add(notes.size()); continue; }
            if (item.equals(")")) {
                if (slurs.isEmpty() || slurs.get(slurs.size() - 1) == notes.size()) throw new IllegalArgumentException("连线括号不配对或没有音符");
                int start = slurs.remove(slurs.size() - 1);
                for (int i = start; i < notes.size(); i++) { Score.Note n = notes.get(i); notes.set(i, ScoreTools.copy(n, n.start, n.end, true)); }
                continue;
            }
            Matcher m = PRECISE.matcher(item);
            if (!m.matches()) throw new IllegalArgumentException("无法识别「" + item + "」，请用空格分隔音符");
            double beats = 1;
            if (m.group(4) != null) { String[] fraction = m.group(4).split("/"); beats = Double.parseDouble(fraction[0]); if (fraction.length == 2) beats /= Double.parseDouble(fraction[1]); }
            if (!Double.isFinite(beats) || beats <= 0 || beats > 9000) throw new IllegalArgumentException("音符时值必须大于零且不超过 9000 拍");
            double end = cursor + beats * 60000 / bpm; long startMs = Math.round(cursor), endMs = Math.round(end);
            if (endMs <= startMs) throw new IllegalArgumentException("音符时值小于本机支持的 1 毫秒，请检查时值");
            int degree = Integer.parseInt(m.group(3));
            if (degree == 0) { if (!m.group(1).isEmpty() || !m.group(2).isEmpty()) throw new IllegalArgumentException("休止符不能带八度或升降号"); }
            else notes.add(new Score.Note(startMs, endMs, 60 + Score.SCALE[degree - 1] + 12 * (count(m.group(1), '+') - count(m.group(1), '-'))
                + (m.group(2).equals("#") ? 1 : m.group(2).equals("b") ? -1 : 0), 0));
            spans.add(new Span(tokens.start(), tokens.end(), startMs, endMs)); cursor = end;
            if (end > 1800000 || notes.size() > 30000) throw new IllegalArgumentException("最多 30000 个音符、30 分钟");
        }
        if (!slurs.isEmpty()) throw new IllegalArgumentException("连线缺少右括号");
        return new Result(new Score(title, notes, Math.round(cursor)), spans, new ArrayList<>());
    }
    private static final class Event {
        String kind, degree; int line, position, left, right, offset; double value, beats;
        List<Event> body, first;
        Event(String kind, int line) { this.kind = kind; this.line = line; }
        Event(String kind, int line, double value) { this(kind, line); this.value = value; }
    }
    private static final class Structure {
        final List<Event> events; int index;
        Structure(List<Event> events) { this.events = events; }
        Event sequence(int depth, boolean explicit) {
            Event sequence = new Event("repeat", 0); sequence.body = new ArrayList<>();
            while (index < events.size()) {
                Event e = events.get(index++);
                if (e.kind.equals("repeat_start")) {
                    if (depth >= 8) throw error(e.line, "反复最多嵌套 8 层");
                    (sequence.first == null ? sequence.body : sequence.first).add(sequence(depth + 1, true));
                } else if (e.kind.equals("ending1")) {
                    if (sequence.first != null) throw error(e.line, "一房子重复出现"); sequence.first = new ArrayList<>();
                } else if (e.kind.equals("repeat_end")) {
                    if (sequence.body.isEmpty() || sequence.first != null && sequence.first.isEmpty()) throw error(e.line, "反复段或一房子为空");
                    if (sequence.first != null) {
                        if (index >= events.size() || !events.get(index++).kind.equals("ending2")) throw error(e.line, "一房子结束后需要 [2 二房子");
                        if (index >= events.size() || Arrays.asList("repeat_end", "ending1", "ending2").contains(events.get(index).kind)) throw error(e.line, "二房子没有内容");
                    }
                    if (explicit) return sequence;
                    int after = 0; for (int i = 0; i < sequence.body.size(); i++) if (sequence.body.get(i).kind.equals("repeat")) after = i + 1;
                    if (after == sequence.body.size()) throw error(e.line, "反复段为空，请补写 |: 起点");
                    Event repeated = new Event("repeat", e.line); repeated.body = new ArrayList<>(sequence.body.subList(after, sequence.body.size())); repeated.first = sequence.first;
                    sequence.body = new ArrayList<>(sequence.body.subList(0, after)); sequence.body.add(repeated); sequence.first = null;
                } else if (e.kind.equals("ending2")) throw error(e.line, "二房子前缺少 [1 和 :|");
                else (sequence.first == null ? sequence.body : sequence.first).add(e);
            }
            if (explicit || sequence.first != null) throw new IllegalArgumentException("反复段缺少结束符 :|");
            return sequence;
        }
    }
    static List<String> syllables(String text) {
        String han = "\\u2e80-\\u2fff\\u3005\\u3007\\u3021-\\u3029\\u3038-\\u303b\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff\\x{20000}-\\x{323af}";
        Pattern token = Pattern.compile("\"(?:[^\"]|\"\")+\"|[" + han + "][^-\\s" + han + "_*\"]*|[^\\s" + han + "_*\\-\"]+|[_*]|-");
        List<String> result = new ArrayList<>();
        for (int i = 0; i < text.length();) {
            if (Character.isWhitespace(text.charAt(i))) { i++; continue; }
            Matcher match = at(token, text, i); if (!match.lookingAt()) throw new IllegalArgumentException("歌词引号不完整，无法定位音节");
            if (!match.group().equals("-")) result.add(match.group()); i = match.end();
        }
        return result;
    }
    public static Result source(String text, String title, String mode) {
        limit(text); if (!mode.equals("score") && !mode.equals("source")) throw new IllegalArgumentException("请选择按谱面规则或跟随源站播放");
        List<Event> events = new ArrayList<>(); List<String> lyrics = new ArrayList<>(), warnings = new ArrayList<>();
        int offset = 0, number = 0, sourceCount = 0, keys = 0, lastKey = 60, annotations = 0; boolean chords = false, ignored = false;
        Pattern chord = Pattern.compile("[A-G][#b]?(?:(?:maj|min|m|dim|aug|sus|add)?(?:[2-9]|11|13)?)(?:/[A-G][#b]?)?");
        String[] symbols = {"|:", ":|", "[1", "[2", "(", ")", "~"};
        String[] kinds = {"repeat_start", "repeat_end", "ending1", "ending2", "slur_start", "slur_end", "tie"};
        for (String raw : text.split("\n", -1)) {
            number++; StringBuilder normalized = new StringBuilder(); List<Integer> positions = new ArrayList<>();
            for (int j = 0; j < raw.length();) {
                int width = Character.charCount(raw.codePointAt(j)); String item = Normalizer.normalize(raw.substring(j, j + width), Normalizer.Form.NFKC);
                normalized.append(item); for (int k = 0; k < item.length(); k++) positions.add(offset + j); j += width;
            }
            offset += raw.length() + 1; String line = normalized.toString();
            if (line.trim().startsWith("L:")) { lyrics.add(line.trim().substring(2)); continue; }
            if (line.trim().isEmpty()) continue;
            Matcher tempo = TEMPO.matcher(line.trim());
            if (tempo.matches()) { double bpm = Double.parseDouble(tempo.group(1)); if (bpm < 20 || bpm > 500) throw error(number, "速度需在 20～500 BPM 之间"); events.add(new Event("tempo", number, bpm)); continue; }
            boolean isChord = true; for (String item : line.trim().split("\\s+")) if (!chord.matcher(item).matches()) isChord = false;
            if (isChord) { chords = true; continue; }
            for (int i = 0; i < line.length();) {
                if (Character.isWhitespace(line.charAt(i))) { i++; continue; }
                Matcher key = at(KEY, line, i);
                if (key.lookingAt()) { lastKey = keyPitch(key); keys++; events.add(new Event("key", number, lastKey)); i = key.end(); continue; }
                if (mode.equals("source") && ":()~[]".indexOf(line.charAt(i)) >= 0) { ignored = true; i++; continue; }
                boolean structure = false;
                if (mode.equals("score")) for (int s = 0; s < symbols.length; s++) if (line.startsWith(symbols[s], i)) {
                    events.add(new Event(kinds[s], number)); i += symbols[s].length();
                    if (s == 1 && i < line.length() && line.charAt(i) == ':') { events.add(new Event("repeat_start", number)); i++; }
                    structure = true; break;
                }
                if (structure) continue;
                Matcher bar = at(Pattern.compile("\\|[|\\]]?"), line, i); if (bar.lookingAt()) { i = bar.end(); continue; }
                Matcher match = at(NOTE, line, i);
                if (!match.lookingAt()) {
                    Matcher annotation = at(Pattern.compile("[ac-mo-z]+"), line, i);
                    if (annotation.lookingAt()) { annotations++; if (annotations <= 3) warnings.add("第 " + number + " 行忽略字母「" + annotation.group() + "」，请对照原谱试听"); i = annotation.end(); continue; }
                    throw error(number, "第 " + (i + 1) + " 字附近「" + line.substring(i, Math.min(line.length(), i + 16)) + "」暂不支持，请核对原谱");
                }
                String accidental = match.group(1) == null ? "" : match.group(1), degree = match.group(2), octave = match.group(3), length = match.group(4);
                if ((degree.equals("0") || degree.equals("-")) && (!accidental.isEmpty() || !octave.isEmpty())) throw error(number, "休止或延音不能带升降号、八度点");
                if (length.length() > 63 || count(length, '=') > 5) throw error(number, "音符时值超出支持范围");
                Event event = new Event("note", number); event.degree = degree; event.position = sourceCount;
                event.offset = 12 * (count(octave, '\'') - count(octave, ',')) + count(accidental, '#') - count(accidental, 'b');
                event.beats = (length.startsWith("-") ? 1 + length.length() : Math.pow(.5, 2 * count(length, '=') + count(length, '_'))) * (2 - Math.pow(.5, match.group(5).length()));
                event.left = positions.get(i); event.right = positions.get(match.end() - 1) + 1; events.add(event);
                if (!degree.equals("0") && !degree.equals("-")) sourceCount++; i = match.end();
            }
        }
        Map<Integer, Integer> changes = new HashMap<>(); int position = 0;
        if (CHANGE.matcher(String.join("\n", lyrics)).find()) for (String line : lyrics) for (String item : syllables(line)) {
            Matcher change = CHANGE.matcher(item);
            if (change.find()) {
                int value; try { value = Integer.parseInt(change.group(2)); } catch (NumberFormatException e) { throw new IllegalArgumentException("歌词转调数值过大"); }
                if (value > 127) throw new IllegalArgumentException("歌词转调超出 MIDI 音域");
                changes.put(position, (change.group(1).equals("升") || change.group(1).equals("+") ? 1 : -1) * value);
                if (change.find()) throw new IllegalArgumentException("同一歌词音节含多个转调指令");
            }
            position++;
        }
        for (int pos : changes.keySet()) if (pos >= sourceCount) throw new IllegalArgumentException("歌词转调指令没有对应音符，请核对歌词占位");
        if (sourceCount > 30000) throw new IllegalArgumentException("最多支持 30000 个音符");
        Performance performance = new Performance(mode, changes, keys > 0 && mode.equals("source"), lastKey);
        performance.perform(mode.equals("score") ? new Structure(events).sequence(0, false).body : events);
        if (performance.pendingTie || !performance.slurs.isEmpty()) throw new IllegalArgumentException("连线缺少结束音符或右括号");
        if (performance.defaultTempo) warnings.add("未标速度的部分按 120 BPM 导入");
        if (performance.defaultKey) warnings.add("未标调号的部分按 1=C4 导入");
        if (!changes.isEmpty()) warnings.add("已按歌词处理 " + changes.size() + " 处转调");
        if (keys > 1) warnings.add(mode.equals("score") ? "已按标记位置处理段落调号" : "跟随源站：最后一个调号用于全曲");
        if (performance.repeats + performance.ties + performance.phrases > 0) warnings.add("展开 " + performance.repeats + " 个反复，处理 " + performance.ties + " 处延音、" + performance.phrases + " 处连奏");
        if (ignored) warnings.add("跟随源站：忽略反复、房子和圆弧／~ 连线标记");
        if (chords) warnings.add("独立和弦标记不演奏，仅导入主旋律");
        return new Result(new Score(title, performance.notes, Math.round(performance.cursor)), performance.spans, warnings);
    }
    private static final class Performance {
        final String mode; final Map<Integer, Integer> changes;
        final List<Score.Note> notes = new ArrayList<>(); final List<Span> spans = new ArrayList<>(); final List<long[]> slurs = new ArrayList<>();
        int base = 60, transpose, steps, repeats, ties, phrases; double bpm = 120, cursor;
        boolean keySet, tempoSet, previousNote, canExtend, pendingTie, defaultKey, defaultTempo;
        Performance(String mode, Map<Integer, Integer> changes, boolean keySet, int lastKey) {
            this.mode = mode; this.changes = changes; this.keySet = keySet; if (keySet) base = lastKey;
        }
        void boundary() { if (pendingTie || !slurs.isEmpty()) throw new IllegalArgumentException("连线不能跨越反复跳转或房子边界"); }
        void extend(long end, boolean legato) { Score.Note n = notes.remove(notes.size() - 1); notes.add(ScoreTools.copy(n, n.start, end, n.legato || legato)); }
        void perform(List<Event> items) {
            for (Event e : items) {
                if (++steps > 120000) throw new IllegalArgumentException("反复展开后的记谱过多，请减少嵌套");
                switch (e.kind) {
                    case "repeat": {
                        boundary(); int oldBase = base, oldTranspose = transpose; double oldBpm = bpm; boolean oldKey = keySet, oldTempo = tempoSet; repeats++;
                        for (int turn = 0; turn < 2; turn++) {
                            base = oldBase; transpose = oldTranspose; bpm = oldBpm; keySet = oldKey; tempoSet = oldTempo; previousNote = false; canExtend = false;
                            double before = cursor; perform(e.body); if (cursor == before) throw error(e.line, "反复段需要音符或休止"); boundary();
                            if (turn == 0 && e.first != null) { perform(e.first); boundary(); }
                        }
                        continue;
                    }
                    case "key": if (mode.equals("score")) { base = (int) e.value; keySet = true; transpose = 0; } continue;
                    case "tempo": bpm = e.value; tempoSet = true; continue;
                    case "slur_start":
                        if (slurs.size() >= 8 || pendingTie) throw error(e.line, "连线嵌套过深或与延音线交叉");
                        slurs.add(new long[]{notes.size(), Math.round(cursor)}); continue;
                    case "slur_end": {
                        if (slurs.isEmpty() || pendingTie) throw error(e.line, "连线括号不配对或延音未结束");
                        long[] group = slurs.remove(slurs.size() - 1); int start = (int) group[0];
                        if (start >= notes.size() || notes.get(start).start != group[1] || notes.get(notes.size() - 1).end != Math.round(cursor)) throw error(e.line, "连线两端需要音符");
                        boolean same = true; for (int i = start; i < notes.size(); i++) if (notes.get(i).pitch != notes.get(start).pitch) same = false;
                        if (same) {
                            for (int i = start; i + 1 < notes.size(); i++) if (notes.get(i).end != notes.get(i + 1).start) throw error(e.line, "同音延音线不能跨越休止");
                            Score.Note n = notes.get(start); notes.subList(start, notes.size()).clear(); notes.add(ScoreTools.copy(n, n.start, Math.round(cursor), true)); ties++;
                        } else { for (int i = start; i < notes.size(); i++) { Score.Note n = notes.get(i); notes.set(i, ScoreTools.copy(n, n.start, n.end, true)); } phrases++; }
                        continue;
                    }
                    case "tie": if (pendingTie || !previousNote) throw error(e.line, "延音线 ~ 前需要音符"); pendingTie = true; continue;
                    default: break;
                }
                double end = cursor + e.beats * 60000 / bpm; long startMs = Math.round(cursor), endMs = Math.round(end);
                if (endMs <= startMs) throw error(e.line, "音符短于 1 毫秒，请检查减时符号");
                spans.add(new Span(e.left, e.right, startMs, endMs)); defaultTempo |= !tempoSet; defaultKey |= !keySet;
                if (e.degree.equals("-")) {
                    if (!canExtend) throw error(e.line, "曲首或反复段首不能以延音线开头");
                    if (pendingTie) throw error(e.line, "~ 后需要同音高音符"); if (previousNote) extend(endMs, false);
                } else if (e.degree.equals("0")) {
                    if (pendingTie) throw error(e.line, "延音线不能连接休止符"); previousNote = false;
                } else {
                    transpose += changes.getOrDefault(e.position, 0); int pitch = base + Score.SCALE[Integer.parseInt(e.degree) - 1] + e.offset + transpose;
                    if (pitch < 0 || pitch > 127) throw error(e.line, "音高超出 MIDI 0～127 范围");
                    if (pendingTie) {
                        Score.Note previous = notes.get(notes.size() - 1);
                        if (previous.pitch != pitch || previous.end != startMs) throw error(e.line, "~ 只能连接相邻的同音高音符");
                        extend(endMs, true); pendingTie = false; ties++;
                    } else notes.add(new Score.Note(startMs, endMs, pitch, 0));
                    previousNote = true;
                }
                cursor = end; canExtend = true;
                if (cursor > 1800000 || notes.size() > 30000) throw new IllegalArgumentException("最多支持 30000 个音符、30 分钟");
            }
        }
    }
    static int keyPitch(Matcher match) {
        String letter = match.group(1).toUpperCase(Locale.ROOT); int octave = match.group(3).isEmpty() ? ("GAB".contains(letter) ? 3 : 4) : Integer.parseInt(match.group(3));
        int value = 12 * (octave + 1) + Score.SCALE["CDEFGAB".indexOf(letter)] + (match.group(2).equals("#") ? 1 : match.group(2).equals("b") ? -1 : 0);
        if (value < 0 || value > 127) throw new IllegalArgumentException("调号超出 MIDI 0～127 范围"); return value;
    }
    public static String pitch(int value) {
        if (value < 0 || value > 127) throw new IllegalArgumentException("移调后超出 MIDI 0～127 范围");
        int octave = value / 12 - 5; StringBuilder result = new StringBuilder();
        for (int i = 0; i < Math.abs(octave); i++) result.append(octave < 0 ? '-' : '+');
        return result + new String[]{"1", "#1", "2", "#2", "3", "4", "#4", "5", "#5", "6", "#6", "7"}[value % 12];
    }
    private static String duration(String pitch, double beats) {
        String value = String.format(Locale.ROOT, "%.9f", beats).replaceAll("0+$", "").replaceAll("\\.$", "");
        return pitch + (value.equals("1") ? "" : ":" + value);
    }
    public static String encode(Score score, double bpm) {
        List<String> tokens = new ArrayList<>(); long cursor = 0;
        for (Score.Note n : score.notes) {
            if (n.start > cursor) tokens.add(duration("0", (n.start - cursor) * bpm / 60000));
            tokens.add((n.legato ? "( " : "") + duration(pitch(n.pitch), (n.end - n.start) * bpm / 60000) + (n.legato ? " )" : "")); cursor = n.end;
        }
        if (score.duration > cursor) tokens.add(duration("0", (score.duration - cursor) * bpm / 60000));
        StringBuilder out = new StringBuilder(); for (int i = 0; i < tokens.size(); i++) out.append(i == 0 ? "" : i % 8 == 0 ? "\n" : "  ").append(tokens.get(i)); return out.toString();
    }
    public static String transpose(String text, int semitones, boolean source, String mode) {
        if (source) {
            Result before = source(text, "校验", mode);
            for (Score.Note n : before.score.notes) if ((long) n.pitch + semitones < 0 || (long) n.pitch + semitones > 127) throw new IllegalArgumentException("移调后超出 MIDI 音域");
            // 全角标记先归一化，不改变歌词或其余原谱写法。
            StringBuilder normalized = new StringBuilder(); List<Integer> positions = new ArrayList<>();
            for (int i = 0; i < text.length(); i++) { String part = Normalizer.normalize(text.substring(i, i + 1), Normalizer.Form.NFKC); normalized.append(part); for (int j = 0; j < part.length(); j++) positions.add(i); }
            Matcher normalizedKeys = KEY.matcher(normalized); StringBuilder canonical = new StringBuilder(text); List<int[]> replacements = new ArrayList<>(); List<String> headers = new ArrayList<>();
            while (normalizedKeys.find()) { replacements.add(new int[]{positions.get(normalizedKeys.start()), positions.get(normalizedKeys.end() - 1) + 1}); headers.add(normalizedKeys.group()); }
            for (int i = replacements.size() - 1; i >= 0; i--) canonical.replace(replacements.get(i)[0], replacements.get(i)[1], headers.get(i));
            text = canonical.toString(); Matcher keys = KEY.matcher(text); StringBuffer output = new StringBuffer(); boolean found = false;
            int firstKey = keys.find() ? keys.start() : Integer.MAX_VALUE; keys.reset();
            boolean defaultStart = mode.equals("score") && !before.spans.isEmpty() && before.spans.get(0).left < firstKey;
            while (keys.find()) { found = true; int value = keyPitch(keys) + semitones; if (value < 12 || value > 127) throw new IllegalArgumentException("调号超出可编辑的音域");
                String key = new String[]{"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"}[value % 12] + (value / 12 - 1);
                keys.appendReplacement(output, Matcher.quoteReplacement("/key(" + key + ")")); }
            keys.appendTail(output);
            if (!found || defaultStart) {
                int value = 60 + semitones;
                String key = new String[]{"C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"}[Math.floorMod(value, 12)] + (Math.floorDiv(value, 12) - 1);
                output.insert(0, "/key(" + key + ")\n");
            }
            source(output.toString(), "校验", mode); return output.toString();
        }
        precise(text, 300, "校验"); Matcher tokens = Pattern.compile("//[^\\n]*|(?:\\+{0,5}|-{1,5})[#b]?[0-7](?::\\d+(?:/\\d+|\\.\\d+)?)?").matcher(text); StringBuffer output = new StringBuffer();
        while (tokens.find()) { String token = tokens.group(); if (!token.startsWith("//") && !token.startsWith("0")) token = pitch(precise(token, 300, "校验").score.notes.get(0).pitch + semitones) + (token.contains(":") ? token.substring(token.indexOf(':')) : ""); tokens.appendReplacement(output, Matcher.quoteReplacement(token)); }
        tokens.appendTail(output); return output.toString();
    }
}
