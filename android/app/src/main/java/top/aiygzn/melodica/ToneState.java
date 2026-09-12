package top.aiygzn.melodica;

/** 三选一音区与独立半音开关；只在点击成功后记录状态。 */
public final class ToneState {
    private int tone = -1, half = -1;
    public void invalidate() { tone = -1; half = -1; }
    public void confirmHalf(boolean selected) { tone = -1; half = selected ? 1 : 0; }
    public boolean known() { return half >= 0; }
    public int next(Score.Fingering fingering) {
        if (!known()) throw new IllegalStateException("请确认游戏内半音当前是否选中");
        if (tone != fingering.tonePoint()) return fingering.tonePoint();
        return half != fingering.half ? Score.HALF : -1;
    }
    public void applied(int point) {
        if (!known()) throw new IllegalStateException("半音状态未知");
        if (point == Score.HALF) half = 1 - half;
        else if (point == Score.LOW || point == Score.HIGH || point == Score.NATURAL) tone = point;
        else throw new IllegalArgumentException("不是变音按钮");
    }
}
