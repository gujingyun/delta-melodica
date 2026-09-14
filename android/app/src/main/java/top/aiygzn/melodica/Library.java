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
    public static final int BUILTIN_COUNT = 5;
    private static final Builtin[] BUILT_INS = {
        new Builtin("demo", "小星星", Score.STAR),
        new Builtin("unlock-nightingale", "乐曲解锁-夜莺", Score.UNLOCK_NIGHTINGALE),
        new Builtin("unlock-watch", "乐曲解锁-守望", Score.UNLOCK_WATCH),
        new Builtin("unlock-wind", "乐曲解锁-风起", Score.UNLOCK_WIND),
        new Builtin("unlock-dawn", "乐曲解锁-破晓", Score.UNLOCK_DAWN)
    };
    public Library(Context context) { this(new File(new Account(context).profile(), "songs")); account = new Account(context); }
    Library(File folder) { this.folder = folder; folder.mkdirs(); }
    private static final class Builtin {
        final String id, title, score;
        Builtin(String id, String title, String score) { this.id = id; this.title = title; this.score = score; }
    }
    public static final class Entry {
        public final String id, title;
        Entry(String id, String title) { this.id = id; this.title = title; }
        @Override public String toString() { return title; }
    }
    public List<Entry> entries() {
        List<Entry> entries = new ArrayList<>();
        for (Builtin builtin : BUILT_INS) entries.add(new Entry(builtin.id, builtin.title + " · 内置"));
        File[] files = folder.listFiles((dir, name) -> name.endsWith(".json"));
        if (files != null) for (File file : files) {
            if (account != null && !account.signedIn() && !account.guestVisible(file.getName())) continue;
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
        for (Builtin builtin : BUILT_INS) if (builtin.id.equals(id)) return Score.jianpu(builtin.score, 100, builtin.title);
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
    public static boolean isBuiltin(String id) {
        for (Builtin builtin : BUILT_INS) if (builtin.id.equals(id)) return true;
        return false;
    }
    public String save(Score score) throws Exception {
        return save(score, UUID.randomUUID() + ".json");
    }
    public String onlineId(String songId) {
        return UUID.nameUUIDFromBytes((OnlineLibrary.CATALOG_URL + "#" + songId).getBytes(StandardCharsets.UTF_8)) + ".json";
    }
    public boolean hasOnline(String songId) { return new File(folder, onlineId(songId)).isFile(); }
    public String saveOnline(String songId, Score score) throws Exception {
        OnlineLibrary.checkCancelled(); return save(score, onlineId(songId));
    }
    public String saveCloud(String songId, Score score) throws Exception {
        if (!songId.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("云端曲目标识无效");
        return save(score, songId + ".json");
    }
    private String save(Score score, String id) throws Exception {
        JSONArray notes = new JSONArray();
        for (Score.Note n : score.notes) notes.put(new JSONArray().put(n.start).put(n.end).put(n.pitch).put(n.track));
        JSONObject json = new JSONObject().put("title", score.title).put("duration", score.duration).put("notes", notes);
        File temp = File.createTempFile(".download-", ".tmp", folder), target = new File(folder, id);
        try {
            Files.write(temp.toPath(), json.toString().getBytes(StandardCharsets.UTF_8));
            OnlineLibrary.checkCancelled();
            try { Files.move(temp.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
            catch (java.nio.file.AtomicMoveNotSupportedException e) { Files.move(temp.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING); }
        } finally { Files.deleteIfExists(temp.toPath()); }
        return id;
    }
}
