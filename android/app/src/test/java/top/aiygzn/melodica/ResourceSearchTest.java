package top.aiygzn.melodica;

import org.junit.Test;
import static org.junit.Assert.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/** 来源格式、验证提示和导入交换的回归；联网验证仅在显式环境开关下运行。 */
public class ResourceSearchTest {
    @Test public void traditionalCatalogAndUnicodeQuery() throws Exception {
        String html = "<table><tr><td><a href='/songList/42'>稻香</a></td><td>周傑倫</td></tr><tr><td><a href='/songList/43'>夜曲</a></td><td>周杰倫</td></tr></table>";
        assertEquals(2, ResourceSearch.parse("jianpu", html, "周杰伦", 1).songs.size());
        assertEquals(1, ResourceSearch.parse("jianpu", html, "周杰伦 稻香", 1).songs.size());
        assertTrue(ResourceSearch.searchUrl("midishow", "晴天 周杰伦", 1).contains("%E6%99%B4"));
    }
    @Test public void htmlSourcesAndNextPages() throws Exception {
        ResourceSearch.Page bit = ResourceSearch.parse("bitmidi", "<a href='/test-midi' title='Test.mid'>Listen</a><a href='/search?q=test&page=1'>next</a>", "test", 1);
        assertEquals("Test", bit.songs.get(0).title); assertTrue(bit.more);
        ResourceSearch.Page world = ResourceSearch.parse("midiworld", "<li>Song name - <a href='/download/123'>download</a></li><a href='/search/2/?q=test'>next</a>", "test", 1);
        assertEquals("Song name", world.songs.get(0).title); assertEquals("https://www.midiworld.com/download/123", world.songs.get(0).downloadUrl); assertTrue(world.more);
        assertEquals("晴天", ResourceSearch.parse("midishow", "<a href='/midi/42.html'><h3>晴天</h3></a>", "晴天", 1).songs.get(0).title);
    }
    @Test public void emptyErrorsVerificationAndUntrustedLinksDiffer() throws Exception {
        assertTrue(ResourceSearch.parse("bitmidi", "<p>No results</p>", "test", 1).songs.isEmpty());
        assertThrows(IllegalArgumentException.class, () -> ResourceSearch.parse("bitmidi", "<p>changed</p>", "test", 1));
        assertTrue(ResourceSearch.verification("<title>Just a moment...</title><p>cf-chl-platform</p>"));
        assertFalse(ResourceSearch.verification("<title>乐谱</title><script src='cloudflare/challenge-platform'></script>"));
        for (String href : new String[]{"https://other.example/test-midi", "javascript:alert(1)", "https://user:pass@bitmidi.com/test-midi", "https://bitmidi.com:999/test-midi"})
            assertEquals("", ResourceSearch.siteUrl("https://bitmidi.com/", href));
        assertEquals("https://bitmidi.com/test-midi", ResourceSearch.siteUrl("https://bitmidi.com/", "http://bitmidi.com/test-midi#play"));
    }
    @Test public void sourceTextAndImportsPreserveMetadata() throws Exception {
        assertEquals("/key(C4)\n1 2\nL:你&我", ResourceSearch.notation("<div id='jianpuOut'>/key(C4)<br>1 2\nL:你&amp;我</div>"));
        java.io.File folder = Files.createTempDirectory("import-source-").toFile();
        try {
            Library library = new Library(folder); String text = "/key(A3)\nbpm108\n(1_ 1_) 2_ 3-";
            Score score = Jianpu.source(text, "原谱导入", "score").score;
            org.json.JSONObject json = CloudScore.encode(score).put("jianpu_source", new org.json.JSONObject().put("text", text).put("mode", "score"));
            String id = library.importBytes(json.toString().getBytes(StandardCharsets.UTF_8), "原谱.json");
            assertEquals(text, library.document(id, -2, false).text); assertTrue(library.read(id).notes.get(0).legato);
            json.remove("jianpu_source"); json.put("editor", new org.json.JSONObject().put("format", "jianpu_space").put("score", text).put("mode", "score").put("bpm", 108));
            String editorId = library.importBytes(json.toString().getBytes(StandardCharsets.UTF_8), "桌面另存.json");
            assertEquals(text, library.document(editorId, -2, false).text); assertTrue(library.document(editorId, -2, false).source());
            String plain = library.importBytes("1:0.1 0:1/2 ++1".getBytes(StandardCharsets.UTF_8), "精确.txt");
            assertEquals("1:0.1 0:1/2 ++1", library.document(plain, -2, false).text);
            String moved = Jianpu.transpose("1 2 /key(D4)3", 1, true, "score");
            assertArrayEquals(new int[]{61, 63, 67}, Jianpu.source(moved, "整体移调", "score").score.notes.stream().mapToInt(n -> n.pitch).toArray());
            assertEquals(61, Jianpu.source(Jianpu.transpose("／key（C4）１２", 1, true, "score"), "全角移调", "score").score.notes.get(0).pitch);
        } finally { for (java.io.File file : folder.listFiles()) Files.delete(file.toPath()); Files.delete(folder.toPath()); }
    }
    @Test public void livePublicSourcesWhenRequested() throws Exception {
        org.junit.Assume.assumeTrue("1".equals(System.getenv("MELODICA_LIVE_SEARCH")));
        for (String source : new String[]{"jianpu", "official", "bitmidi", "midiworld", "midishow"}) {
            try {
                ResourceSearch.Page page = ResourceSearch.search(source, source.equals("jianpu") ? "青花瓷" : source.equals("midishow") ? "晴天" : "star", 1);
                System.out.println(source + "：返回 " + page.songs.size() + " 首");
                if (source.equals("jianpu") && !page.songs.isEmpty()) {
                    String text = ResourceSearch.notation(ResourceSearch.html(page.songs.get(0).pageUrl));
                    Score score = Jianpu.source(text, page.songs.get(0).title, "score").score; System.out.println("在线简谱校验：" + score.notes.size() + " 音");
                }
                if ((source.equals("bitmidi") || source.equals("midiworld")) && !page.songs.isEmpty()) {
                    java.io.File folder = Files.createTempDirectory("live-midi-").toFile();
                    try {
                        Library library = new Library(folder); String id = ResourceSearch.download(page.songs.get(0), library, "score");
                        System.out.println(source + " 下载并转换：" + library.read(id).notes.size() + " 个原始音符");
                    } finally { for (java.io.File file : folder.listFiles()) Files.delete(file.toPath()); Files.delete(folder.toPath()); }
                }
            } catch (Exception error) {
                System.out.println(source + "：来源当前不可用：" + error.getMessage());
                if (source.equals("jianpu") || source.equals("official")) throw error;
            }
        }
    }
}
