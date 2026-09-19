package top.aiygzn.melodica;

import org.json.JSONArray;
import org.json.JSONObject;
import java.net.URI;
import java.nio.charset.StandardCharsets;

/** 官网 Android 更新清单，只读取版本信息和下载地址。 */
public final class AppUpdate {
    public static final String MANIFEST_URL = "https://aiygzn.top/melodica/android-version.json";
    static final int MAX_MANIFEST_BYTES = 256 * 1024;
    public final String version, fileUrl, notes;
    public final int versionCode;

    private AppUpdate(String version, int versionCode, String fileUrl, String notes) {
        this.version = version; this.versionCode = versionCode; this.fileUrl = fileUrl; this.notes = notes;
    }
    public static AppUpdate fetch() throws Exception { return parse(OnlineLibrary.fetch(MANIFEST_URL, MAX_MANIFEST_BYTES)); }
    public static AppUpdate parse(byte[] bytes) throws Exception {
        if (bytes == null || bytes.length > MAX_MANIFEST_BYTES) throw new IllegalArgumentException("更新清单超过 256 KB");
        JSONObject root = new JSONObject(new String(bytes, StandardCharsets.UTF_8));
        if (!"android".equals(root.optString("platform"))) throw new IllegalArgumentException("更新清单平台无效");
        String version = text(root, "version", 32), file = text(root, "file", 500);
        int versionCode = root.getInt("versionCode");
        if (versionCode <= 0) throw new IllegalArgumentException("更新清单版本号无效");
        URI manifest = OnlineLibrary.checkedUrl(MANIFEST_URL);
        String fileUrl = OnlineLibrary.checkedUrl(manifest.resolve(file).toString()).toString();
        JSONArray rawNotes = root.optJSONArray("notes"); StringBuilder notes = new StringBuilder();
        if (rawNotes != null) {
            if (rawNotes.length() > 20) throw new IllegalArgumentException("更新说明过多");
            for (int i = 0; i < rawNotes.length(); i++) {
                Object value = rawNotes.get(i); if (!(value instanceof String)) throw new IllegalArgumentException("更新说明格式无效");
                String line = ((String) value).trim(); if (line.isEmpty() || line.length() > 300) throw new IllegalArgumentException("更新说明格式无效");
                for (int j = 0; j < line.length(); j++) if (line.charAt(j) < 32) throw new IllegalArgumentException("更新说明包含无效字符");
                if (notes.length() > 0) notes.append('\n'); notes.append("• ").append(line);
            }
        }
        return new AppUpdate(version, versionCode, fileUrl, notes.toString());
    }
    private static String text(JSONObject root, String key, int maximum) throws Exception {
        Object value = root.get(key); if (!(value instanceof String)) throw new IllegalArgumentException("更新清单字段无效：" + key);
        String result = ((String) value).trim();
        if (result.isEmpty() || result.length() > maximum) throw new IllegalArgumentException("更新清单字段无效：" + key);
        for (int i = 0; i < result.length(); i++) if (result.charAt(i) < 32) throw new IllegalArgumentException("更新清单字段包含无效字符");
        return result;
    }
}
