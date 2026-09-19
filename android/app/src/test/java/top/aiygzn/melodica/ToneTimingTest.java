package top.aiygzn.melodica;

import org.junit.Test;
import static org.junit.Assert.*;

public class ToneTimingTest {
    private long release(int pitch, long end, long nextStart, int nextPitch, double speed) {
        return ToneTiming.releaseAt(new Score.Note(0, end, pitch, 0), new Score.Note(nextStart, nextStart + 500, nextPitch, 0),
            Score.map(pitch, 60, true, true, true), Score.map(nextPitch, 60, true, true, true), speed);
    }
    @Test public void octaveAndHalfEachReserveOneClick() {
        assertEquals(431, release(60, 500, 500, 74, 1));
        assertEquals(431, release(60, 500, 500, 61, 1));
        assertEquals(391, release(60, 500, 500, 75, 1));
    }
    @Test public void restsAndUnchangedToneKeepOriginalDuration() {
        assertEquals(475, release(60, 500, 1000, 75, 1));
        assertEquals(475, release(60, 500, 500, 62, 1));
        assertEquals(475, release(60, 500, 500, 60, 1));
        assertEquals(441, release(60, 500, 550, 75, 1));
    }
    @Test public void speedConvertsReserveWithoutShrinkingTap() {
        assertEquals(375, release(60, 500, 500, 74, 2));
        assertEquals(375, release(60, 500, 500, 75, 2));
        assertEquals(472, release(60, 500, 500, 75, .25));
    }
    @Test public void veryShortNotesKeepAtLeastThreeQuarters() {
        for (int length : new int[]{10, 40, 125, 250}) for (double speed : new double[]{.25, 1, 2}) {
            long end = release(60, length, length, 75, speed);
            assertTrue(end >= length - length / 4);
            assertTrue(end < length);
        }
    }
    @Test public void finalAndLegatoNotesKeepTheirOriginalGapWithoutSwitch() {
        Score.Note note = new Score.Note(0, 500, 60, 0, true);
        Score.Fingering f = Score.map(60, 60, true, true, true);
        assertEquals(488, ToneTiming.releaseAt(note, null, f, null, 1));
        assertEquals(488, ToneTiming.releaseAt(note, new Score.Note(500, 1000, 62, 0), f,
            Score.map(62, 60, true, true, true), 1));
    }
    @Test public void fastSwitchReservesSameGapForOneOrTwoSelectors() {
        Score.Note note = new Score.Note(0, 500, 60, 0);
        Score.Fingering current = Score.map(60, 60, true, true, true);
        for (int pitch : new int[]{61, 74, 75}) {
            Score.Fingering next = Score.map(pitch, 60, true, true, true);
            assertEquals(472, ToneTiming.releaseAt(note, new Score.Note(500, 1000, pitch, 0), current, next, 1, true));
            assertEquals(444, ToneTiming.releaseAt(note, new Score.Note(500, 1000, pitch, 0), current, next, 2, true));
            assertEquals(475, ToneTiming.releaseAt(note, new Score.Note(1000, 1500, pitch, 0), current, next, 1, true));
        }
    }
    @Test public void fastSwitchKeepsShortNotesAndExistingNoSwitchArticulation() {
        Score.Fingering current = Score.map(60, 60, true, true, true), next = Score.map(75, 60, true, true, true);
        for (int length : new int[]{10, 40, 125}) {
            Score.Note note = new Score.Note(0, length, 60, 0), following = new Score.Note(length, length + 500, 75, 0);
            assertTrue(ToneTiming.releaseAt(note, following, current, next, 2, true) >= length - length / 4);
            assertEquals(ScoreTools.releaseAt(note), ToneTiming.releaseAt(note, following, current, current, 2, true));
            assertEquals(ScoreTools.releaseAt(note), ToneTiming.releaseAt(note, null, current, null, 2, true));
        }
    }
}
