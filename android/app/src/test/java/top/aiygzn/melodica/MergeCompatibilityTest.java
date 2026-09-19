package top.aiygzn.melodica;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

/** 覆盖预览功能与正式版曲库、下载规则合并后的交叉行为。 */
public class MergeCompatibilityTest {
    @Test public void allReleaseBuiltinsRemainEditable() throws Exception {
        File folder = Files.createTempDirectory("merge-builtins-").toFile();
        try {
            Library library = new Library(folder);
            assertEquals(5, library.entries().size());
            for (Library.Entry entry : library.entries()) {
                assertTrue(Library.isBuiltin(entry.id)); assertEquals("内置", library.kind(entry.id));
                Library.Document document = library.document(entry.id, -2, false);
                assertEquals(library.read(entry.id).title, document.score.title);
                assertEquals(document.score.notes.size(), document.parse().score.notes.size());
            }
        } finally { Files.delete(folder.toPath()); }
    }
    @Test public void verifiedCatalogDownloadKeepsTitleAndEditableSource() throws Exception {
        File folder = Files.createTempDirectory("merge-download-").toFile();
        try {
            Library library = new Library(folder); String text = "/key(C4)\nbpm120\n1_ 2_ (3 4)";
            Score score = Jianpu.source(text, "文件中的旧标题", "score").score;
            JSONObject json = CloudScore.encode(score).put("editor", new JSONObject().put("format", "jianpu_space").put("score", text).put("mode", "score"));
            byte[] bytes = json.toString().getBytes(StandardCharsets.UTF_8);
            OnlineLibrary.Song song = new OnlineLibrary.Song("merge", "目录中的新标题", "", "", "https://example.com/score.json", bytes.length, OnlineLibrary.digest(bytes), "score");
            String id = OnlineLibrary.saveDownload(song, bytes, library);
            assertEquals(library.onlineId("merge"), id); assertEquals(song.title, library.read(id).title);
            assertEquals(text, library.document(id, -2, false).text);
            assertTrue(library.document(id, -2, false).source());
            byte[] original = Files.readAllBytes(new File(folder, id).toPath());
            assertThrows(Exception.class, () -> OnlineLibrary.saveDownload(song, "{}".getBytes(StandardCharsets.UTF_8), library));
            assertArrayEquals(original, Files.readAllBytes(new File(folder, id).toPath()));
        } finally { for (File file : folder.listFiles()) Files.delete(file.toPath()); Files.delete(folder.toPath()); }
    }
    @Test public void searchRetainsPlainLinkTitleFallback() throws Exception {
        assertEquals("练习", ResourceSearch.parse("midishow", "<a href='/midi/42.html'>练习</a>", "练习", 1).songs.get(0).title);
        assertEquals("练习", ResourceSearch.parse("midiworld", "<a href='/download/42'>练习</a>", "练习", 1).songs.get(0).title);
        assertEquals("Practice", ResourceSearch.parse("bitmidi", "<a href='/practice-midi' title=''>Practice.mid</a>", "Practice", 1).songs.get(0).title);
    }
}
