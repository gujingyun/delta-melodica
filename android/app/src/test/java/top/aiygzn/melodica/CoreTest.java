package top.aiygzn.melodica;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.util.Arrays;

public class CoreTest {
    @Test public void jianpuKeepsRestAndRepeat() {
        Score s = Score.jianpu("1 1:1/2 0:2 +1 #4", 120, "测试");
        assertEquals(4, s.notes.size()); assertEquals(500, s.notes.get(1).start);
        assertEquals(1750, s.notes.get(2).start); assertEquals(72, s.notes.get(2).pitch);
        assertEquals(66, s.notes.get(3).pitch); assertEquals(2750, s.duration);
    }
    @Test public void jianpuRejectsBadData() {
        for (String s : new String[]{"0", "+0", "#0", "1:1/0", "1:0", "9", "1:99999", "1:0.001"})
            assertThrows(IllegalArgumentException.class, () -> Score.jianpu(s, 100, "测试"));
        assertThrows(IllegalArgumentException.class, () -> Score.jianpu("1", Double.NaN, "测试"));
    }
    @Test public void mappingFoldsOnlyOctaves() {
        assertEquals(0, Score.map(48, 60, false, false, false).key);
        assertEquals(7, Score.map(72, 60, false, false, false).key);
        assertEquals(-12, Score.map(48, 60, true, true, true).octave);
        assertEquals(1, Score.map(61, 60, false, false, true).half);
        assertThrows(IllegalArgumentException.class, () -> Score.map(61, 60, false, false, false));
    }
    @Test public void toneSelectionIsExclusiveAndHalfIndependent() {
        ToneState state = new ToneState(); state.confirmHalf(false);
        Score.Fingering lowHalf = Score.map(49, 60, true, true, true);
        assertEquals(Score.LOW, state.next(lowHalf)); state.applied(Score.LOW);
        assertEquals(Score.HALF, state.next(lowHalf)); state.applied(Score.HALF);
        assertEquals(-1, state.next(lowHalf));
        Score.Fingering highHalf = Score.map(75, 60, true, true, true);
        assertEquals(Score.HIGH, state.next(highHalf)); state.applied(Score.HIGH);
        assertEquals(-1, state.next(highHalf));
        Score.Fingering naturalHalf = Score.map(61, 60, true, true, true);
        assertEquals(Score.NATURAL, state.next(naturalHalf)); state.applied(Score.NATURAL);
        assertEquals(-1, state.next(naturalHalf));
        Score.Fingering natural = Score.map(60, 60, true, true, true);
        assertEquals(Score.HALF, state.next(natural)); state.applied(Score.HALF);
        assertEquals(-1, state.next(natural));
    }
    @Test public void toneNeedsConfirmationAfterInterruption() {
        ToneState state = new ToneState(); Score.Fingering natural = Score.map(60, 60, true, true, true);
        assertThrows(IllegalStateException.class, () -> state.next(natural));
        state.confirmHalf(true); assertEquals(Score.NATURAL, state.next(natural));
        // 未收到点击完成之前，同一步仍然待执行。
        assertEquals(Score.NATURAL, state.next(natural)); state.applied(Score.NATURAL);
        assertEquals(Score.HALF, state.next(natural));
        state.invalidate(); assertFalse(state.known());
        assertThrows(IllegalStateException.class, () -> state.applied(Score.HALF));
        state.confirmHalf(false); assertEquals(Score.NATURAL, state.next(natural));
    }
    @Test public void selectorTimeDoesNotConsumeShortNotes() {
        Transport p = new Transport(1000, 2); p.play(100, 0);
        p.holdClock(125); assertEquals(50, p.position(1000));
        p.holdClock(1100); p.update(1200); assertTrue(p.active());
        p.resumeClock(1300); assertEquals(100, p.position(1325));
        p.holdClock(1325); p.pause(1500); assertEquals(100, p.position(2000));
        p.play(2100, 0); assertEquals(200, p.position(2150));
        p.holdClock(2150); p.stop(); p.play(2500, 0); assertEquals(100, p.position(2550));
    }
    @Test public void melodyDoesNotRefillAccompaniment() {
        Score s = new Score("和弦", Arrays.asList(new Score.Note(0, 2000, 48, 0), new Score.Note(10, 600, 72, 0), new Score.Note(800, 1000, 72, 0)), 2200).melody(0);
        assertEquals(2, s.notes.size()); assertEquals(72, s.notes.get(0).pitch);
        assertEquals(600, s.notes.get(0).end); assertEquals(2200, s.duration);
    }
    @Test public void trackSelectionAndOverlap() {
        Score s = new Score("音轨", Arrays.asList(new Score.Note(0, 500, 48, 0), new Score.Note(0, 500, 72, 1), new Score.Note(300, 700, 74, 1)), 700);
        assertEquals(1, s.recommendedTrack()); assertEquals(300, s.melody(1).notes.get(0).end);
    }
    @Test public void pauseResumeStopAndStaleGeneration() {
        Transport p = new Transport(5000, 1.5);
        p.play(1000, 3000); p.update(3999); assertEquals(0, p.position(3999));
        p.update(4000); assertEquals(1500, p.position(5000));
        long old = p.generation; p.pause(5000); assertTrue(old != p.generation);
        assertEquals(1500, p.position(9000)); p.play(10000, 0);
        assertEquals(2250, p.position(10500)); p.stop(); assertEquals(0, p.position(11000));
    }
    @Test public void cancelCountdownAndFinish() {
        Transport p = new Transport(1000, 1);
        p.play(0, 3000); p.pause(1000); p.update(5000); assertFalse(p.active());
        p.play(6000, 0); p.update(7000); assertEquals(1000, p.position(7000));
        p.play(8000, 0); assertEquals(0, p.position(8000));
    }
    @Test public void midiTempoAcrossTracksAndPercussion() throws Exception {
        byte[] tempo = {(byte)0, (byte)0xff, 0x51, 3, 7, (byte)0xa1, 0x20,
            (byte)0x83, 0x60, (byte)0xff, 0x51, 3, 0x0f, 0x42, 0x40, 0, (byte)0xff, 0x2f, 0};
        byte[] notes = {0, (byte)0x90, 60, 100, (byte)0x83, 0x60, (byte)0x80, 60, 0,
            0, (byte)0x90, 62, 100, (byte)0x83, 0x60, (byte)0x80, 62, 0,
            0, (byte)0x99, 40, 100, 0x60, (byte)0x89, 40, 0, 0, (byte)0xff, 0x2f, 0};
        Score s = MidiReader.read(midi(tempo, notes), "变速");
        assertEquals(2, s.notes.size()); assertEquals(500, s.notes.get(0).end);
        assertEquals(1500, s.notes.get(1).end); assertEquals(1700, s.duration);
    }
    @Test public void midiRunningStatusRepeatAndUnclosedNote() throws Exception {
        byte[] notes = {0, (byte)0x90, 60, 100, 0x60, 60, 0, 0, 60, 100, 0x60, (byte)0xff, 0x2f, 0};
        Score s = MidiReader.read(midi(notes), "重复");
        assertEquals(2, s.notes.size()); assertEquals(100, s.notes.get(1).start); assertEquals(200, s.notes.get(1).end);
    }
    @Test public void midiRejectsTruncatedAndInvalidVlq() throws Exception {
        assertThrows(Exception.class, () -> MidiReader.read(new byte[]{1, 2}, "损坏"));
        assertThrows(Exception.class, () -> MidiReader.read(midi(new byte[]{(byte)0x80, (byte)0x80, (byte)0x80, (byte)0x80, 0}), "损坏"));
        assertThrows(Exception.class, () -> MidiReader.read(midi(new byte[]{0, 60, 100}), "损坏"));
    }
    private static byte[] midi(byte[]... tracks) throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(); DataOutputStream out = new DataOutputStream(bytes);
        out.writeInt(0x4d546864); out.writeInt(6); out.writeShort(tracks.length > 1 ? 1 : 0); out.writeShort(tracks.length); out.writeShort(480);
        for (byte[] track : tracks) { out.writeInt(0x4d54726b); out.writeInt(track.length); out.write(track); }
        return bytes.toByteArray();
    }
}
