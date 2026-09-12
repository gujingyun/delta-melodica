package top.aiygzn.melodica;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;

/** 保存解析后的曲谱副本，文件选择器中的原始文件保持原样。 */
public final class Library {
    private final File folder;
    public Library(Context context) { folder = new File(context.getFilesDir(), "songs"); folder.mkdirs(); }
    public static final class Entry {
        public final String id, title;
        Entry(String id, String title) { this.id = id; this.title = title; }
        @Override public String toString() { return title; }
    }
    public List<Entry> entries() {
        List<Entry> entries = new ArrayList<>(); entries.add(new Entry("demo", "小星星 · 内置"));
        File[] files = folder.listFiles((dir, name) -> name.endsWith(".json"));
        if (files != null) for (File file : files) {
            try { entries.add(new Entry(file.getName(), object(file).getString("title"))); }
            catch (Exception ignored) { /* 损坏的曲谱不会阻止打开其余曲库。 */ }
        }
        if (entries.size() > 1) entries.subList(1, entries.size()).sort(Comparator.comparing(e -> e.title));
        return entries;
    }
    private JSONObject object(File file) throws Exception {
        if (file.length() > 5 * 1024 * 1024) throw new IllegalArgumentException("本地曲谱文件过大");
        return new JSONObject(new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8));
    }
    public Score read(String id) throws Exception {
        if (id.equals("demo")) return Score.jianpu(Score.STAR, 100, "小星星");
        if (!id.matches("[a-f0-9-]+\\.json")) throw new IllegalArgumentException("曲谱标识无效");
        JSONObject json = object(new File(folder, id)); JSONArray data = json.getJSONArray("notes");
        List<Score.Note> notes = new ArrayList<>();
        if (data.length() > 30000) throw new IllegalArgumentException("曲谱音符过多");
        for (int i = 0; i < data.length(); i++) {
            JSONArray n = data.getJSONArray(i);
            notes.add(new Score.Note(n.getLong(0), n.getLong(1), n.getInt(2), n.getInt(3)));
        }
        return new Score(json.getString("title"), notes, json.getLong("duration"));
    }
    public String save(Score score) throws Exception {
        JSONArray notes = new JSONArray();
        for (Score.Note n : score.notes) notes.put(new JSONArray().put(n.start).put(n.end).put(n.pitch).put(n.track));
        JSONObject json = new JSONObject().put("title", score.title).put("duration", score.duration).put("notes", notes);
        String id = UUID.randomUUID() + ".json";
        File temp = new File(folder, id + ".tmp"), target = new File(folder, id);
        Files.write(temp.toPath(), json.toString().getBytes(StandardCharsets.UTF_8));
        Files.move(temp.toPath(), target.toPath());
        return id;
    }
}
