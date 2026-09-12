package top.aiygzn.melodica;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Point;
import android.graphics.PointF;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.view.MotionEvent;
import android.widget.TextView;
import java.lang.reflect.Field;
import java.util.HashMap;
import java.util.Map;
import java.util.List;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.function.BooleanSupplier;

/** 仅向自建测试键盘发手势；测试结束恢复原来的设置和曲目。 */
public final class GestureSmokeTest extends Instrumentation {
    private TouchTestActivity keyboard;
    private MelodicaService service;
    private Settings settings;
    private Point size;
    private int rotation;
    private PointF[] points;
    private boolean onlineOnly, timingOnly;
    private final StringBuilder report = new StringBuilder();
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); onlineOnly = "online".equals(arguments.getString("suite")); timingOnly = "timing".equals(arguments.getString("suite")); start(); }
    @Override public void onStart() {
        SharedPreferences prefs = getTargetContext().getSharedPreferences("melodica", 0);
        Map<String, ?> previous = new HashMap<>(prefs.getAll());
        Bundle result = new Bundle(); int code = Activity.RESULT_OK;
        try {
            if (onlineOnly) { new OnlineUiChecks(this, report).run(); }
            else {
            android.app.UiAutomation automation = getUiAutomation(android.app.UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
            startActivitySync(new Intent(getTargetContext(), MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            // instrumentation 会重启目标进程，系统将原服务记作崩溃；只重连原本已开启的本服务。
            String enabled = android.provider.Settings.Secure.getString(getTargetContext().getContentResolver(), "enabled_accessibility_services");
            if (enabled != null && enabled.contains("top.aiygzn.melodica/")) {
                if (android.os.Build.VERSION.SDK_INT < 29) throw new AssertionError("此自动化测试入口需 Android 10+；应用本身支持 Android 8+");
                automation.adoptShellPermissionIdentity("android.permission.WRITE_SECURE_SETTINGS");
                try {
                    String others = java.util.Arrays.stream(enabled.split(":"))
                        .filter(s -> !s.startsWith("top.aiygzn.melodica/")).collect(java.util.stream.Collectors.joining(":"));
                    android.provider.Settings.Secure.putString(getTargetContext().getContentResolver(), "enabled_accessibility_services", others);
                    SystemClock.sleep(200);
                } finally {
                    android.provider.Settings.Secure.putString(getTargetContext().getContentResolver(), "enabled_accessibility_services", enabled);
                    automation.dropShellPermissionIdentity();
                }
            }
            await(() -> MelodicaService.instance != null, 8000, "请先在测试设备开启演奏服务");
            service = MelodicaService.instance;
            keyboard = (TouchTestActivity) startActivitySync(new Intent(getTargetContext(), TouchTestActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            SystemClock.sleep(700); waitForIdleSync();
            runOnMainSync(() -> {
                service.stop(); service.hidePanel(); settings = new Settings(keyboard);
                settings.speed(1); settings.base(60); settings.transpose(0);
                size = new Point(); keyboard.getWindowManager().getDefaultDisplay().getRealSize(size);
                rotation = keyboard.getWindowManager().getDefaultDisplay().getRotation(); points = new PointF[Score.LABELS.length];
                for (int i = 0; i < points.length; i++) {
                    View key = find(keyboard.getWindow().getDecorView(), Score.LABELS[i]);
                    if (key == null) throw new AssertionError("未找到测试音键");
                    int[] location = new int[2]; key.getLocationOnScreen(location);
                    points[i] = new PointF(location[0] + key.getWidth() / 2f, location[1] + key.getHeight() / 2f);
                }
                calibrate(keyboard.getPackageName(), rotation);
            });
            if (timingOnly) { measureTiming(); }
            else {
            runOnMainSync(() -> {
                prefs.edit().remove("calibrationVersion").commit();
                service.toggle();
                check(!settings.calibrated() && !transport().active() && !(Boolean) field(service, "awaitingHalf"), "旧校准被误用");
                service.showPanel(); find((View) field(service, "panel"), "校准").performClick();
            });
            SystemClock.sleep(150);
            for (int id : Score.CALIBRATION_ORDER) {
                tap(points[id]);
                if (id == Score.NATURAL) saveScreen("calibration-v02.png");
            }
            await(settings::calibrated, 1000, "12 点校准未保存");
            for (int i = 0; i < points.length; i++) check(settings.point(i).equals(points[i]), "校准位置对应错误");
            check(count("downs") == 0 && list("selectors").isEmpty(), "校准穿透点击了测试键盘");
            pass("旧校准失效与真实点击完成 12 点校准");

            runOnMainSync(() -> { service.toggle(); check((Boolean) field(service, "awaitingHalf"), "没有请求半音状态"); });
            SystemClock.sleep(200);
            check(!transport().active() && list("selectors").isEmpty(), "确认半音前发送了触摸");
            saveScreen("half-confirmation-v02.png");
            runOnMainSync(service::stop); pass("半音未确认时不演奏");
            // 重复音、休止和长音必须产生完整 DOWN / UP，续接不能成为空事件。
            start("1 1:2 0 2");
            await(() -> !list("selectors").isEmpty() && !(Boolean) field(service, "inFlight"), 1000, "倒计时未准备变音");
            runOnMainSync(() -> {
                check(transport().state == Transport.State.COUNTDOWN && count("downs") == 0, "倒计时提前按下音键");
                View collapse = find((View) field(service, "panel"), "收起");
                check(!collapse.isEnabled(), "倒计时中收起未禁用"); collapse.performClick();
                check(field(service, "panel") != null && transport().active(), "收起入口绕过了播放保护");
            });
            await(() -> count("ups") == 3, 7000, "完整演奏没有收到三个抬起事件");
            check(count("downs") == 3 && count("cancels") == 0 && held() == 0, "重复音或长按出现丢失／取消"); pass("重复音、休止、连续长按");
            await(() -> !transport().active() && find((View) field(service, "panel"), "收起").isEnabled(), 500, "播放完成后收起未恢复");
            pass("倒计时预选变音且不发音、禁用收起、播放结束恢复");

            start("1:8 2"); await(() -> held() == 1, 4500, "长音未按下"); SystemClock.sleep(150);
            runOnMainSync(() -> service.pause("测试暂停")); await(() -> held() == 0, 600, "暂停未释放触摸");
            long position = transport().position(SystemClock.uptimeMillis()); int down = count("downs"); SystemClock.sleep(250);
            check(position > 0 && transport().position(SystemClock.uptimeMillis()) == position && count("downs") == down, "暂停位置漂移"); pass("暂停释放与位置保持");
            check(find((View) field(service, "panel"), "收起").isEnabled(), "暂停后收起未恢复");
            runOnMainSync(() -> { service.toggle(); service.confirmHalfState(false); }); await(() -> count("downs") > down, 1000, "续播没有重新按下剩余长音");
            runOnMainSync(service::stop); await(() -> held() == 0, 600, "停止未释放触摸");
            check(transport().position(SystemClock.uptimeMillis()) == 0, "停止未归零"); pass("续播、停止归零与释放");

            start("1:8"); runOnMainSync(service::stop); SystemClock.sleep(3200);
            check(count("downs") == down + 1, "取消倒计时后仍发送了触摸"); pass("倒计时取消");

            int noteStart = list("pitches").size(), selectorStart = list("selectors").size();
            start("-1 -#1 -#2 #1 #2 +#2 +#4 +2 1 1");
            await(() -> !transport().active() && held() == 0, 12000, "组合变音未完成");
            check(list("pitches").subList(noteStart, list("pitches").size()).equals(Arrays.asList(48, 49, 51, 61, 63, 75, 78, 74, 60, 60)), "组合变音音高不符：" + list("pitches"));
            check(list("selectors").subList(selectorStart, list("selectors").size()).equals(Arrays.asList(Score.LOW, Score.HALF, Score.NATURAL, Score.HIGH, Score.HALF, Score.NATURAL)), "重复切换或互斥规则错误：" + list("selectors"));
            check(count("selectorWhileHeld") == 0 && count("cancels") == 0, "变音与音键发生重叠触摸"); pass("三音区与半音组合、重复音不重复切换、先松音键再切换");

            runOnMainSync(() -> find(keyboard.getWindow().getDecorView(), "半音").performClick());
            check((Boolean) field(keyboard, "half"), "测试半音初态没有选中");
            noteStart = list("pitches").size();
            start("1 #1"); await(() -> !transport().active() && held() == 0, 6000, "半音初态选中时未完成");
            check(list("pitches").subList(noteStart, list("pitches").size()).equals(Arrays.asList(60, 61)), "半音初态确认后音高错误"); pass("初始半音已选中时正确开关");

            start("+#2:8");
            await(() -> transport().active() && (Boolean) field(service, "inFlight") && held() == 0, 4500, "未捕获变音点击阶段");
            runOnMainSync(() -> service.pause("变音点击期间暂停"));
            int interruptedNotes = count("downs"); SystemClock.sleep(250);
            check(!transport().active() && count("downs") == interruptedNotes && !((ToneState) field(service, "tones")).known(), "旧变音回调继续发键或恢复过期状态");
            runOnMainSync(() -> { service.toggle(); check((Boolean) field(service, "awaitingHalf"), "中断后未重新确认半音"); service.confirmHalfState((Boolean) field(keyboard, "half")); });
            await(() -> held() == 1, 1000, "变音中断后无法续播");
            check(list("pitches").get(list("pitches").size() - 1) == 75, "变音中断后续播音高错误");
            runOnMainSync(service::stop); await(() -> held() == 0, 600, "变音续播后停止未释放"); pass("变音点击中暂停、旧回调失效及重新同步续播");

            noteStart = list("pitches").size();
            start("1:1/4 +#2:1/4 -#1:1/4 #1:1/4 2:1/4");
            await(() -> !transport().active() && held() == 0, 6500, "短音变音未完成");
            check(list("pitches").subList(noteStart, list("pitches").size()).equals(Arrays.asList(60, 75, 49, 61, 62)), "切换耗时吞掉短音"); pass("密集跨音区半音不丢短音");
            start("1:16"); await(() -> held() == 1, 4500, "收起禁用测试前未按下音键");
            final PointF[] collapsePoint = new PointF[1];
            runOnMainSync(() -> {
                View collapse = find((View) field(service, "panel"), "收起"); check(!collapse.isEnabled(), "演奏中收起未禁用");
                int[] p = new int[2]; collapse.getLocationOnScreen(p); collapsePoint[0] = new PointF(p[0] + collapse.getWidth() / 2f, p[1] + collapse.getHeight() / 2f);
            });
            saveScreen("collapse-disabled-v03.png");
            tap(collapsePoint[0]);
            check(field(service, "panel") != null, "手指点击禁用按钮后悬浮窗消失");
            runOnMainSync(service::stop);
            await(() -> find((View) field(service, "panel"), "收起").isEnabled(), 1000, "停止后收起未恢复");
            runOnMainSync(() -> { find((View) field(service, "panel"), "收起").performClick(); check(field(service, "panel") == null, "停止后无法收起"); service.showPanel(); });
            pass("真实触摸不能收起演奏悬浮窗、停止后可收起");
            runOnMainSync(() -> calibrate("test.invalid.package", rotation)); start("1"); SystemClock.sleep(200);
            check(!transport().active() && held() == 0, "目标应用不匹配仍开始演奏"); pass("目标应用检查");
            runOnMainSync(() -> calibrate(keyboard.getPackageName(), (rotation + 1) % 4)); start("1"); SystemClock.sleep(200);
            check(!transport().active() && held() == 0, "旋转方向不匹配仍开始演奏"); pass("旋转校准检查");
            runOnMainSync(() -> calibrate(keyboard.getPackageName(), rotation));
            start("1:8"); await(() -> held() == 1, 4500, "切出测试前未按下音键");
            runOnMainSync(keyboard::finish);
            await(() -> held() == 0 && !transport().active(), 1000, "离开测试窗口未暂停释放"); pass("切出窗口暂停释放");
            }
            }
        } catch (Throwable error) {
            code = Activity.RESULT_CANCELED; report.append("失败：").append(error).append('\n');
            android.util.Log.e("MelodicaSmoke", "测试失败", error);
        } finally {
            runOnMainSync(() -> {
                if (service != null) service.stop();
                SharedPreferences.Editor edit = prefs.edit().clear();
                for (var entry : previous.entrySet()) {
                    Object v = entry.getValue(); String k = entry.getKey();
                    if (v instanceof String) edit.putString(k, (String) v);
                    else if (v instanceof Integer) edit.putInt(k, (Integer) v);
                    else if (v instanceof Float) edit.putFloat(k, (Float) v);
                    else if (v instanceof Boolean) edit.putBoolean(k, (Boolean) v);
                    else if (v instanceof Long) edit.putLong(k, (Long) v);
                }
                edit.commit();
                if (service != null) {
                    try { Score s = new Library(service).read(new Settings(service).selected()); service.load(s.melody(s.recommendedTrack())); }
                    catch (Exception ignored) { /* 仍保留停止状态。 */ }
                    service.showPanel();
                }
            });
        }
        result.putString("stream", "\n" + report); finish(code, result);
    }
    private void calibrate(String target, int direction) { settings.calibrate(target, size.x, size.y, direction, points); }
    @SuppressWarnings("unchecked")
    private void measureTiming() {
        for (String score : new String[]{"1 +2 1 -2 1 +2 1 -2 1", "1 0 +2 0 -2 0 1", "1 +#2 -#1 #1 2"}) {
            int from = count("downs");
            start(score);
            await(() -> !transport().active() && held() == 0, 12000, "计时演奏未完成");
            runOnMainSync(() -> {
                List<Long> downs = (List<Long>) field(keyboard, "noteDownTimes"), ups = (List<Long>) field(keyboard, "noteUpTimes");
                List<Score.Note> notes = Score.jianpu(score, 120, "计时").notes;
                check(downs.size() - from == notes.size() && count("cancels") == 0 && count("selectorWhileHeld") == 0, "计时测试丢音、取消或叠按");
                for (int i = 0; i < notes.size(); i++) {
                    check(list("pitches").get(from + i) == notes.get(i).pitch, "计时测试音高错误");
                    check(downs.get(from + i) - downs.get(from) >= notes.get(i).start - 20, "预选变音导致音符提前");
                }
                long totalGap = 0, maxGap = 0;
                for (int i = from + 1; i < downs.size(); i++) { long gap = downs.get(i) - ups.get(i - 1); totalGap += gap; maxGap = Math.max(maxGap, gap); }
                long drift = downs.get(downs.size() - 1) - downs.get(from) - notes.get(notes.size() - 1).start;
                report.append("计时：").append(score).append("；累计延迟 ").append(drift).append(" ms；平均空隙 ").append(totalGap / (notes.size() - 1)).append(" ms；最大空隙 ").append(maxGap).append(" ms\n");
                if (score.contains(" 0 ")) check(Math.abs(drift) < 150, "充足休止时切换仍在累积延迟");
            });
        }
        int from = count("downs");
        runOnMainSync(() -> settings.speed(2));
        start("1:1/4 +#2:1/4 -#1:1/4 #1:1/4 2:1/4");
        await(() -> !transport().active() && held() == 0, 6000, "二倍速短音未完成");
        check(list("pitches").subList(from, list("pitches").size()).equals(Arrays.asList(60, 75, 49, 61, 62)), "二倍速切换吞音或错音");
        check(count("cancels") == 0 && count("selectorWhileHeld") == 0, "二倍速切换取消或叠按");
        pass("二倍速密集跨音区半音不丢音");
        pass("实际触摸计时、音符完整及无叠按");
    }
    private void start(String notes) {
        runOnMainSync(service::stop);
        // 键盘收到 UP 时系统完成回调可能仍在队列中；下一首需等待服务确认释放。
        await(() -> !(Boolean) field(service, "inFlight") && field(service, "held") == null, 1000, "切歌前触摸未释放");
        runOnMainSync(() -> { service.load(Score.jianpu(notes, 120, "触摸回归测试")); service.toggle(); service.confirmHalfState((Boolean) field(keyboard, "half")); });
    }
    private void tap(PointF point) {
        long now = SystemClock.uptimeMillis();
        MotionEvent down = MotionEvent.obtain(now, now, MotionEvent.ACTION_DOWN, point.x, point.y, 0);
        MotionEvent up = MotionEvent.obtain(now, now + 50, MotionEvent.ACTION_UP, point.x, point.y, 0);
        try { sendPointerSync(down); sendPointerSync(up); waitForIdleSync(); } finally { down.recycle(); up.recycle(); }
    }
    private void saveScreen(String name) throws java.io.IOException {
        // 仅测试入口保存自建界面截图；应用正常演奏不会截图。
        SystemClock.sleep(4000); // 等待前一步故意触发的校准提示消失，避免挡住截图。
        android.graphics.Bitmap bitmap = getUiAutomation(android.app.UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES).takeScreenshot();
        if (bitmap == null) throw new AssertionError("测试截图失败");
        try (java.io.FileOutputStream output = new java.io.FileOutputStream(new java.io.File(getTargetContext().getExternalFilesDir(null), name))) {
            check(bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, output), "测试截图保存失败");
        } finally { bitmap.recycle(); }
    }
    @SuppressWarnings("unchecked")
    private List<Integer> list(String name) { return new ArrayList<>((List<Integer>) field(keyboard, name)); }
    private void await(BooleanSupplier condition, long timeout, String failure) {
        long end = SystemClock.uptimeMillis() + timeout;
        while (SystemClock.uptimeMillis() < end) { final boolean[] value = {false}; runOnMainSync(() -> value[0] = condition.getAsBoolean()); if (value[0]) return; SystemClock.sleep(30); }
        throw new AssertionError(failure);
    }
    private void check(boolean value, String failure) { if (!value) throw new AssertionError(failure); }
    private void pass(String value) { report.append("通过：").append(value).append('\n'); }
    private Object field(Object object, String name) {
        try { Field field = object.getClass().getDeclaredField(name); field.setAccessible(true); return field.get(object); }
        catch (Exception e) { throw new AssertionError(e); }
    }
    private int count(String name) { return (Integer) field(keyboard, name); }
    private int held() { return ((Map<?, ?>) field(keyboard, "held")).size(); }
    private Transport transport() { return (Transport) field(service, "transport"); }
    private View find(View view, String label) {
        if (view instanceof TextView && ((TextView) view).getText().toString().equals(label)) return view;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup) view).getChildCount(); i++) { View found = find(((ViewGroup) view).getChildAt(i), label); if (found != null) return found; }
        return null;
    }
}
