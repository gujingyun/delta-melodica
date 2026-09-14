package top.aiygzn.melodica;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import static org.junit.Assert.*;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;

public class OnlineLibraryTest {
    @Rule public TemporaryFolder temporary = new TemporaryFolder();
    private JSONObject item(String id, String title) throws Exception {
        return new JSONObject().put("id", id).put("title", title).put("url", "songs/test.mid");
    }
    private List<OnlineLibrary.Song> catalog(JSONObject... items) throws Exception {
        JSONArray rows = new JSONArray(); for (JSONObject item : items) rows.put(item);
        return OnlineLibrary.parseCatalog(new JSONObject().put("songs", rows).toString().getBytes(StandardCharsets.UTF_8));
    }
    @Test public void relativeUrlsUnicodeAndSearch() throws Exception {
        List<OnlineLibrary.Song> songs = catalog(item("hua", "花海").put("artist", "Test Artist"), item("jun", "中国军魂"));
        assertEquals("https://aiygzn.top/melodica/songs/test.mid", songs.get(0).url);
        assertEquals(1, OnlineLibrary.search(songs, " 军魂 ").size());
        assertEquals("hua", OnlineLibrary.search(songs, "test ARTIST").get(0).id);
        assertEquals(0, OnlineLibrary.search(songs, "不存在").size()); assertEquals(2, OnlineLibrary.search(songs, "").size());
    }
    @Test public void rejectsMalformedCatalogAndMetadata() throws Exception {
        assertThrows(Exception.class, () -> catalog(item("a", "甲"), item("a", "乙")));
        assertThrows(Exception.class, () -> catalog(item("../escape", "甲")));
        assertThrows(Exception.class, () -> catalog(item("a", " ")));
        assertThrows(Exception.class, () -> catalog(item("a", "甲\n乙")));
        for (Object size : new Object[]{0, -1, true, 1.5, "10", OnlineLibrary.MAX_SONG_BYTES + 1})
            assertThrows(Exception.class, () -> catalog(item("a", "甲").put("size", size)));
        assertThrows(Exception.class, () -> catalog(item("a", "甲").put("sha256", "invalid")));
        assertThrows(Exception.class, () -> OnlineLibrary.parseCatalog("<html>失败</html>".getBytes(StandardCharsets.UTF_8)));
        assertThrows(Exception.class, () -> OnlineLibrary.parseCatalog(new byte[OnlineLibrary.MAX_CATALOG_BYTES + 1]));
        JSONObject[] many = new JSONObject[501]; for (int i = 0; i < many.length; i++) many[i] = item("s" + i, "曲目" + i);
        assertThrows(Exception.class, () -> catalog(many));
    }
    @Test public void rejectsNonHttpsAndCredentialUrls() {
        for (String url : new String[]{"http://example.com/a.mid", "file:///tmp/a.mid", "javascript:alert(1)", "https://user:password@example.com/a.mid", "https://example.com/a.mid#fragment", "https:///missing"})
            assertThrows(Exception.class, () -> OnlineLibrary.checkedUrl(url));
    }
    @Test public void checksSizeHashAndMidiBeforeAccepting() throws Exception {
        byte[] bytes = midi();
        JSONObject good = item("song", "校验曲目").put("size", bytes.length).put("sha256", OnlineLibrary.digest(bytes).toUpperCase(java.util.Locale.ROOT));
        Score score = OnlineLibrary.decode(catalog(good).get(0), bytes);
        assertEquals("校验曲目", score.title); assertEquals(60, score.notes.get(0).pitch);
        assertThrows(Exception.class, () -> OnlineLibrary.decode(catalog(item("a", "甲").put("size", bytes.length + 1)).get(0), bytes));
        assertThrows(Exception.class, () -> OnlineLibrary.decode(catalog(item("a", "甲").put("sha256", "0".repeat(64))).get(0), bytes));
        byte[] html = "<html>404</html>".getBytes(StandardCharsets.UTF_8);
        assertThrows(Exception.class, () -> OnlineLibrary.decode(catalog(item("a", "甲").put("sha256", OnlineLibrary.digest(html))).get(0), html));
    }
    @Test public void boundsStreamsDeadlineAndCancellation() throws Exception {
        assertEquals(8, OnlineLibrary.readLimited(new ByteArrayInputStream(new byte[8]), 8, Long.MAX_VALUE).length);
        assertThrows(Exception.class, () -> OnlineLibrary.readLimited(new ByteArrayInputStream(new byte[9]), 8, Long.MAX_VALUE));
        assertThrows(Exception.class, () -> OnlineLibrary.readLimited(new ByteArrayInputStream(new byte[1]), 8, 0));
        try {
            Thread.currentThread().interrupt();
            assertThrows(java.io.InterruptedIOException.class, () -> OnlineLibrary.readLimited(new ByteArrayInputStream(new byte[1]), 8, Long.MAX_VALUE));
        } finally { Thread.interrupted(); }
    }
    @Test public void downloadsScoreJsonWithExactTimingAndCatalogTitle() throws Exception {
        JSONObject value = CloudScore.encode(Score.jianpu("1 0:1/2 #4:1/2 +1:2", 120, "文件标题"));
        byte[] bytes = value.put("source", new JSONObject().put("text", "可编辑原谱")).toString().getBytes(StandardCharsets.UTF_8);
        JSONObject row = item("json-song", "目录标题").put("url", "songs/example.json").put("format", "score")
            .put("size", bytes.length).put("sha256", OnlineLibrary.digest(bytes));
        Score result = OnlineLibrary.decode(catalog(row).get(0), bytes);
        assertEquals("目录标题", result.title); assertEquals(2000, result.duration);
        assertEquals(3, result.notes.size()); assertEquals(750, result.notes.get(1).start);
        assertEquals(1000, result.notes.get(1).end); assertEquals(66, result.notes.get(1).pitch);
        assertEquals(72, result.notes.get(2).pitch);
        Library library = new Library(temporary.newFolder());
        assertEquals(result.duration, library.read(library.saveOnline("json-song", result)).duration);
    }
    @Test public void rejectsInvalidScoreJsonAndFormatMismatch() throws Exception {
        JSONObject row = item("json-song", "曲谱").put("format", "score");
        byte[] invalid = "{\"version\":1,\"title\":\"坏谱\",\"duration\":500,\"notes\":[[0,501,60,0]]}".getBytes(StandardCharsets.UTF_8);
        assertThrows(Exception.class, () -> OnlineLibrary.decode(catalog(row).get(0), invalid));
        assertThrows(Exception.class, () -> OnlineLibrary.decode(catalog(row).get(0), midi()));
        byte[] valid = CloudScore.encode(Score.jianpu("1", 120, "曲谱")).toString().getBytes(StandardCharsets.UTF_8);
        assertThrows(Exception.class, () -> OnlineLibrary.decode(catalog(item("midi-song", "MIDI")).get(0), valid));
        assertThrows(Exception.class, () -> OnlineLibrary.decode(catalog(row.put("sha256", "0".repeat(64))).get(0), valid));
        assertThrows(Exception.class, () -> catalog(item("unknown", "曲谱").put("format", "html")));
        assertThrows(Exception.class, () -> catalog(item("unknown", "曲谱").put("format", 1)));
    }
    @Test public void downloadsHaveStableLocalIdsAndKeepImportedSongs() throws Exception {
        java.io.File folder = temporary.newFolder(); Library library = new Library(folder);
        Score score = Score.jianpu("1 2 3", 120, "下载测试");
        String imported = library.save(score), online = library.saveOnline("online-test", score);
        assertEquals(online, library.saveOnline("online-test", score)); assertNotEquals(imported, online);
        assertEquals(Library.BUILTIN_COUNT + 2, library.entries().size()); assertTrue(library.hasOnline("online-test"));
        assertEquals(3, new Library(folder).read(online).notes.size());
        byte[] before = Files.readAllBytes(new java.io.File(folder, online).toPath());
        try {
            Thread.currentThread().interrupt(); assertThrows(java.io.InterruptedIOException.class, () -> library.saveOnline("online-test", score));
        } finally { Thread.interrupted(); }
        assertArrayEquals(before, Files.readAllBytes(new java.io.File(folder, online).toPath()));
        assertEquals(2, folder.listFiles().length);
    }
    static byte[] midi() throws Exception {
        byte[] track = {0, (byte)0x90, 60, 100, (byte)0x83, 0x60, (byte)0x80, 60, 0, 0, (byte)0xff, 0x2f, 0};
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(); DataOutputStream out = new DataOutputStream(bytes);
        out.writeInt(0x4d546864); out.writeInt(6); out.writeShort(0); out.writeShort(1); out.writeShort(480);
        out.writeInt(0x4d54726b); out.writeInt(track.length); out.write(track); return bytes.toByteArray();
    }
}
