package top.aiygzn.melodica;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;

/** 保存解析后的曲谱副本，文件选择器中的原始文件保持原样。 */
public final class Library {
    private final File folder;
    private Account account;
    public Library(Context context) { this(new File(new Account(context).profile(), "songs")); account = new Account(context); }
    Library(File folder) { this.folder = folder; folder.mkdirs(); }
    public static final class Entry {
        public final String id, title;
        Entry(String id, String title) { this.id = id; this.title = title; }
        @Override public String toString() { return title; }
    }
    public List<Entry> entries() {
        List<Entry> entries = new ArrayList<>(); entries.add(new Entry("demo", "小星星 · 内置"));
        File[] files = folder.listFiles((dir, name) -> name.endsWith(".json"));
        if (files != null) for (File file : files) {
            try { JSONObject item = object(file); entries.add(new Entry(file.getName(), "[" + item.optString("kind", "曲谱") + "] " + item.getString("title"))); }
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
            notes.add(new Score.Note(n.getLong(0), n.getLong(1), n.getInt(2), n.getInt(3), n.optBoolean(4, false)));
        }
        return new Score(json.getString("title"), notes, json.getLong("duration"));
    }
    public String save(Score score) throws Exception {
        return save(score, UUID.randomUUID() + ".json");
    }
    public static final class Document {
        public final Score score;
        public final String text, mode, url, kind;
        public final double bpm;
        public Document(Score score, String text, double bpm, String mode, String url, String kind) {
            this.score = score; this.text = text; this.bpm = bpm; this.mode = mode; this.url = url; this.kind = kind;
        }
        public boolean source() { return mode.equals("score") || mode.equals("source"); }
        public Jianpu.Result parse() { return source() ? Jianpu.source(text, score.title, mode) : Jianpu.precise(text, bpm, score.title); }
    }
    public Document document(String id, int track, boolean piano) throws Exception {
        Score score = read(id); JSONObject json = id.equals("demo") ? new JSONObject() : object(new File(folder, id));
        JSONObject editor = json.optJSONObject("editor"), source = json.optJSONObject("jianpu_source");
        if (source != null) {
            Document candidate = new Document(score, source.optString("text"), 120, source.optString("mode", "score"), source.optString("url"), "简谱");
            if (matches(candidate)) return candidate;
        }
        if (editor != null) {
            Document candidate = new Document(score, editor.optString("score"), editor.optDouble("bpm", 120), editor.optString("format").equals("jianpu_space") ? editor.optString("mode", "score") : "precise", editor.optString("source_url"), "简谱");
            if (matches(candidate)) return candidate;
        }
        Score melody = ScoreTools.melody(score, track, piano);
        return new Document(melody, Jianpu.encode(melody, 120), 120, "precise", "", json.optString("kind", "曲谱"));
    }
    private static boolean matches(Document document) {
        try {
            Score parsed = document.parse().score, original = document.score;
            if (Math.abs(parsed.duration - original.duration) > 1 || parsed.notes.size() != original.notes.size()) return false;
            for (int i = 0; i < parsed.notes.size(); i++) {
                Score.Note a = parsed.notes.get(i), b = original.notes.get(i);
                if (a.pitch != b.pitch || Math.abs(a.start - b.start) > 1 || Math.abs(a.end - b.end) > 1) return false;
            }
            return true;
        } catch (Exception e) { return false; }
    }
    public String kind(String id) {
        if (id.equals("demo")) return "内置";
        try { if (!id.matches("[a-f0-9-]+\\.json")) return "曲谱"; return object(new File(folder, id)).optString("kind", "曲谱"); }
        catch (Exception e) { return "曲谱"; }
    }
    public String saveDocument(Document document) throws Exception { return saveDocument(document, UUID.randomUUID() + ".json"); }
    public String saveDocument(Document document, String id) throws Exception {
        if (!id.matches("[a-f0-9-]+\\.json")) throw new IllegalArgumentException("曲目标识无效");
        if (!matches(document)) throw new IllegalArgumentException("谱文与音符不一致，请重新校验后保存");
        JSONObject extra = new JSONObject().put("kind", "简谱");
        extra.put("editor", new JSONObject().put("score", document.source() ? Jianpu.encode(document.score, 120) : document.text).put("bpm", document.bpm));
        if (document.source()) extra.put("jianpu_source", new JSONObject().put("text", document.text).put("mode", document.mode).put("url", document.url));
        return save(document.score, id, extra);
    }
    public String saveImported(Score score, String kind) throws Exception { return save(score, UUID.randomUUID() + ".json", new JSONObject().put("kind", kind)); }
    public String importBytes(byte[] bytes, String title) throws Exception { return importBytes(bytes, title, UUID.randomUUID() + ".json"); }
    String importBytes(byte[] bytes, String title, String id) throws Exception {
        if (bytes.length > 10 * 1024 * 1024) throw new IllegalArgumentException("文件不能超过 10 MB");
        title = ResourceSearch.truncate(title.replaceFirst("(?i)\\.(midi?|txt|json)$", ""), 100).trim();
        if (title.isEmpty()) title = "导入曲谱";
        if (bytes.length >= 4 && bytes[0] == 'M' && bytes[1] == 'T' && bytes[2] == 'h' && bytes[3] == 'd') return save(MidiReader.read(bytes, title), id, new JSONObject().put("kind", "MIDI"));
        String text = new String(bytes, StandardCharsets.UTF_8).replace("\ufeff", "");
        if (text.trim().startsWith("{")) {
            JSONObject json = new JSONObject(text); Score score = CloudScore.decode(json);
            JSONObject source = json.optJSONObject("jianpu_source"), editor = json.optJSONObject("editor");
            if (source != null) {
                Document document = new Document(score, source.optString("text"), 120, source.optString("mode", "score"), source.optString("url"), "简谱");
                if (matches(document)) return saveDocument(new Document(document.parse().score, document.text, document.bpm, document.mode, document.url, "简谱"), id);
            }
            if (editor != null) {
                Document document = new Document(score, editor.optString("score"), editor.optDouble("bpm", 120), editor.optString("format").equals("jianpu_space") ? editor.optString("mode", "score") : "precise", editor.optString("source_url"), "简谱");
                if (matches(document)) return saveDocument(new Document(document.parse().score, document.text, document.bpm, document.mode, document.url, "简谱"), id);
            }
            return save(score, id, new JSONObject().put("kind", "云端"));
        }
        if (bytes.length > 512000) throw new IllegalArgumentException("文本简谱过大");
        boolean source = java.util.regex.Pattern.compile("(?im)/key|^\\s*bpm|^\\s*L:|[',=_~]").matcher(java.text.Normalizer.normalize(text, java.text.Normalizer.Form.NFKC)).find();
        Score score = source ? Jianpu.source(text, title, "score").score : Jianpu.precise(text, 100, title).score;
        return saveDocument(new Document(score, text, source ? 120 : 100, source ? "score" : "precise", "", "简谱"), id);
    }
    public String onlineId(String songId) {
        return UUID.nameUUIDFromBytes((OnlineLibrary.CATALOG_URL + "#" + songId).getBytes(StandardCharsets.UTF_8)) + ".json";
    }
    public boolean hasOnline(String songId) { return new File(folder, onlineId(songId)).isFile(); }
    public String saveOnline(String songId, Score score) throws Exception {
        OnlineLibrary.checkCancelled(); return save(score, onlineId(songId), new JSONObject().put("kind", "MIDI"));
    }
    public String saveCloud(String songId, Score score) throws Exception {
        if (!songId.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("云端曲目标识无效");
        return save(score, songId + ".json", new JSONObject().put("kind", "云端"));
    }
    private String save(Score score, String id) throws Exception {
        return save(score, id, new JSONObject());
    }
    String save(Score score, String id, JSONObject extra) throws Exception {
        if (!id.matches("[a-f0-9-]+\\.json")) throw new IllegalArgumentException("曲目标识无效");
        CloudScore.encode(score);
        JSONArray notes = new JSONArray();
        for (Score.Note n : score.notes) notes.put(new JSONArray().put(n.start).put(n.end).put(n.pitch).put(n.track).put(n.legato));
        JSONObject json = extra.put("title", score.title).put("duration", score.duration).put("notes", notes);
        byte[] bytes = json.toString().getBytes(StandardCharsets.UTF_8);
        if (bytes.length > 5 * 1024 * 1024) throw new IllegalArgumentException("本地曲谱文件过大");
        File temp = File.createTempFile(".download-", ".tmp", folder), target = new File(folder, id);
        try {
            Files.write(temp.toPath(), bytes);
            OnlineLibrary.checkCancelled();
            try { Files.move(temp.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
            catch (java.nio.file.AtomicMoveNotSupportedException e) { Files.move(temp.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING); }
        } finally { Files.deleteIfExists(temp.toPath()); }
        return id;
    }
}
