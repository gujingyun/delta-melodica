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
import android.widget.TextView;
import java.lang.reflect.Field;
import java.util.HashMap;
import java.util.Map;
import java.util.function.BooleanSupplier;

/** 仅向自建测试键盘发手势；测试结束恢复原来的设置和曲目。 */
public final class GestureSmokeTest extends Instrumentation {
    private TouchTestActivity keyboard;
    private MelodicaService service;
    private Settings settings;
    private Point size;
    private int rotation;
    private PointF[] points;
    private final StringBuilder report = new StringBuilder();
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        SharedPreferences prefs = getTargetContext().getSharedPreferences("melodica", 0);
        Map<String, ?> previous = new HashMap<>(prefs.getAll());
        Bundle result = new Bundle(); int code = Activity.RESULT_OK;
        try {
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
                for (int i = 8; i < 11; i++) settings.modifier(i, false);
                size = new Point(); keyboard.getWindowManager().getDefaultDisplay().getRealSize(size);
                rotation = keyboard.getWindowManager().getDefaultDisplay().getRotation(); points = new PointF[11];
                for (int i = 0; i < 8; i++) {
                    View key = find(keyboard.getWindow().getDecorView(), Score.LABELS[i]);
                    if (key == null) throw new AssertionError("未找到测试音键");
                    int[] location = new int[2]; key.getLocationOnScreen(location);
                    points[i] = new PointF(location[0] + key.getWidth() / 2f, location[1] + key.getHeight() / 2f);
                }
                calibrate(keyboard.getPackageName(), rotation);
            });
            // 重复音、休止和长音必须产生完整 DOWN / UP，续接不能成为空事件。
            start("1 1:2 0 2");
            await(() -> count("ups") == 3, 7000, "完整演奏没有收到三个抬起事件");
            check(count("downs") == 3 && count("cancels") == 0 && held() == 0, "重复音或长按出现丢失／取消"); pass("重复音、休止、连续长按");

            start("1:8 2"); await(() -> held() == 1, 4500, "长音未按下"); SystemClock.sleep(150);
            runOnMainSync(() -> service.pause("测试暂停")); await(() -> held() == 0, 600, "暂停未释放触摸");
            long position = transport().position(SystemClock.uptimeMillis()); int down = count("downs"); SystemClock.sleep(250);
            check(position > 0 && transport().position(SystemClock.uptimeMillis()) == position && count("downs") == down, "暂停位置漂移"); pass("暂停释放与位置保持");
            runOnMainSync(service::toggle); await(() -> count("downs") > down, 1000, "续播没有重新按下剩余长音");
            runOnMainSync(service::stop); await(() -> held() == 0, 600, "停止未释放触摸");
            check(transport().position(SystemClock.uptimeMillis()) == 0, "停止未归零"); pass("续播、停止归零与释放");

            start("1:8"); runOnMainSync(service::stop); SystemClock.sleep(3200);
            check(count("downs") == down + 1, "取消倒计时后仍发送了触摸"); pass("倒计时取消");
            runOnMainSync(() -> calibrate("test.invalid.package", rotation)); start("1"); SystemClock.sleep(200);
            check(!transport().active() && held() == 0, "目标应用不匹配仍开始演奏"); pass("目标应用检查");
            runOnMainSync(() -> calibrate(keyboard.getPackageName(), (rotation + 1) % 4)); start("1"); SystemClock.sleep(200);
            check(!transport().active() && held() == 0, "旋转方向不匹配仍开始演奏"); pass("旋转校准检查");
            runOnMainSync(() -> calibrate(keyboard.getPackageName(), rotation));
            start("1:8"); await(() -> held() == 1, 4500, "切出测试前未按下音键");
            runOnMainSync(keyboard::finish);
            await(() -> held() == 0 && !transport().active(), 1000, "离开测试窗口未暂停释放"); pass("切出窗口暂停释放");
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
    private void start(String notes) { runOnMainSync(() -> { service.load(Score.jianpu(notes, 120, "触摸回归测试")); service.toggle(); }); }
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
