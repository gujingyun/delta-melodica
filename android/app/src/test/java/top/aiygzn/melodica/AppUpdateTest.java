package top.aiygzn.melodica;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import java.nio.charset.StandardCharsets;
import static org.junit.Assert.*;

public class AppUpdateTest {
    private byte[] manifest(JSONObject value) { return value.toString().getBytes(StandardCharsets.UTF_8); }
    private JSONObject base() throws Exception {
        return new JSONObject().put("platform", "android").put("version", "0.7.0")
            .put("versionCode", 10).put("file", "downloads/app.apk");
    }
    @Test public void parsesVersionAndResolvesDownloadUrl() throws Exception {
        AppUpdate update = AppUpdate.parse(manifest(base().put("notes", new JSONArray().put("新增检查更新").put("修复问题"))));
        assertEquals("0.7.0", update.version); assertEquals(10, update.versionCode);
        assertEquals("https://aiygzn.top/melodica/downloads/app.apk", update.fileUrl);
        assertEquals("• 新增检查更新\n• 修复问题", update.notes);
    }
    @Test public void rejectsInvalidManifestAndUnsafeDownload() throws Exception {
        assertThrows(Exception.class, () -> AppUpdate.parse(manifest(base().put("platform", "windows"))));
        assertThrows(Exception.class, () -> AppUpdate.parse(manifest(base().put("versionCode", 0))));
        assertThrows(Exception.class, () -> AppUpdate.parse(manifest(base().put("file", "http://example.com/app.apk"))));
        JSONArray notes = new JSONArray(); for (int i = 0; i < 21; i++) notes.put("说明" + i);
        assertThrows(Exception.class, () -> AppUpdate.parse(manifest(base().put("notes", notes))));
        assertThrows(Exception.class, () -> AppUpdate.parse(new byte[AppUpdate.MAX_MANIFEST_BYTES + 1]));
    }
}
