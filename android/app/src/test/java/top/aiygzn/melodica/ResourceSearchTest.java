package top.aiygzn.melodica;

import org.junit.Test;
import java.util.List;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/** 聚合搜索来源、分页链接和结果解析的离线测试。 */
public class ResourceSearchTest {
    @Test public void keepsFiveSourcesAndBuildsCompatibleUrls() {
        assertEquals(5, ResourceSearch.SOURCES.size());
        assertEquals("https://jianpu.space/songList", ResourceSearch.searchUrl("jianpu", "父亲", 1));
        assertEquals("https://bitmidi.com/search?q=%E7%88%B6%E4%BA%B2&page=0", ResourceSearch.searchUrl("bitmidi", "父亲", 1));
        assertEquals("https://www.midiworld.com/search/2/?q=river", ResourceSearch.searchUrl("midiworld", "river", 2));
        assertEquals("https://www.midishow.com/search/result?q=%E7%A8%BB%E9%A6%99&page=1", ResourceSearch.searchUrl("midishow", "稻香", 1));
    }

    @Test public void parsesAllHtmlSourceShapesAndMoreLinks() throws Exception {
        String bitmidi = "<h1>Results</h1><a title=\"River.mid\" href=\"/river-midi\">River</a>"
            + "<a href=\"/search?q=river&page=1\">下一页</a>";
        ResourceSearch.SearchPage bitPage = ResourceSearch.parseSearchPage("bitmidi", bitmidi, "https://bitmidi.com/search?q=river&page=0", 1);
        assertEquals(1, bitPage.songs.size()); assertEquals("River", bitPage.songs.get(0).title); assertTrue(bitPage.hasMore);

        String midiworld = "<ul><li>River of Dreams (Billy Joel) - <a href=\"/download/42\">Download</a></li></ul>";
        ResourceSearch.SearchPage worldPage = ResourceSearch.parseSearchPage("midiworld", midiworld, "https://www.midiworld.com/search/?q=river", 1);
        assertEquals("River of Dreams (Billy Joel)", worldPage.songs.get(0).title); assertEquals("https://www.midiworld.com/download/42", worldPage.songs.get(0).downloadUrl);

        String midishow = "<h2><a href=\"/midi/river-42\">River MIDI</a></h2>";
        ResourceSearch.SearchPage showPage = ResourceSearch.parseSearchPage("midishow", midishow, "https://www.midishow.com/search/result?q=river&page=1", 1);
        assertEquals(1, showPage.songs.size()); assertFalse(showPage.songs.get(0).downloadable()); assertEquals("River MIDI", showPage.songs.get(0).title);
    }

    @Test public void parsesJianpuCatalogAndTraditionalQuery() {
        String html = "<table><tr><td><a href=\"/songList/42\">中国军魂</a></td><td>None</td></tr>"
            + "<tr><td><a href=\"https://example.com/no\">外站</a></td><td>A</td></tr></table>";
        List<ResourceSearch.SearchSong> songs = ResourceSearch.searchJianpu(html, "軍魂").songs;
        assertEquals(1, songs.size()); assertEquals("中国军魂", songs.get(0).title); assertEquals("", songs.get(0).artist);
    }

    @Test public void deduplicationKeyIncludesSourceAndPrefersDownloadUrl() {
        ResourceSearch.SearchSong first = new ResourceSearch.SearchSong("midiworld", "甲", "https://www.midiworld.com/search", "https://www.midiworld.com/download/1", "", -1, "", "midi");
        ResourceSearch.SearchSong second = new ResourceSearch.SearchSong("midishow", "甲", "https://www.midishow.com/midi/1", "", "", -1, "", "midi");
        assertTrue(first.key().contains("download/1")); assertFalse(first.key().equals(second.key()));
    }
}
