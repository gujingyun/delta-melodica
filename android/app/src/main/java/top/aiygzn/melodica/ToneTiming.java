package top.aiygzn.melodica;

/** 为变音预留有限气口；优先利用休止，短音至少保留原时值的四分之三。 */
public final class ToneTiming {
    public static final long TAP_MS = 32, SETTLE_MS = 8, RELEASE_GAP_MS = 1;
    private ToneTiming() { }
    // 快速模式将触摸预算分给需要改变的按钮，完成后仍由播放器回调检查再发下一音。
    public static long tapMs(int steps, boolean fast) { return fast ? 6 / steps : TAP_MS; }
    public static long betweenMs(boolean fast) { return fast ? 1 : SETTLE_MS; }
    public static long settleMs(boolean fast) { return fast ? 0 : SETTLE_MS; }
    public static long releaseAt(Score.Note note, Score.Note next, Score.Fingering current,
                                 Score.Fingering upcoming, double speed) {
        return releaseAt(note, next, current, upcoming, speed, false);
    }
    public static long releaseAt(Score.Note note, Score.Note next, Score.Fingering current,
                                 Score.Fingering upcoming, double speed, boolean fast) {
        long normal = ScoreTools.releaseAt(note);
        if (next == null) return normal;
        int steps = (current.tonePoint() == upcoming.tonePoint() ? 0 : 1) + (current.half == upcoming.half ? 0 : 1);
        if (steps == 0) return normal;
        // 包含松键后的间隔和回调余量，播放倍率只换算谱面气口，不缩短真实点击。
        // 快速气口给出 28 毫秒预算，实际间隔还包含后续派发开销。
        long reserve = (long) Math.ceil((fast ? 28 : steps * (TAP_MS + SETTLE_MS) + RELEASE_GAP_MS + 28) * speed);
        long earliest = note.end - (note.end - note.start) / 4;
        return Math.min(normal, Math.max(earliest, next.start - reserve));
    }
}
