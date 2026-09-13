package top.aiygzn.melodica;

import org.json.JSONObject;
import org.junit.Test;
import java.util.Arrays;
import static org.junit.Assert.*;

/** 与后端相同的跨端曲谱样例，验证时值、音轨及重复音不被同步过程改变。 */
public class CloudScoreTest {
    @Test public void roundTripPreservesNotesAndTrack() throws Exception {
        Score original = new Score("同步测试", Arrays.asList(new Score.Note(500, 1000, 62, 3), new Score.Note(0, 500, 60, 0)), 1200);
        Score decoded = CloudScore.decode(CloudScore.encode(original));
        assertEquals(1200, decoded.duration); assertEquals(2, decoded.notes.size());
        assertEquals(0, decoded.notes.get(0).start); assertEquals(3, decoded.notes.get(1).track);
        assertEquals(CloudScore.id(original), CloudScore.id(decoded));
        assertEquals("3a2f55eda21cb4933d77db4999aa9b2f2d3b91c0b368e3924393e86c77ffbb53", CloudScore.id(original));
    }
    @Test public void sameContentDifferentTitleSharesId() throws Exception {
        Score first = Score.jianpu("1 1 2", 120, "一");
        Score second = Score.jianpu("1 1 2", 120, "二");
        assertEquals(CloudScore.id(first), CloudScore.id(second));
        assertEquals(3, CloudScore.decode(CloudScore.encode(first)).notes.size());
    }
    @Test public void rejectsInvalidCloudPayload() throws Exception {
        for (String invalid : new String[]{
            "{\"version\":1,\"title\":\"一\",\"duration\":1000,\"notes\":[[0,1001,60,0]]}",
            "{\"version\":1,\"title\":\"一\",\"duration\":1000,\"notes\":[[0,500,true,0]]}",
            "{\"version\":1,\"title\":\"一\",\"duration\":1000,\"notes\":[[0,500,60,-1]]}",
            "{\"version\":2,\"title\":\"一\",\"duration\":1000,\"notes\":[[0,500,60,0]]}"
        }) {
            try {CloudScore.decode(new JSONObject(invalid)); fail("应拒绝越界曲谱");} catch (IllegalArgumentException expected) { }
        }
    }
    @Test public void cloudSaveIsIdempotentAndReadable() throws Exception {
        java.io.File dir = java.nio.file.Files.createTempDirectory("account-library").toFile();
        try {
            Library library = new Library(dir); Score score = Score.jianpu("1 2 3", 100, "云端测试");
            String id = library.saveCloud(CloudScore.id(score), score);
            assertEquals(id, library.saveCloud(CloudScore.id(score), score));
            assertEquals(2, library.entries().size()); assertEquals(3, library.read(id).notes.size());
        } finally {for (java.io.File file : dir.listFiles()) java.nio.file.Files.delete(file.toPath()); java.nio.file.Files.delete(dir.toPath());}
    }
}
