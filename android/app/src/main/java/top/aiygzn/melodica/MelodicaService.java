package top.aiygzn.melodica;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.app.KeyguardManager;
import android.content.Intent;
import android.content.res.Configuration;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Point;
import android.graphics.PointF;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import java.util.Locale;

/** 无障碍悬浮控制与触摸后端，所有窗口和调度操作都在主线程。 */
public final class MelodicaService extends AccessibilityService {
    public static MelodicaService instance;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private Settings settings;
    private WindowManager windows;
    private LinearLayout panel;
    private WindowManager.LayoutParams panelParams;
    private TextView status;
    private Button play;
    private LinearLayout halfConfirmation;
    private boolean awaitingHalf;
    private final ToneState tones = new ToneState();
    private Calibration calibration;
    private Score score;
    private Transport transport;
    private String message = "选择曲目后，进入游戏校准音键";
    private GestureDescription.StrokeDescription[] held;
    private PointF[] anchors, endpoints;
    private boolean inFlight, destroyed;
    private long gestureSerial;
    private long cancelledAt;
    private int heldIndex = -1;
    private final Runnable pumpTask = this::pump;
    private final Runnable watchdog = () -> fail("触摸回调超时，已关闭服务，请重新开启");
    private final Runnable heartbeat = new Runnable() {
        @Override public void run() {
            if (destroyed) return;
            if (transport != null && transport.active() && !ready()) pause("已离开目标窗口或屏幕发生变化");
            if (awaitingHalf && !ready()) pause("画面变化，请重新确认半音状态");
            if (calibration != null && !calibration.valid()) closeCalibration();
            render(); handler.postDelayed(this, 100);
        }
    };
    @Override protected void onServiceConnected() {
        instance = this; settings = new Settings(this); windows = (WindowManager) getSystemService(WINDOW_SERVICE);
        try { Score stored = new Library(this).read(settings.selected()); load(stored.melody(stored.recommendedTrack())); }
        catch (Exception e) { load(Score.jianpu(Score.STAR, 100, "小星星")); }
        showPanel(); handler.post(heartbeat);
    }
    public void load(Score value) {
        stop(); score = value; transport = new Transport(value.duration, settings.speed()); message = "已准备：" + value.title; render();
    }
    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private Point size() { Point point = new Point(); windows.getDefaultDisplay().getRealSize(point); return point; }
    private int rotation() { return windows.getDefaultDisplay().getRotation(); }
    private String foreground() {
        try {
            for (AccessibilityWindowInfo window : getWindows()) {
                if (window.getType() == AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY || !window.isActive()) continue;
                AccessibilityNodeInfo root = window.getRoot();
                if (root == null) return "";
                CharSequence name = root.getPackageName(); root.recycle();
                return name == null ? "" : name.toString();
            }
        } catch (RuntimeException ignored) { /* 无法确认前台窗口时不发出手势。 */ }
        return "";
    }
    private boolean screenReady() {
        return ((PowerManager) getSystemService(POWER_SERVICE)).isInteractive()
            && !((KeyguardManager) getSystemService(KEYGUARD_SERVICE)).isKeyguardLocked();
    }
    private boolean ready() {
        Point size = size();
        return screenReady() && settings.calibrated() && !settings.target().isEmpty() && settings.target().equals(foreground())
            && size.x == settings.width() && size.y == settings.height() && rotation() == settings.rotation()
            && ( !settings.target().equals(getPackageName()) || TouchTestActivity.active );
    }
    public void showPanel() {
        if (panel != null || destroyed) return;
        panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL); panel.setPadding(dp(10), dp(7), dp(10), dp(7));
        GradientDrawable bg = new GradientDrawable(); bg.setColor(Color.rgb(20, 39, 41)); bg.setCornerRadius(dp(16)); bg.setStroke(dp(1), Color.rgb(76, 129, 114)); panel.setBackground(bg);
        TextView title = new TextView(this); title.setText("口风琴  ·  拖动这里移动"); title.setTextSize(13); title.setTextColor(0xff66e3ac); title.setPadding(0, dp(3), 0, dp(5)); panel.addView(title);
        status = new TextView(this); status.setTextSize(11); status.setTextColor(Color.WHITE); status.setMaxLines(2); panel.addView(status);
        LinearLayout row = new LinearLayout(this); panel.addView(row);
        play = button(row, "播放", this::toggle);
        button(row, "停止", this::stop);
        button(row, "校准", this::startCalibration);
        button(row, "收起", () -> { stop(); hidePanel(); });
        halfConfirmation = new LinearLayout(this); halfConfirmation.setOrientation(LinearLayout.VERTICAL);
        TextView question = new TextView(this); question.setText("游戏内「半音」当前是否选中？"); question.setTextColor(Color.WHITE); question.setTextSize(13); halfConfirmation.addView(question);
        LinearLayout choices = new LinearLayout(this); halfConfirmation.addView(choices);
        button(choices, "未选中", () -> confirmHalfState(false));
        button(choices, "已选中", () -> confirmHalfState(true));
        button(choices, "取消", () -> { dismissHalfConfirmation(); message = "已取消播放"; render(); });
        panel.addView(halfConfirmation); halfConfirmation.setVisibility(View.GONE);
        panelParams = new WindowManager.LayoutParams(dp(300), WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY, WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE, PixelFormat.TRANSLUCENT);
        panelParams.gravity = Gravity.TOP | Gravity.LEFT; panelParams.x = dp(12); panelParams.y = dp(24);
        title.setOnTouchListener(new View.OnTouchListener() {
            float x, y; int startX, startY;
            @Override public boolean onTouch(View view, MotionEvent event) {
                if (event.getAction() == MotionEvent.ACTION_DOWN) { x = event.getRawX(); y = event.getRawY(); startX = panelParams.x; startY = panelParams.y; return true; }
                if (event.getAction() == MotionEvent.ACTION_MOVE) {
                    Point screen = size(); panelParams.x = Math.max(0, Math.min(screen.x - panel.getWidth(), startX + Math.round(event.getRawX() - x)));
                    panelParams.y = Math.max(0, Math.min(screen.y - panel.getHeight() - dp(24), startY + Math.round(event.getRawY() - y)));
                    windows.updateViewLayout(panel, panelParams); return true;
                }
                return true;
            }
        });
        try { windows.addView(panel, panelParams); } catch (RuntimeException e) { panel = null; notifyUser("悬浮窗创建失败：" + e.getMessage()); }
        render();
    }
    private Button button(LinearLayout row, String text, Runnable click) {
        Button button = new Button(this); button.setText(text); button.setTextSize(12); button.setMinWidth(0); button.setMinimumWidth(0); button.setPadding(0, 0, 0, 0);
        row.addView(button, new LinearLayout.LayoutParams(0, dp(44), 1)); button.setOnClickListener(v -> click.run()); return button;
    }
    public void hidePanel() {
        dismissHalfConfirmation();
        closeCalibration();
        if (panel != null) { windows.removeView(panel); panel = null; status = null; play = null; halfConfirmation = null; }
    }
    private void render() {
        if (status == null) return;
        String detail = message;
        if (transport != null && score != null) {
            long now = SystemClock.uptimeMillis();
            if (transport.state == Transport.State.COUNTDOWN) detail = "准备 " + ((transport.countdown(now) + 999) / 1000) + " 秒";
            else if (transport.state == Transport.State.PLAYING) detail = "正在演奏";
            detail = score.title + "  " + time(transport.position(now)) + " / " + time(score.duration) + "\n" + detail;
            play.setText(transport.active() ? "暂停" : transport.state == Transport.State.PAUSED ? "继续" : "播放");
        }
        status.setText(detail);
    }
    static String time(long ms) { return String.format(Locale.ROOT, "%02d:%02d", ms / 60000, ms / 1000 % 60); }
    private void notifyUser(String text) { message = text; Toast.makeText(this, text, Toast.LENGTH_LONG).show(); render(); }
    public void toggle() {
        if (transport == null || calibration != null) return;
        if (transport.active()) { pause("已暂停"); return; }
        if (awaitingHalf) return;
        // 手指点悬浮按钮时系统会先取消演奏手势，避免该次抬手又触发继续。
        if (transport.state == Transport.State.PAUSED && SystemClock.uptimeMillis() - cancelledAt < 400) return;
        if (inFlight || held != null) { notifyUser("正在释放触摸，请稍后重试"); return; }
        if (!validateStart()) return;
        showPanel(); awaitingHalf = true; tones.invalidate();
        halfConfirmation.setVisibility(View.VISIBLE); message = "先确认半音当前状态，再开始演奏"; render();
    }
    private boolean validateStart() {
        if (!ready()) { notifyUser("请进入目标窗口并完成 12 点校准；升级或旋转屏幕后需重新校准"); return false; }
        try {
            for (Score.Note n : score.notes) settings.fingering(n.pitch);
            for (int point : Score.CALIBRATION_ORDER) {
                PointF p = settings.point(point);
                if (p == null) throw new IllegalArgumentException("请重新校准「" + Score.LABELS[point] + "」");
                if (covers(p)) throw new IllegalArgumentException("悬浮窗挡住了「" + Score.LABELS[point] + "」，请拖到空白区域");
            }
        } catch (IllegalArgumentException e) { notifyUser(e.getMessage()); return false; }
        return true;
    }
    private void dismissHalfConfirmation() {
        awaitingHalf = false;
        if (halfConfirmation != null) halfConfirmation.setVisibility(View.GONE);
    }
    void confirmHalfState(boolean selected) {
        if (!awaitingHalf) return;
        dismissHalfConfirmation();
        if (transport == null || transport.active() || inFlight || held != null || !validateStart()) return;
        tones.confirmHalf(selected);
        transport.play(SystemClock.uptimeMillis(), transport.state == Transport.State.PAUSED ? 0 : 3000);
        message = "正在演奏"; schedule(0);
    }
    private boolean covers(PointF p) {
        if (panel == null || panel.getVisibility() != View.VISIBLE) return false;
        int[] location = new int[2]; panel.getLocationOnScreen(location);
        return p.x >= location[0] && p.x < location[0] + panel.getWidth() && p.y >= location[1] && p.y < location[1] + panel.getHeight();
    }
    public void pause(String reason) {
        dismissHalfConfirmation(); tones.invalidate();
        if (transport != null) transport.pause(SystemClock.uptimeMillis());
        message = reason; handler.removeCallbacks(pumpTask);
        if (!inFlight) release(); render();
    }
    public void stop() {
        dismissHalfConfirmation(); tones.invalidate();
        if (transport != null) transport.stop();
        message = "已停止，回到曲首"; handler.removeCallbacks(pumpTask);
        if (!inFlight) release(); render();
    }
    private void schedule(long delay) { handler.removeCallbacks(pumpTask); if (!destroyed) handler.postDelayed(pumpTask, delay); }
    private void pump() {
        if (destroyed || inFlight || transport == null) return;
        if (!transport.active()) { release(); return; }
        if (!ready()) { pause("已切出目标窗口，保留进度"); return; }
        long now = SystemClock.uptimeMillis(); transport.update(now);
        if (transport.state == Transport.State.COUNTDOWN) { schedule(20); return; }
        if (!transport.active()) { message = "演奏结束"; release(); render(); return; }
        long position = transport.position(now);
        int index = findNote(position);
        if (held != null && heldIndex != index) { release(); return; }
        if (index < 0) { schedule(15); return; }
        Score.Note n = score.notes.get(index);
        Score.Fingering fingering = settings.fingering(n.pitch);
        if (!tones.known()) { pause("变音状态不明，请确认半音后继续"); return; }
        int selector = tones.next(fingering);
        if (selector >= 0) {
            // 必须先抬起音键，再依次点击音区和半音；这些按钮不能与音键一起长按。
            if (held != null) { release(); return; }
            PointF p = settings.point(selector);
            if (p == null || covers(p)) { pause("变音按钮被遮挡或校准已失效"); return; }
            transport.holdClock(now);
            Transport batch = transport; long generation = batch.generation;
            Path path = new Path(); path.moveTo(p.x, p.y);
            dispatch(new GestureDescription.StrokeDescription[]{new GestureDescription.StrokeDescription(path, 0, 45)}, false, () -> {
                if (transport == batch && batch.generation == generation && batch.active() && ready()) tones.applied(selector);
                else tones.invalidate();
            }, 20);
            return;
        }
        transport.resumeClock(now);
        long end = releaseAt(n), remaining = Math.max(1, (long) Math.ceil((end - position) / transport.speed));
        long slice = Math.min(60, remaining); boolean more = remaining > slice;
        if (held == null) {
            int[] ids = {fingering.key};
            held = new GestureDescription.StrokeDescription[ids.length]; heldIndex = index;
            anchors = new PointF[ids.length]; endpoints = new PointF[ids.length];
            for (int i = 0; i < ids.length; i++) {
                PointF p = settings.point(ids[i]);
                if (p == null || covers(p)) { held = null; pause("音键被遮挡或校准已失效"); return; }
                anchors[i] = p; endpoints[i] = p;
                Path path = holdPath(i, more);
                held[i] = new GestureDescription.StrokeDescription(path, 0, slice, more);
            }
        } else {
            for (int i = 0; i < held.length; i++) held[i] = held[i].continueStroke(holdPath(i, more), 0, slice, more);
        }
        dispatch(held, more);
    }
    private Path holdPath(int index, boolean move) {
        PointF start = endpoints[index], anchor = anchors[index];
        Path path = new Path(); path.moveTo(start.x, start.y);
        if (move) {
            // 完全静止的续接会被系统合并为空事件；在键心附近往返一个像素保持长按。
            float x = start.x == anchor.x ? anchor.x + (anchor.x + 1 < settings.width() ? 1 : -1) : anchor.x;
            path.lineTo(x, anchor.y); endpoints[index] = new PointF(x, anchor.y);
        }
        return path;
    }
    private long releaseAt(Score.Note n) { return n.end - Math.min(25, Math.max(1, (n.end - n.start) / 10)); }
    private int findNote(long position) {
        int low = 0, high = score.notes.size() - 1, found = -1;
        while (low <= high) { int mid = (low + high) >>> 1; if (score.notes.get(mid).start <= position) { found = mid; low = mid + 1; } else high = mid - 1; }
        return found >= 0 && position < releaseAt(score.notes.get(found)) ? found : -1;
    }
    private void release() {
        if (inFlight || held == null) { if (transport != null && transport.active() && !inFlight) schedule(0); return; }
        GestureDescription.StrokeDescription[] ending = new GestureDescription.StrokeDescription[held.length];
        for (int i = 0; i < held.length; i++) ending[i] = held[i].continueStroke(holdPath(i, false), 0, 1, false);
        dispatch(ending, false);
    }
    private void dispatch(GestureDescription.StrokeDescription[] strokes, boolean continued) {
        dispatch(strokes, continued, null, 0);
    }
    private void dispatch(GestureDescription.StrokeDescription[] strokes, boolean continued, Runnable completed, long settle) {
        GestureDescription.Builder builder = new GestureDescription.Builder();
        for (GestureDescription.StrokeDescription stroke : strokes) builder.addStroke(stroke);
        inFlight = true; long serial = ++gestureSerial;
        handler.postDelayed(watchdog, 1500);
        try {
            boolean accepted = dispatchGesture(builder.build(), new GestureResultCallback() {
                @Override public void onCompleted(GestureDescription gesture) {
                    if (destroyed || serial != gestureSerial) return;
                    handler.removeCallbacks(watchdog); inFlight = false;
                    if (!continued) { held = null; heldIndex = -1; }
                    if (completed != null) completed.run();
                    if (transport != null && transport.active()) schedule(settle); else release();
                }
                @Override public void onCancelled(GestureDescription gesture) {
                    if (destroyed || serial != gestureSerial) return;
                    handler.removeCallbacks(watchdog); inFlight = false; held = null; heldIndex = -1;
                    cancelledAt = SystemClock.uptimeMillis();
                    pause("触摸被系统或手动操作中断，已暂停");
                }
            }, handler);
            if (!accepted) fail("系统拒绝触摸，已关闭服务，请重新开启");
        } catch (RuntimeException e) { fail("触摸接口异常，已关闭服务"); }
    }
    private void fail(String reason) {
        if (destroyed) return;
        handler.removeCallbacks(watchdog); gestureSerial++; inFlight = false; held = null;
        dismissHalfConfirmation(); tones.invalidate();
        if (transport != null) transport.stop();
        handler.removeCallbacks(pumpTask); notifyUser(reason);
        // 接口状态不明时断开服务，让系统清理该服务的触摸序列。
        disableSelf();
    }
    private void startCalibration() {
        stop();
        if (inFlight || held != null) { notifyUser("请待触摸释放后再校准"); return; }
        String target = foreground();
        if (!screenReady() || target.isEmpty() || (target.equals(getPackageName()) && !TouchTestActivity.active)
            || target.equals("com.android.systemui") || target.contains("launcher") || target.equals("com.android.settings")) {
            notifyUser("先进入游戏演奏画面，再点悬浮窗的校准"); return;
        }
        closeCalibration(); calibration = new Calibration(target);
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(-1, -1, WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN, PixelFormat.TRANSLUCENT);
        if (android.os.Build.VERSION.SDK_INT >= 28) params.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
        panel.setVisibility(View.GONE); windows.addView(calibration, params);
    }
    private void closeCalibration() {
        if (calibration != null) { windows.removeView(calibration); calibration = null; }
        if (panel != null) panel.setVisibility(View.VISIBLE);
    }
    private final class Calibration extends View {
        final String target; final Point screen = size(); final int orientation = rotation();
        final PointF[] points = new PointF[Score.LABELS.length]; final int[] required = Score.CALIBRATION_ORDER;
        final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG); int index;
        Calibration(String target) { super(MelodicaService.this); this.target = target; }
        boolean valid() { Point s = size(); return screenReady() && target.equals(foreground()) && screen.equals(s) && orientation == rotation(); }
        @Override protected void onDraw(Canvas canvas) {
            canvas.drawColor(0x25000000); paint.setColor(0xeb102829); canvas.drawRect(0, 0, getWidth(), dp(76), paint);
            paint.setColor(0xff66e3ac); paint.setTextSize(dp(18));
            canvas.drawText("请点按钮中心：" + Score.LABELS[required[index]] + "（" + (index + 1) + "/" + required.length + "）", dp(18), dp(28), paint);
            paint.setColor(Color.WHITE); paint.setTextSize(dp(12)); canvas.drawText("仅标记位置，不会点击游戏  ·  " + target, dp(18), dp(53), paint);
            paint.setTextSize(dp(14)); canvas.drawText("撤销", getWidth() - dp(120), dp(30), paint); canvas.drawText("取消", getWidth() - dp(58), dp(30), paint);
            int[] origin = new int[2]; getLocationOnScreen(origin);
            for (int i = 0; i < points.length; i++) if (points[i] != null) {
                float x = points[i].x - origin[0], y = points[i].y - origin[1];
                paint.setTextSize(dp(12)); paint.setTextAlign(Paint.Align.CENTER);
                paint.setColor(0xff66e3ac); canvas.drawCircle(x, y, Math.max(dp(17), paint.measureText(Score.LABELS[i]) / 2 + dp(5)), paint);
                paint.setColor(0xff102829); canvas.drawText(Score.LABELS[i], x, y + dp(4), paint);
            }
            paint.setTextAlign(Paint.Align.LEFT);
        }
        @Override public boolean onTouchEvent(MotionEvent event) {
            if (event.getActionMasked() != MotionEvent.ACTION_UP) return true;
            if (!valid()) { closeCalibration(); notifyUser("画面变化，校准已取消"); return true; }
            if (event.getY() < dp(76)) {
                if (event.getX() > getWidth() - dp(70)) closeCalibration();
                else if (event.getX() > getWidth() - dp(140) && index > 0) { points[required[--index]] = null; invalidate(); }
                return true;
            }
            PointF p = new PointF(event.getRawX(), event.getRawY());
            if (p.x < 0 || p.y < 0 || p.x >= screen.x || p.y >= screen.y) return true;
            for (PointF old : points) if (old != null && Math.hypot(old.x - p.x, old.y - p.y) < dp(12)) { notifyUser("两个音键太近，请重新点选"); return true; }
            points[required[index++]] = p;
            if (index == required.length) {
                settings.calibrate(target, screen.x, screen.y, orientation, points); closeCalibration(); notifyUser("校准已保存，可以播放");
            } else invalidate();
            return true;
        }
    }
    @Override public void onAccessibilityEvent(AccessibilityEvent event) {
        if (transport != null && transport.active() && !ready()) pause("已切出目标窗口，保留进度");
    }
    @Override public void onInterrupt() { pause("无障碍服务被中断"); }
    @Override public void onConfigurationChanged(Configuration config) {
        super.onConfigurationChanged(config); pause("屏幕方向变化，请重新校准"); closeCalibration();
        if (panel != null) { panelParams.x = dp(12); panelParams.y = dp(24); windows.updateViewLayout(panel, panelParams); }
    }
    @Override public boolean onUnbind(Intent intent) { shutdown(); return super.onUnbind(intent); }
    @Override public void onDestroy() { shutdown(); super.onDestroy(); }
    private void shutdown() {
        if (destroyed) return;
        destroyed = true; if (transport != null) transport.stop(); handler.removeCallbacksAndMessages(null);
        gestureSerial++; inFlight = false; held = null; hidePanel(); if (instance == this) instance = null;
    }
}
