package top.aiygzn.melodica;

/** 使用单调时钟的播放状态，暂停保留位置，停止归零。 */
public final class Transport {
    public enum State { READY, COUNTDOWN, PLAYING, PAUSED }
    public State state = State.READY;
    public long generation;
    private long position, origin, deadline;
    private long clockLimit = Long.MAX_VALUE;
    public final long duration;
    public final double speed;
    public Transport(long duration, double speed) {
        if (duration <= 0 || !Double.isFinite(speed) || speed < .25 || speed > 2) throw new IllegalArgumentException("播放参数无效");
        this.duration = duration; this.speed = speed;
    }
    public long position(long now) {
        return Math.min(Math.min(duration, clockLimit), state == State.PLAYING ? position + Math.max(0, Math.round((now - origin) * speed)) : position);
    }
    public void play(long now, long countdown) {
        if (state == State.PLAYING || state == State.COUNTDOWN) return;
        if (position >= duration) position = 0;
        generation++; deadline = now + countdown; origin = now; clockLimit = Long.MAX_VALUE;
        state = countdown > 0 ? State.COUNTDOWN : State.PLAYING;
    }
    public void update(long now) {
        if (state == State.COUNTDOWN && now >= deadline) { origin = now; state = State.PLAYING; }
        if (state == State.PLAYING && position(now) >= duration) { position = duration; state = State.READY; generation++; }
    }
    public long countdown(long now) { return state == State.COUNTDOWN ? Math.max(0, deadline - now) : 0; }
    public void pause(long now) {
        if (state != State.PLAYING && state != State.COUNTDOWN) return;
        position = position(now); state = State.PAUSED; clockLimit = Long.MAX_VALUE; generation++;
    }
    /** 切换按钮时暂缓乐谱时钟，避免触摸回调耗时吞掉短音。 */
    public void holdClock(long now) {
        limitClock(now, position(now));
    }
    /** 先利用现有休止时间，仅在下一音符到点后等待变音完成，避免切换吞音。 */
    public void limitClock(long now, long noteStart) {
        if (active()) clockLimit = Math.min(clockLimit, Math.max(position(now), noteStart));
    }
    public void resumeClock(long now) {
        if (clockLimit != Long.MAX_VALUE) { position = position(now); origin = now; clockLimit = Long.MAX_VALUE; }
    }
    public void stop() { position = 0; state = State.READY; clockLimit = Long.MAX_VALUE; generation++; }
    public void seek(long value) {
        position = Math.max(0, Math.min(duration, value)); state = State.PAUSED; clockLimit = Long.MAX_VALUE; generation++;
    }
    public boolean active() { return state == State.PLAYING || state == State.COUNTDOWN; }
}
