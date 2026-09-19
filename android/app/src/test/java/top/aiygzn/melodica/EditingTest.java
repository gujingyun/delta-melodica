package top.aiygzn.melodica;

import org.junit.Test;
import static org.junit.Assert.*;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Collections;

/** 对照桌面规则，覆盖编辑、时间轴和保存兼容性。 */
public class EditingTest {
    @Test public void desktopParityFixtures() throws Exception {
        org.json.JSONArray fixtures;
        try (java.io.InputStream in = getClass().getResourceAsStream("/desktop-jianpu.json")) {
            fixtures = new org.json.JSONArray(new String(in.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8));
        }
        for (int i = 0; i < fixtures.length(); i++) {
            org.json.JSONObject fixture = fixtures.getJSONObject(i);
            String text = fixture.getString("text"), mode = fixture.getString("mode"), label = mode + "：" + text;
            if (fixture.optBoolean("error")) { assertThrows(label, IllegalArgumentException.class, () -> Jianpu.source(text, "跨端基准", mode)); continue; }
            Jianpu.Result parsed = Jianpu.source(text, "跨端基准", mode);
            assertEquals(label, fixture.getLong("duration"), parsed.score.duration);
            org.json.JSONArray notes = fixture.getJSONArray("notes"); assertEquals(label, notes.length(), parsed.score.notes.size());
            for (int j = 0; j < notes.length(); j++) {
                org.json.JSONArray n = notes.getJSONArray(j); Score.Note actual = parsed.score.notes.get(j);
                assertEquals(label, n.getLong(0), actual.start, 1); assertEquals(label, n.getLong(1), actual.end, 1);
                assertEquals(label, n.getInt(2), actual.pitch); assertEquals(label, n.getBoolean(3), actual.legato);
            }
            org.json.JSONArray spans = fixture.getJSONArray("trace"); assertEquals(label, spans.length(), parsed.spans.size());
            for (int j = 0; j < spans.length(); j++) {
                org.json.JSONArray span = spans.getJSONArray(j); Jianpu.Span actual = parsed.spans.get(j);
                assertEquals(label, span.getInt(0), actual.left); assertEquals(label, span.getInt(1), actual.right);
                assertEquals(label, span.getLong(2), actual.start, 1); assertEquals(label, span.getLong(3), actual.end, 1);
            }
        }
    }
    @Test public void repeatsRestoreKeyTempoAndFirstEnding() {
        Jianpu.Result r = Jianpu.source("/key(C4)\nbpm120\n|:1 [1 /key(D4)2 :| [2 3", "反复", "score");
        assertArrayEquals(new int[]{60, 64, 60, 64}, r.score.notes.stream().mapToInt(n -> n.pitch).toArray());
        assertEquals(2000, r.score.duration);
        assertEquals(60, Jianpu.source("1 :| 2 :|", "省略起点", "score").score.notes.get(0).pitch);
        assertEquals(4, Jianpu.source("1 :| 2 :|", "省略起点", "score").score.notes.size());
    }
    @Test public void sourceModeAndLyricKeyRemainDistinct() {
        String text = "/key(C4)\n1 0 2 3\nL: 一 * 三(+1key)\n/key(D4)1";
        assertArrayEquals(new int[]{60, 62, 65, 62}, Jianpu.source(text, "歌词", "score").score.notes.stream().mapToInt(n -> n.pitch).toArray());
        assertArrayEquals(new int[]{62, 64, 67, 63}, Jianpu.source(text, "歌词", "source").score.notes.stream().mapToInt(n -> n.pitch).toArray());
        assertEquals(3, Jianpu.source("|:1 [1 2 :| [2 3", "反复", "source").score.notes.size() - 2);
    }
    @Test public void tiesSelectionAndPreciseRoundTrip() {
        String text = "/key(A3)\nbpm108\n(1_ 1_) 2. 0 3~3";
        Jianpu.Result r = Jianpu.source(text, "延音", "score");
        assertEquals(3, r.score.notes.size()); assertTrue(r.score.notes.get(0).legato);
        int start = text.indexOf("1_");
        Jianpu.Result selected = r.selection(start, start + 2);
        assertEquals(278, selected.score.duration); assertEquals(57, selected.score.notes.get(0).pitch);
        assertThrows(IllegalArgumentException.class, () -> r.selection(start, start + 1));
        Score roundTrip = Jianpu.precise(Jianpu.encode(r.score, 120), 120, "重开").score;
        assertEquals(r.score.duration, roundTrip.duration); assertEquals(r.score.notes.size(), roundTrip.notes.size());
        assertEquals(2, Jianpu.precise("(1 1)", 120, "分音").score.notes.size());
    }
    @Test public void invalidStructuresAndLimitsAreRejected() {
        for (String text : new String[]{"|:1", "[2 1", "1~2", "(1 0 1)", "|:(1:|)", "#0", "1@2", "1\nL: 一 二(+1key)", "bpm1\n1"})
            assertThrows(text, IllegalArgumentException.class, () -> Jianpu.source(text, "错误", "score"));
        assertThrows(IllegalArgumentException.class, () -> Jianpu.precise("1:1/0", 120, "错误"));
        assertThrows(IllegalArgumentException.class, () -> Jianpu.precise("+++++7", 120, "错误"));
    }
    @Test public void normalizedSourceKeepsEditablePositions() {
        String text = "／key（C4）\n１２３"; Jianpu.Result r = Jianpu.source(text, "全角", "score");
        assertEquals("２", text.substring(r.spans.get(1).left, r.spans.get(1).right));
        assertEquals(62, r.selection(r.spans.get(1).left, r.spans.get(1).right).score.notes.get(0).pitch);
    }
    @Test public void sourceTransposeKeepsRhythmAndLyrics() {
        String text = "/key(A3)\nbpm108\n1_ 2. 3\nL: 一 二 三";
        String moved = Jianpu.transpose(text, 2, true, "score"); assertTrue(moved.contains("/key(B3)")); assertTrue(moved.contains("1_ 2. 3\nL: 一 二 三"));
        assertEquals(59, Jianpu.source(moved, "移调", "score").score.notes.get(0).pitch);
    }
    @Test public void pianoPreservesFastAndRepeatedNotes() {
        Score input = new Score("快速", Arrays.asList(new Score.Note(0, 20, 60, 0), new Score.Note(20, 40, 62, 0), new Score.Note(40, 180, 62, 0)), 180);
        assertEquals(3, ScoreTools.melody(input, 0, true).notes.size());
        Score chord = new Score("和弦", Arrays.asList(new Score.Note(0, 2000, 48, 0), new Score.Note(10, 600, 72, 0), new Score.Note(800, 1000, 74, 0)), 2200);
        assertEquals(2, ScoreTools.melody(chord, 0, true).notes.size()); assertEquals(72, ScoreTools.melody(chord, 0, true).notes.get(0).pitch);
        assertTrue(ScoreTools.melody(chord, 0, false).notes.size() > 2);
    }
    @Test public void segmentsClipSustainRepeatAndSeek() {
        Score s = Score.jianpu("1:2 2 0", 120, "编排");
        Score part = ScoreTools.arrange(s, Arrays.asList(new ScoreTools.Segment(250, 750, 2), new ScoreTools.Segment(1000, 1500, 1)));
        assertEquals(1500, part.duration); assertEquals(3, part.notes.size()); assertEquals(500, part.notes.get(1).start);
        assertThrows(IllegalArgumentException.class, () -> ScoreTools.arrange(s, Collections.singletonList(new ScoreTools.Segment(0, 2500, 1))));
        Transport p = new Transport(2000, 1); p.play(0, 0); long generation = p.generation; p.seek(700);
        assertFalse(p.active()); assertTrue(p.generation > generation); assertEquals(700, p.position(1000)); p.play(2000, 0); assertEquals(900, p.position(2200));
    }
    @Test public void originalTextAndLegatoSurviveSaveWithoutChangingOriginal() throws Exception {
        java.io.File folder = Files.createTempDirectory("melodica-edit-").toFile();
        try {
            Library library = new Library(folder); String original = library.save(Score.jianpu("1 2", 100, "原曲"));
            String text = "/key(D4)\nbpm120\n(1 1) 2"; Score score = Jianpu.source(text, "修改版", "score").score;
            String saved = library.saveDocument(new Library.Document(score, text, 120, "score", "https://jianpu.space/", "简谱"));
            assertNotEquals(original, saved); assertEquals(2, library.read(original).notes.size());
            assertEquals(text, library.document(saved, -2, false).text); assertTrue(library.read(saved).notes.get(0).legato);
            assertThrows(IllegalArgumentException.class, () -> library.saveDocument(new Library.Document(score, "1 2 3", 120, "precise", "", "简谱")));
        } finally { for (java.io.File f : folder.listFiles()) Files.delete(f.toPath()); Files.delete(folder.toPath()); }
    }
}
