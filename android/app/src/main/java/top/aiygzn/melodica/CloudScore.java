package top.aiygzn.melodica;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** 云端交换格式使用整数毫秒，与 Windows、官网及后端保持一致。 */
public final class CloudScore {
    private CloudScore() { }
    public static JSONObject encode(Score score) throws Exception {
        JSONArray notes = new JSONArray();
        List<Score.Note> sorted = new ArrayList<>(score.notes);
        sorted.sort(Comparator.comparingLong((Score.Note n) -> n.start).thenComparingLong(n -> n.end)
            .thenComparingInt(n -> n.pitch).thenComparingInt(n -> n.track));
        for (Score.Note n : sorted) notes.put(new JSONArray().put(n.start).put(n.end).put(n.pitch).put(n.track));
        JSONObject value = new JSONObject().put("version", 1).put("title", score.title).put("duration", score.duration).put("notes", notes);
        decode(value); return value;
    }
    private static long integer(Object value) {
        if (!(value instanceof Integer) && !(value instanceof Long)) throw new IllegalArgumentException("音符时间和编号必须为整数");
        return ((Number) value).longValue();
    }
    public static Score decode(JSONObject value) throws Exception {
        if (integer(value.get("version")) != 1) throw new IllegalArgumentException("云端曲谱版本无效");
        Object rawTitle = value.get("title");
        if (!(rawTitle instanceof String)) throw new IllegalArgumentException("曲名格式无效");
        String title = ((String) rawTitle).trim();
        if (title.isEmpty() || title.length() > 100 || title.matches("(?s).*[\\x00-\\x1f].*")) throw new IllegalArgumentException("曲名需为 1～100 个字符");
        long duration = integer(value.get("duration"));
        if (duration < 1 || duration > 1800000) throw new IllegalArgumentException("曲目不能超过 30 分钟");
        JSONArray data = value.getJSONArray("notes");
        if (data.length() < 1 || data.length() > 30000) throw new IllegalArgumentException("曲谱需包含 1～30000 个音符");
        List<Score.Note> notes = new ArrayList<>();
        for (int i = 0; i < data.length(); i++) {
            JSONArray note = data.getJSONArray(i);
            if (note.length() != 4) throw new IllegalArgumentException("音符需包含四个整数");
            long start = integer(note.get(0)), end = integer(note.get(1)), pitch = integer(note.get(2)), track = integer(note.get(3));
            if (end > duration || track < 0 || track > 65535 || pitch < 0 || pitch > 127) throw new IllegalArgumentException("音符越界");
            notes.add(new Score.Note(start, end, (int) pitch, (int) track));
        }
        return new Score(title, notes, duration);
    }
    public static String id(Score score) throws Exception {
        JSONObject value = encode(score);
        return OnlineLibrary.digest(new JSONArray().put(value.getLong("duration")).put(value.getJSONArray("notes")).toString().getBytes(StandardCharsets.UTF_8));
    }
}
