package top.aiygzn.melodica;

/** 三选一音区与独立半音开关；只在点击成功后记录状态。 */
public final class ToneState {
    private int tone = -1, half = -1;
    public void invalidate() { tone = -1; half = -1; }
    public void confirmHalf(boolean selected) { tone = -1; half = selected ? 1 : 0; }
    public boolean known() { return half >= 0; }
    public int next(Score.Fingering fingering) {
        if (!known()) throw new IllegalStateException("请先将游戏内半音设为未选中，等待准备完成");
        if (tone != fingering.tonePoint()) return fingering.tonePoint();
        return half != fingering.half ? Score.HALF : -1;
    }
    /** 一次准备完整的顺序点击；生成计划不改变选中状态，完成后才提交。 */
    public int[] steps(Score.Fingering fingering) {
        int first = next(fingering);
        if (first < 0) return new int[0];
        return first != Score.HALF && half != fingering.half ? new int[]{first, Score.HALF} : new int[]{first};
    }
    public void applied(int point) {
        if (!known()) throw new IllegalStateException("半音状态未知");
        if (point == Score.HALF) half = 1 - half;
        else if (point == Score.LOW || point == Score.HIGH || point == Score.NATURAL) tone = point;
        else throw new IllegalArgumentException("不是变音按钮");
    }
}
