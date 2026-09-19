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
import android.text.TextUtils;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
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
    private TextView title, status;
    private Button play, collapse, calibrate;
    private LinearLayout panelHeader, controls;
    private LinearLayout detailPanel, detailHeader, songList, detailControls;
    private WindowManager.LayoutParams detailParams;
    private TextView detailStatus;
    private android.widget.SeekBar progress;
    private boolean seeking;
    private Button expand, detailPlay;
    private boolean awaitingHalf, compactPanel, panelTouching, detailVisible, restoreDetail;
    private String selectedSongId;
    private final ToneState tones = new ToneState();
    private Calibration calibration;
    private Score score;
    private Score.Fingering[] fingerings;
    private long[] releaseTimes;
    private boolean fastSwitch;
    private Transport transport;
    private String message = "选择曲目后，进入游戏校准音键";
    private GestureDescription.StrokeDescription[] held;
    private PointF[] anchors, endpoints;
    private boolean inFlight, destroyed;
    private long gestureSerial;
    private long cancelledAt;
    private int heldIndex = -1;
    private final Runnable pumpTask = this::pump;
    private final Runnable halfPromptTask = this::finishHalfPrompt;
    private final Runnable watchdog = () -> fail("触摸回调超时，已关闭服务，请重新开启");
    private final Runnable heartbeat = new Runnable() {
        @Override public void run() {
            if (destroyed) return;
            if (transport != null && transport.active() && !ready()) pause("已离开目标窗口或屏幕发生变化");
            if (awaitingHalf && !ready()) pause("画面变化，请先将半音设为未选中后再播放");
            if (calibration != null && !calibration.valid()) closeCalibration();
            render(); handler.postDelayed(this, 100);
        }
    };
    @Override protected void onServiceConnected() {
        // 同一服务实例重新绑定时清理旧回调，只恢复待机，不能沿用退出标记或自动续播。
        shutdown(); destroyed = false;
        instance = this; settings = new Settings(this); windows = (WindowManager) getSystemService(WINDOW_SERVICE);
        try { selectedSongId = settings.selected(); Library library = new Library(this); Score stored = library.read(selectedSongId); load(settings.prepare(stored, library.kind(selectedSongId).equals("MIDI"))); }
        catch (Exception e) { load(Score.jianpu(Score.STAR, 100, "小星星")); }
        showPanel(); handler.post(heartbeat);
    }
    public void load(Score value) {
        stop(); settings = new Settings(this); score = value; selectedSongId = settings.selected(); transport = new Transport(value.duration, settings.speed()); message = "已准备：" + value.title; render();
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
        if (destroyed) return;
        if (panel == null) createPanel();
        if (panel == null) return;
        hideDetail(false);
        panel.setVisibility(View.VISIBLE);
        compactPanel = true; panelTouching = false;
        render();
    }
    private void createPanel() {
        panel = new LinearLayout(this); panel.setOrientation(LinearLayout.HORIZONTAL); panel.setPadding(dp(6), dp(4), dp(6), dp(4)); panel.setGravity(Gravity.CENTER_VERTICAL);
        GradientDrawable bg = new GradientDrawable(); bg.setColor(Color.rgb(20, 39, 41)); bg.setCornerRadius(dp(16)); bg.setStroke(dp(1), Color.rgb(76, 129, 114)); panel.setBackground(bg);
        panelHeader = new LinearLayout(this); panelHeader.setOrientation(LinearLayout.HORIZONTAL); panelHeader.setGravity(Gravity.CENTER_VERTICAL); panelHeader.setMinimumHeight(dp(48)); panel.addView(panelHeader);
        status = new TextView(this); status.setTextSize(14); status.setTextColor(Color.WHITE); status.setGravity(Gravity.CENTER_VERTICAL); status.setSingleLine(); status.setEllipsize(TextUtils.TruncateAt.END); panelHeader.addView(status, new LinearLayout.LayoutParams(0, -2, 1));
        panelHeader.setContentDescription("拖动移动悬浮控制条");
        controls = new LinearLayout(this); panel.addView(controls);
        play = button(controls, "播放", this::toggle);
        expand = button(controls, "展开", this::openDetail);
        panelParams = new WindowManager.LayoutParams(panelWidth(), WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY, WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE, PixelFormat.TRANSLUCENT);
        panelParams.gravity = Gravity.TOP | Gravity.LEFT; panelParams.x = dp(12); panelParams.y = dp(24);
        panelHeader.setOnTouchListener(new View.OnTouchListener() {
            float x, y; int startX, startY;
            @Override public boolean onTouch(View view, MotionEvent event) {
                trackPanelTouch(event);
                if (event.getAction() == MotionEvent.ACTION_DOWN) {
                    // 移动前主动暂停，避免后续演奏手势打断拖动或碰到移动后的控制条。
                    if (transport != null && transport.active()) pause("移动悬浮窗，已暂停");
                    x = event.getRawX(); y = event.getRawY(); startX = panelParams.x; startY = panelParams.y; return true;
                }
                if (event.getAction() == MotionEvent.ACTION_MOVE) {
                    panelParams.x = startX + Math.round(event.getRawX() - x); panelParams.y = startY + Math.round(event.getRawY() - y);
                    constrainPanel(); windows.updateViewLayout(panel, panelParams); return true;
                }
                return true;
            }
        });
        // 字体变化和旋转后按实际尺寸收回屏幕内，保留播放时间和按钮。
        panel.addOnLayoutChangeListener((v, l, t, r, b, oldL, oldT, oldR, oldB) -> {
            if (panel != null && constrainPanel()) windows.updateViewLayout(panel, panelParams);
        });
        try { windows.addView(panel, panelParams); }
        catch (RuntimeException e) { panel = null; notifyUser("悬浮窗创建失败：" + ErrorMessages.userMessage(e, "请检查悬浮窗权限")); }
    }
    private Button button(LinearLayout row, String text, Runnable click) {
        Button button = new Button(this); button.setText(text); button.setTextSize(12); button.setMinWidth(0); button.setMinimumWidth(0); button.setPadding(0, 0, 0, 0);
        button.setSingleLine(); button.setMinHeight(dp(48)); button.setMinimumHeight(dp(48));
        row.addView(button, new LinearLayout.LayoutParams(0, -2, 1)); button.setOnClickListener(v -> click.run());
        button.setOnTouchListener((v, event) -> { trackPanelTouch(event); return false; }); return button;
    }
    private Button detailButton(LinearLayout row, String text, Runnable click) {
        Button button = new Button(this); button.setText(text); button.setTextSize(12); button.setMinWidth(0); button.setMinimumWidth(0); button.setPadding(0, 0, 0, 0);
        button.setSingleLine(); button.setMinHeight(dp(48)); button.setMinimumHeight(dp(48)); button.setAllCaps(false);
        row.addView(button, new LinearLayout.LayoutParams(0, -2, 1)); button.setOnClickListener(v -> click.run()); return button;
    }
    private void openDetail() {
        if (destroyed || transport == null || transport.active() || !canCollapse()) return;
        if (detailPanel == null) createDetailPanel();
        if (detailPanel == null) return;
        if (panel != null) panel.setVisibility(View.GONE);
        detailVisible = true; compactPanel = false; detailPanel.setVisibility(View.VISIBLE); refreshSongList(); render();
    }
    private void hideDetail(boolean restorePanel) {
        detailVisible = false;
        if (detailPanel != null) detailPanel.setVisibility(View.GONE);
        if (restorePanel && panel != null) { panel.setVisibility(View.VISIBLE); compactPanel = true; }
    }
    private void createDetailPanel() {
        detailPanel = new LinearLayout(this); detailPanel.setOrientation(LinearLayout.VERTICAL); detailPanel.setPadding(dp(10), dp(8), dp(10), dp(8));
        GradientDrawable bg = new GradientDrawable(); bg.setColor(Color.rgb(20, 39, 41)); bg.setCornerRadius(dp(18)); bg.setStroke(dp(1), Color.rgb(76, 129, 114)); detailPanel.setBackground(bg);
        detailHeader = new LinearLayout(this); detailHeader.setOrientation(LinearLayout.VERTICAL); detailHeader.setGravity(Gravity.CENTER_VERTICAL); detailHeader.setMinimumHeight(dp(54)); detailPanel.addView(detailHeader);
        title = new TextView(this); title.setText("歌曲列表"); title.setTextSize(16); title.setTextColor(0xff66e3ac); title.setSingleLine(); title.setEllipsize(TextUtils.TruncateAt.END); detailHeader.addView(title);
        detailStatus = new TextView(this); detailStatus.setTextSize(11); detailStatus.setTextColor(Color.WHITE); detailStatus.setSingleLine(); detailStatus.setEllipsize(TextUtils.TruncateAt.END); detailHeader.addView(detailStatus);
        detailHeader.setContentDescription("拖动移动歌曲列表悬浮窗");
        progress = new android.widget.SeekBar(this); progress.setMax(1000); progress.setContentDescription("演奏进度，拖动后暂停并定位"); detailPanel.addView(progress);
        progress.setOnSeekBarChangeListener(new android.widget.SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(android.widget.SeekBar view, int value, boolean user) { }
            @Override public void onStartTrackingTouch(android.widget.SeekBar view) { seeking = true; pause("正在定位，继续前请将半音设为未选中"); }
            @Override public void onStopTrackingTouch(android.widget.SeekBar view) { if (transport != null) seek(Math.round(view.getProgress() / 1000.0 * transport.duration)); seeking = false; render(); }
        });
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true); scroll.setVerticalScrollBarEnabled(true);
        songList = new LinearLayout(this); songList.setOrientation(LinearLayout.VERTICAL); scroll.addView(songList, new ScrollView.LayoutParams(-1, -2));
        detailPanel.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        detailControls = new LinearLayout(this); detailPanel.addView(detailControls);
        detailPlay = detailButton(detailControls, "播放", this::toggle);
        calibrate = detailButton(detailControls, "校准", this::startCalibration);
        collapse = detailButton(detailControls, "收起", () -> { if (canCollapse()) hideDetail(true); });
        detailParams = new WindowManager.LayoutParams(detailWidth(), detailHeight(), WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE, PixelFormat.TRANSLUCENT);
        detailParams.gravity = Gravity.TOP | Gravity.LEFT; detailParams.x = dp(8); detailParams.y = dp(24);
        detailHeader.setOnTouchListener(new View.OnTouchListener() {
            float x, y; int startX, startY;
            @Override public boolean onTouch(View view, MotionEvent event) {
                if (event.getActionMasked() == MotionEvent.ACTION_DOWN) {
                    x = event.getRawX(); y = event.getRawY(); startX = detailParams.x; startY = detailParams.y; return true;
                }
                if (event.getActionMasked() == MotionEvent.ACTION_MOVE) {
                    detailParams.x = startX + Math.round(event.getRawX() - x); detailParams.y = startY + Math.round(event.getRawY() - y);
                    constrainDetail(); windows.updateViewLayout(detailPanel, detailParams); return true;
                }
                return true;
            }
        });
        detailPanel.addOnLayoutChangeListener((v, l, t, r, b, oldL, oldT, oldR, oldB) -> {
            if (detailPanel != null && constrainDetail()) windows.updateViewLayout(detailPanel, detailParams);
        });
        try { windows.addView(detailPanel, detailParams); detailPanel.setVisibility(View.GONE); }
        catch (RuntimeException e) { detailPanel = null; notifyUser("曲库悬浮窗创建失败：" + ErrorMessages.userMessage(e, "请检查悬浮窗权限")); }
    }
    private int detailWidth() {
        Point space = panelSpace(); int available = Math.max(dp(1), space.x - dp(16));
        int preferred = Math.round(Math.min(space.x, space.y) * .84f);
        return Math.min(available, Math.max(dp(240), preferred));
    }
    private int detailHeight() {
        Point space = panelSpace(); int available = Math.max(dp(160), space.y - dp(24));
        return Math.min(available, Math.max(dp(340), Math.round(space.y * .72f)));
    }
    private boolean constrainDetail() {
        if (detailPanel == null || detailParams == null) return false;
        Point space = panelSpace(); int x = detailParams.x, y = detailParams.y;
        detailParams.x = Math.max(0, Math.min(Math.max(0, space.x - detailPanel.getWidth()), x));
        detailParams.y = Math.max(0, Math.min(Math.max(0, space.y - detailPanel.getHeight()), y));
        return x != detailParams.x || y != detailParams.y;
    }
    private void refreshSongList() {
        if (songList == null) return;
        songList.removeAllViews();
        try {
            for (Library.Entry entry : new Library(this).entries()) {
                boolean selected = entry.id.equals(selectedSongId);
                Button item = new Button(this); item.setText((selected ? "✓  " : "　　") + entry.title); item.setTextSize(13); item.setAllCaps(false);
                item.setGravity(Gravity.CENTER_VERTICAL | Gravity.LEFT); item.setPadding(dp(10), 0, dp(10), 0); item.setMinHeight(dp(48)); item.setMinimumHeight(dp(48));
                item.setTextColor(selected ? 0xff102829 : Color.WHITE);
                GradientDrawable background = new GradientDrawable(); background.setColor(selected ? 0xff66e3ac : 0xff263c3e); background.setCornerRadius(dp(10)); item.setBackground(background);
                LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-1, dp(48)); layout.bottomMargin = dp(5); songList.addView(item, layout);
                item.setOnClickListener(v -> selectSong(entry));
            }
        } catch (RuntimeException e) { notifyUser("曲库读取失败：" + ErrorMessages.userMessage(e, "请检查曲谱后重试")); }
    }
    private void selectSong(Library.Entry entry) {
        if (transport != null && (transport.active() || !canCollapse())) return;
        try {
            Score stored = new Library(this).read(entry.id);
            selectedSongId = entry.id; settings.selected(entry.id); load(settings.prepare(stored, new Library(this).kind(entry.id).equals("MIDI"))); refreshSongList();
        } catch (Exception e) { notifyUser("曲谱读取失败：" + ErrorMessages.userMessage(e, "请检查曲谱后重试")); }
    }
    private void trackPanelTouch(MotionEvent event) {
        if (event.getActionMasked() == MotionEvent.ACTION_DOWN) panelTouching = true;
        if (event.getActionMasked() == MotionEvent.ACTION_UP || event.getActionMasked() == MotionEvent.ACTION_CANCEL) {
            panelTouching = false; handler.post(this::render);
        }
    }
    private Point panelSpace() { Point point = new Point(); windows.getDefaultDisplay().getSize(point); return point; }
    private int panelButtonWidth() { return Math.max(dp(48), (int) Math.ceil(play.getPaint().measureText("暂停")) + dp(16)); }
    private int compactButtonCount() { return transport != null && transport.active() ? 1 : 2; }
    private int panelWidth() {
        Point space = panelSpace();
        int preferred = Math.round(Math.min(space.x, space.y) * .30f);
        String displayed = status.getText().toString();
        if (displayed.isEmpty()) displayed = "00:00";
        int textWidth = (int) Math.ceil(status.getPaint().measureText(displayed)) + dp(12);
        int required = textWidth + compactButtonCount() * panelButtonWidth() + panel.getPaddingLeft() + panel.getPaddingRight();
        return Math.min(Math.max(preferred, required), Math.max(1, space.x - dp(8)));
    }
    private boolean constrainPanel() {
        Point space = panelSpace(); int x = panelParams.x, y = panelParams.y;
        panelParams.x = Math.max(0, Math.min(Math.max(0, space.x - panel.getWidth()), x));
        panelParams.y = Math.max(0, Math.min(Math.max(0, space.y - panel.getHeight()), y));
        return x != panelParams.x || y != panelParams.y;
    }
    private void layoutPanel() {
        compactPanel = panel != null && panel.getVisibility() == View.VISIBLE;
        panel.setOrientation(LinearLayout.HORIZONTAL);
        panelHeader.setLayoutParams(new LinearLayout.LayoutParams(0, -2, 1));
        controls.setLayoutParams(new LinearLayout.LayoutParams(compactButtonCount() * panelButtonWidth(), -2));
        expand.setVisibility(transport != null && transport.active() ? View.GONE : View.VISIBLE);
        status.setMaxLines(1);
        int width = panelWidth();
        if (panelParams.width != width) { panelParams.width = width; windows.updateViewLayout(panel, panelParams); }
    }
    public void hidePanel() {
        if (awaitingHalf) pause("已取消播放准备");
        dismissHalfPrompt();
        closeCalibration();
        if (panel != null) { windows.removeView(panel); panel = null; title = null; status = null; play = null; collapse = null; calibrate = null; panelHeader = null; controls = null; }
        if (detailPanel != null) { windows.removeView(detailPanel); detailPanel = null; detailHeader = null; detailStatus = null; detailPlay = null; detailControls = null; songList = null; }
        progress = null; seeking = false; detailParams = null; detailVisible = false; compactPanel = false; expand = null; panelTouching = false;
    }
    private boolean canCollapse() {
        // 实际手指触碰可能先取消演奏手势；该次触碰仍不能把刚暂停的悬浮窗收起。
        return (transport == null || !transport.active()) && !inFlight && held == null && SystemClock.uptimeMillis() - cancelledAt >= 400;
    }
    private void render() {
        if (panel != null && status != null && panel.getVisibility() == View.VISIBLE && !detailVisible && calibration == null) {
            long now = SystemClock.uptimeMillis();
            String progress = transport == null || score == null ? "00:00" : time(transport.position(now));
            String value = awaitingHalf ? "半音设为未选中" : progress;
            if (!value.contentEquals(status.getText())) status.setText(value);
            String label = transport != null && transport.active() ? "暂停" : "播放";
            if (!label.contentEquals(play.getText())) play.setText(label);
            layoutPanel();
        }
        renderDetail();
    }
    private void renderDetail() {
        if (detailPanel == null || detailStatus == null) return;
        boolean enabled = canCollapse();
        if (detailPlay != null) {
            String label = transport != null && transport.active() ? "暂停" : "播放";
            if (!label.contentEquals(detailPlay.getText())) detailPlay.setText(label);
        }
        if (calibrate != null) { calibrate.setEnabled(enabled); calibrate.setAlpha(enabled ? 1f : .35f); }
        if (collapse != null) { collapse.setEnabled(enabled); collapse.setAlpha(enabled ? 1f : .35f); }
        if (score != null && transport != null) {
            if (progress != null && !seeking) progress.setProgress((int) (transport.position(SystemClock.uptimeMillis()) * 1000 / Math.max(1, score.duration)));
            String value = "当前：" + score.title + "  " + time(transport.position(SystemClock.uptimeMillis())) + " / " + time(score.duration);
            if (!value.contentEquals(detailStatus.getText())) detailStatus.setText(value);
        }
    }
    static String time(long ms) { return String.format(Locale.ROOT, "%02d:%02d", ms / 60000, ms / 1000 % 60); }
    private void notifyUser(String text) { message = text; Toast.makeText(this, text, Toast.LENGTH_LONG).show(); render(); }
    public void toggle() {
        if (transport == null || calibration != null) return;
        if (transport.active()) { pause("已暂停"); return; }
        // 手指点悬浮按钮时系统会先取消演奏手势，避免该次抬手又触发继续。
        if (transport.state == Transport.State.PAUSED && SystemClock.uptimeMillis() - cancelledAt < 400) return;
        if (inFlight || held != null) { notifyUser("正在释放触摸，请稍后重试"); return; }
        // 详情窗点击播放先切换为紧凑条，再检查校准点是否被播放条遮挡。
        showPanel();
        if (!validateStart()) return;
        awaitingHalf = true; tones.invalidate();
        // 播放和续播都给用户三秒关闭半音，提示期间不预选变音或发送音键。
        transport.play(SystemClock.uptimeMillis(), 3000);
        handler.postDelayed(halfPromptTask, 3000); render();
    }
    private boolean validateStart() {
        if (!ready()) { notifyUser("请进入目标窗口并完成 12 点校准；升级或旋转屏幕后需重新校准"); return false; }
        try {
            fastSwitch = settings.fastSwitch();
            fingerings = new Score.Fingering[score.notes.size()];
            for (int i = 0; i < fingerings.length; i++) fingerings[i] = settings.fingering(score.notes.get(i).pitch);
            releaseTimes = new long[fingerings.length];
            for (int i = 0; i < releaseTimes.length; i++) {
                boolean last = i + 1 == releaseTimes.length;
                releaseTimes[i] = ToneTiming.releaseAt(score.notes.get(i), last ? null : score.notes.get(i + 1),
                    fingerings[i], last ? null : fingerings[i + 1], transport.speed, fastSwitch);
            }
            for (int point : Score.CALIBRATION_ORDER) {
                PointF p = settings.point(point);
                if (p == null) throw new IllegalArgumentException("请重新校准「" + Score.LABELS[point] + "」");
                if (covers(p)) throw new IllegalArgumentException("悬浮窗挡住了「" + Score.LABELS[point] + "」，请拖到空白区域");
            }
        } catch (IllegalArgumentException e) { notifyUser(ErrorMessages.userMessage(e, "校准设置无效")); return false; }
        return true;
    }
    private void dismissHalfPrompt() {
        awaitingHalf = false; handler.removeCallbacks(halfPromptTask);
    }
    private void finishHalfPrompt() {
        if (!awaitingHalf || destroyed) return;
        dismissHalfPrompt();
        if (transport == null || !transport.active()) return;
        if (!validateStart()) { pause(message); return; }
        tones.confirmHalf(false); message = "正在演奏"; render(); schedule(0);
    }
    private boolean covers(PointF p) {
        if (panel == null || panel.getVisibility() != View.VISIBLE) return false;
        int[] location = new int[2]; panel.getLocationOnScreen(location);
        return p.x >= location[0] && p.x < location[0] + panel.getWidth() && p.y >= location[1] && p.y < location[1] + panel.getHeight();
    }
    public void seek(long position) {
        pause("已定位，继续前请将半音设为未选中");
        if (transport != null) transport.seek(position);
        tones.invalidate(); render();
    }
    public void pause(String reason) {
        dismissHalfPrompt(); tones.invalidate();
        if (transport != null) transport.pause(SystemClock.uptimeMillis());
        message = reason; handler.removeCallbacks(pumpTask);
        if (!inFlight) release(); render();
    }
    public void stop() {
        dismissHalfPrompt(); tones.invalidate();
        if (transport != null) transport.stop();
        message = "已停止，回到曲首"; handler.removeCallbacks(pumpTask);
        if (!inFlight) release(); render();
    }
    private void schedule(long delay) { handler.removeCallbacks(pumpTask); if (!destroyed) handler.postDelayed(pumpTask, delay); }
    private void pump() {
        if (destroyed || inFlight || transport == null || awaitingHalf) return;
        if (!transport.active()) { release(); return; }
        if (!ready()) { pause("已切出目标窗口，保留进度"); return; }
        long now = SystemClock.uptimeMillis(); transport.update(now);
        if (!transport.active()) { message = "演奏结束"; release(); render(); return; }
        long position = transport.position(now);
        int index = findUpcomingNote(position);
        if (held != null && heldIndex != index) { release(); return; }
        if (index < 0) { schedule(15); return; }
        Score.Note n = score.notes.get(index);
        Score.Fingering fingering = fingerings[index];
        if (!tones.known()) { pause("变音状态不明，请先将半音设为未选中后继续"); return; }
        int selector = tones.next(fingering);
        if (selector >= 0) {
            // 必须先抬起音键，再依次点击音区和半音；这些按钮不能与音键一起长按。
            if (held != null) { release(); return; }
            int[] selectors = tones.steps(fingering);
            GestureDescription.StrokeDescription[] taps = selectorTaps(selectors, 0);
            if (taps != null) dispatchToneBatch(taps, selectors, now, n.start);
            return;
        }
        transport.resumeClock(now);
        // 倒计时和休止时只预选变音，必须到谱面时刻才按下音键。
        if (transport.state == Transport.State.COUNTDOWN) { schedule(20); return; }
        if (position < n.start) { schedule(Math.min(15, Math.max(1, (long) Math.ceil((n.start - position) / transport.speed)))); return; }
        long end = releaseTimes[index], remaining = Math.max(1, (long) Math.ceil((end - position) / transport.speed));
        long slice = Math.min(60, remaining); boolean more = remaining > slice;
        int[] nextSelectors = !more && index + 1 < fingerings.length ? tones.steps(fingerings[index + 1]) : new int[0];
        // 在最后一段音键手势里排入松键后的变音，省去松键回调到下一次派发的往返。
        GestureDescription.StrokeDescription[] nextTaps = selectorTaps(nextSelectors, slice + ToneTiming.RELEASE_GAP_MS);
        if (nextTaps == null) return;
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
        if (nextSelectors.length == 0) dispatch(held, more);
        else {
            GestureDescription.StrokeDescription[] batch = java.util.Arrays.copyOf(held, held.length + nextTaps.length);
            System.arraycopy(nextTaps, 0, batch, held.length, nextTaps.length);
            dispatchToneBatch(batch, nextSelectors, now, score.notes.get(index + 1).start);
        }
    }
    private GestureDescription.StrokeDescription[] selectorTaps(int[] selectors, long start) {
        GestureDescription.StrokeDescription[] taps = new GestureDescription.StrokeDescription[selectors.length];
        if (selectors.length == 0) return taps;
        long tap = ToneTiming.tapMs(selectors.length, fastSwitch), between = ToneTiming.betweenMs(fastSwitch);
        for (int i = 0; i < selectors.length; i++) {
            PointF p = settings.point(selectors[i]);
            if (p == null || covers(p)) { pause("变音按钮被遮挡或校准已失效"); return null; }
            Path path = new Path(); path.moveTo(p.x, p.y);
            taps[i] = new GestureDescription.StrokeDescription(path,
                start + i * (tap + between), tap);
        }
        return taps;
    }
    private void dispatchToneBatch(GestureDescription.StrokeDescription[] strokes, int[] selectors, long now, long nextStart) {
        transport.limitClock(now, nextStart);
        Transport batch = transport; long generation = batch.generation;
        dispatch(strokes, false, () -> {
            // 此处只提交同一播放批次的状态；下一次 pump 在任何触摸前统一检查前台。
            if (transport == batch && batch.generation == generation && batch.active()) {
                for (int point : selectors) tones.applied(point);
            } else tones.invalidate();
        }, ToneTiming.settleMs(fastSwitch));
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
    private int findUpcomingNote(long position) {
        int low = 0, high = score.notes.size() - 1, found = -1;
        while (low <= high) { int mid = (low + high) >>> 1; if (score.notes.get(mid).start <= position) { found = mid; low = mid + 1; } else high = mid - 1; }
        if (found < 0 || position >= releaseTimes[found]) found++;
        return found < score.notes.size() ? found : -1;
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
                    // 演奏进度由心跳刷新，避免每个短手势都更新布局并触发窗口事件。
                    if (transport == null || !transport.active()) render();
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
        dismissHalfPrompt(); tones.invalidate();
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
        boolean wasDetailVisible = detailVisible; closeCalibration(); restoreDetail = wasDetailVisible; calibration = new Calibration(target);
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(-1, -1, WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN, PixelFormat.TRANSLUCENT);
        if (android.os.Build.VERSION.SDK_INT >= 28) params.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
        if (panel != null) panel.setVisibility(View.GONE);
        if (detailPanel != null) detailPanel.setVisibility(View.GONE);
        windows.addView(calibration, params);
    }
    private void closeCalibration() {
        if (calibration != null) { windows.removeView(calibration); calibration = null; }
        if (restoreDetail && detailPanel != null) {
            detailVisible = true; detailPanel.setVisibility(View.VISIBLE); if (panel != null) panel.setVisibility(View.GONE);
        } else if (panel != null) {
            detailVisible = false; panel.setVisibility(View.VISIBLE);
        }
        restoreDetail = false; render();
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
        // 重建文字以应用最新系统字体和密度，重新按可用屏幕计算尺寸。
        if (panel != null) { hidePanel(); showPanel(); }
    }
    @Override public boolean onUnbind(Intent intent) { shutdown(); return super.onUnbind(intent); }
    @Override public void onDestroy() { shutdown(); super.onDestroy(); }
    private void shutdown() {
        if (destroyed) return;
        destroyed = true; if (transport != null) transport.stop(); handler.removeCallbacksAndMessages(null);
        gestureSerial++; inFlight = false; held = null; heldIndex = -1; tones.invalidate(); hidePanel(); if (instance == this) instance = null;
    }
}
