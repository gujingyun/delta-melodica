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
    private boolean onlineOnly, timingOnly, permissionsOnly, overlayOnly;
    private final StringBuilder report = new StringBuilder();
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); onlineOnly = "online".equals(arguments.getString("suite")); timingOnly = "timing".equals(arguments.getString("suite")); permissionsOnly = "permissions".equals(arguments.getString("suite")); overlayOnly = "overlay".equals(arguments.getString("suite")); start(); }
    @Override public void onStart() {
        SharedPreferences prefs = getTargetContext().getSharedPreferences("melodica", 0);
        Map<String, ?> previous = new HashMap<>(prefs.getAll());
        Bundle result = new Bundle(); int code = Activity.RESULT_OK;
        try {
            if (onlineOnly) { new OnlineUiChecks(this, report).run(); }
            else {
            android.app.UiAutomation automation = getUiAutomation(android.app.UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
            MainActivity main = (MainActivity) startActivitySync(new Intent(getTargetContext(), MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
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
            if (permissionsOnly) { permissionChecks(main, automation); }
            else {
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
            else if (overlayOnly) { overlayChecks(); }
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

            SystemClock.sleep(4000); // 等校准成功提示消失，再拍摄控制条内的准备文字。
            runOnMainSync(() -> { service.toggle(); checkHalfPrompt(); });
            SystemClock.sleep(200);
            check(transport().state == Transport.State.COUNTDOWN && count("downs") == 0 && list("selectors").isEmpty(), "提示期间发送了触摸");
            saveScreen("half-toast-v063.png", 0);
            runOnMainSync(service::stop); SystemClock.sleep(3200);
            check(!transport().active() && count("downs") == 0 && list("selectors").isEmpty() && !(Boolean) field(service, "awaitingHalf"), "停止后提示或延迟演奏未取消");
            pass("纯文字提示期间不发键、停止后取消提示与延迟演奏");
            // 重复音、休止和长音必须产生完整 DOWN / UP，续接不能成为空事件。
            start("1 1:2 0 2");
            SystemClock.sleep(200);
            runOnMainSync(() -> {
                check(transport().state == Transport.State.COUNTDOWN && count("downs") == 0, "倒计时提前按下音键");
                check(list("selectors").isEmpty(), "提示结束前切换了变音按钮");
                View collapse = find((View) field(service, "panel"), "收起");
                check(!collapse.isEnabled() && collapse.getVisibility() == View.GONE, "倒计时中收起未隐藏并禁用"); collapse.performClick();
                check(field(service, "panel") != null && transport().active(), "收起入口绕过了播放保护");
            });
            await(() -> count("ups") == 3, 7000, "完整演奏没有收到三个抬起事件");
            check(count("downs") == 3 && count("cancels") == 0 && held() == 0, "重复音或长按出现丢失／取消"); pass("重复音、休止、连续长按");
            await(() -> !transport().active() && find((View) field(service, "panel"), "收起").isEnabled(), 500, "播放完成后收起未恢复");
            pass("准备期间不预选变音且不发音、禁用收起、播放结束恢复");

            start("1:8 2"); await(() -> held() == 1, 4500, "长音未按下"); SystemClock.sleep(150);
            runOnMainSync(() -> service.pause("测试暂停")); await(() -> held() == 0, 600, "暂停未释放触摸");
            long position = transport().position(SystemClock.uptimeMillis()); int down = count("downs"); SystemClock.sleep(250);
            check(position > 0 && transport().position(SystemClock.uptimeMillis()) == position && count("downs") == down, "暂停位置漂移"); pass("暂停释放与位置保持");
            check(find((View) field(service, "panel"), "收起").isEnabled(), "暂停后收起未恢复");
            runOnMainSync(() -> { service.toggle(); checkHalfPrompt(); prepareHalfOff(); }); await(() -> count("downs") > down, 4500, "提示结束后续播没有重新按下剩余长音");
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
            runOnMainSync(() -> { service.load(Score.jianpu("1 #1", 120, "半音关闭提示测试")); service.toggle(); checkHalfPrompt(); });
            SystemClock.sleep(200);
            check(transport().state == Transport.State.COUNTDOWN && (Boolean) field(keyboard, "half") && list("pitches").size() == noteStart, "提示期间自动切换半音或演奏");
            tap(points[Score.HALF]); check(!(Boolean) field(keyboard, "half"), "按提示手动关闭半音失败");
            int expectedPitches = noteStart + 2;
            await(() -> !transport().active() && held() == 0 && list("pitches").size() == expectedPitches, 6000, "关闭半音后未完成演奏");
            check(list("pitches").subList(noteStart, list("pitches").size()).equals(Arrays.asList(60, 61)), "按提示关闭半音后音高错误"); pass("手动关闭半音后自动演奏、自然音与半音正确");

            start("+#2:8");
            await(() -> transport().active() && (Boolean) field(service, "inFlight") && held() == 0, 4500, "未捕获变音点击阶段");
            runOnMainSync(() -> service.pause("变音点击期间暂停"));
            int interruptedNotes = count("downs"); SystemClock.sleep(250);
            check(!transport().active() && count("downs") == interruptedNotes && !((ToneState) field(service, "tones")).known(), "旧变音回调继续发键或恢复过期状态");
            runOnMainSync(() -> { service.toggle(); checkHalfPrompt(); prepareHalfOff(); });
            await(() -> held() == 1, 4500, "变音中断后无法续播");
            check(list("pitches").get(list("pitches").size() - 1) == 75, "变音中断后续播音高错误");
            runOnMainSync(service::stop); await(() -> held() == 0, 600, "变音续播后停止未释放"); pass("变音点击中暂停、旧回调失效及重新同步续播");

            noteStart = list("pitches").size();
            start("1:1/4 +#2:1/4 -#1:1/4 #1:1/4 2:1/4");
            await(() -> !transport().active() && held() == 0, 6500, "短音变音未完成");
            check(list("pitches").subList(noteStart, list("pitches").size()).equals(Arrays.asList(60, 75, 49, 61, 62)), "切换耗时吞掉短音"); pass("密集跨音区半音不丢短音");
            start("1:16"); await(() -> held() == 1, 4500, "收起禁用测试前未按下音键");
            runOnMainSync(() -> {
                View collapse = find((View) field(service, "panel"), "收起"); check(!collapse.isEnabled() && collapse.getVisibility() == View.GONE, "演奏中收起未隐藏并禁用");
                collapse.performClick(); check(transport().active(), "隐藏按钮绕过播放保护");
            });
            saveScreen("overlay-playing.png");
            tap(panelCenter("停止"));
            await(() -> transport().state == Transport.State.READY && held() == 0, 1000, "真实点击紧凑条停止失败");
            check(field(service, "panel") != null && transport().position(SystemClock.uptimeMillis()) == 0, "停止后窗口丢失或进度未归零");
            await(() -> find((View) field(service, "panel"), "收起").isEnabled(), 1000, "停止后收起未恢复");
            runOnMainSync(() -> { find((View) field(service, "panel"), "收起").performClick(); check(field(service, "panel") == null, "停止后无法收起"); service.showPanel(); });
            pass("演奏中隐藏收起、真实触摸停止归零、停止后可收起");
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
    private void permissionChecks(MainActivity main, android.app.UiAutomation automation) throws Exception {
        String key = android.provider.Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES;
        String before = android.provider.Settings.Secure.getString(getTargetContext().getContentResolver(), key);
        ActivityMonitor settingsMonitor = addMonitor(new android.content.IntentFilter(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS), new ActivityResult(Activity.RESULT_CANCELED, null), true);
        MainActivity[] page = {main};
        try {
            runOnMainSync(() -> {
                check(page[0].serviceEnabled(), "已开启的授权未识别");
                service.showPanel(); find(page[0].getWindow().getDecorView(), "停止并隐藏悬浮窗").performClick();
                check(field(service, "panel") == null && !transport().active() && transport().position(SystemClock.uptimeMillis()) == 0, "日常退出没有停止归零并隐藏");
                check(MelodicaService.instance == service && page[0].serviceEnabled(), "日常退出关闭了授权");
            });
            check(before.equals(android.provider.Settings.Secure.getString(getTargetContext().getContentResolver(), key)), "系统服务开关被改变");
            pass("停止并隐藏保留系统无障碍开关，停止归零且服务仍连接");
            SystemClock.sleep(6000); // 等待前一步的系统 Toast 消失，避免遮挡权限截图。
            saveScreen("permissions-connected-v05.png");

            runOnMainSync(() -> find(page[0].getWindow().getDecorView(), "显示悬浮控制条").performClick());
            check(field(service, "panel") != null && settingsMonitor.getHits() == 0, "再次显示悬浮窗仍要求授权");
            runOnMainSync(() -> { service.hidePanel(); page[0].finish(); });
            await(page[0]::isDestroyed, 2000, "主界面未退出");
            // 显式 ACTION_MAIN，避免系统设置的 IntentFilter 也匹配没有 action 的启动 Intent。
            page[0] = (MainActivity) startActivitySync(new Intent(Intent.ACTION_MAIN).setClass(getTargetContext(), MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            runOnMainSync(() -> check(page[0].serviceEnabled() && MelodicaService.instance == service && find(page[0].getWindow().getDecorView(), "管理无障碍授权") != null, "重开应用没有保留授权"));
            check(settingsMonitor.getHits() == 0, "重开应用重复跳转授权");
            pass("恢复悬浮窗与退出后重开应用均不重复申请授权");

            // 仅测试界面状态：已授权但系统尚未连接时不能显示为未授权。
            runOnMainSync(() -> MelodicaService.instance = null);
            try {
                await(() -> ((TextView) field(page[0], "serviceStatus")).getText().toString().contains("已授权，等待系统连接"), 1500, "已授权的连接等待被误报为未开启");
                runOnMainSync(() -> find(page[0].getWindow().getDecorView(), "显示悬浮控制条").performClick());
                check(settingsMonitor.getHits() == 0, "连接等待时重复跳转授权");
            } finally { runOnMainSync(() -> MelodicaService.instance = service); }
            pass("已授权但未连接时显示等待状态，不重复申请");
            runOnMainSync(() -> find(page[0].getWindow().getDecorView(), "管理无障碍授权").performClick());
            check(settingsMonitor.getHits() == 1, "管理授权没有进入系统设置入口");
            pass("管理授权直接使用系统设置入口");

            // 测试主动撤销后的首次申请路径；仅测试包有恢复专用设备设置的能力。
            runOnMainSync(service::disableSelf);
            await(() -> MelodicaService.instance == null && !page[0].serviceEnabled() && find(page[0].getWindow().getDecorView(), "开启无障碍服务") != null, 3000, "关闭后授权状态未刷新");
            SystemClock.sleep(6000);
            saveScreen("permissions-needed-v05.png");
            runOnMainSync(() -> find(page[0].getWindow().getDecorView(), "显示悬浮控制条").performClick());
            SystemClock.sleep(300);
            android.view.accessibility.AccessibilityNodeInfo root = automation.getRootInActiveWindow();
            check(root != null, "权限说明弹窗不可见");
            try {
                List<android.view.accessibility.AccessibilityNodeInfo> buttons = root.findAccessibilityNodeInfosByText("前往系统设置");
                check(!buttons.isEmpty(), "缺少权限说明及申请入口");
                try { check(buttons.get(0).performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK), "权限说明按钮无法点击"); }
                finally { for (var button : buttons) button.recycle(); }
            } finally { root.recycle(); }
            await(() -> settingsMonitor.getHits() == 2, 1500, "未授权时没有按需进入设置");
            check(!page[0].serviceEnabled(), "应用擅自开启了系统开关");
            pass("未授权时按需说明并跳转，确认系统授权仍由用户完成");
        } finally {
            removeMonitor(settingsMonitor);
            automation.adoptShellPermissionIdentity("android.permission.WRITE_SECURE_SETTINGS");
            try { android.provider.Settings.Secure.putString(getTargetContext().getContentResolver(), key, before); }
            finally { automation.dropShellPermissionIdentity(); }
            await(() -> MelodicaService.instance != null, 8000, "测试结束未恢复服务");
            service = MelodicaService.instance;
        }
    }
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
    private void overlayChecks() throws java.io.IOException {
        runOnMainSync(() -> { service.load(Score.jianpu("1:32 2", 120, "悬浮布局测试")); service.showPanel(); });
        waitForIdleSync();
        final int[] expanded = new int[2];
        runOnMainSync(() -> {
            checkPanelBounds(); checkPanelButtons("播放", "停止", "校准", "收起");
            View panel = (View) field(service, "panel"); expanded[0] = panel.getWidth(); expanded[1] = panel.getHeight();
            report.append("尺寸：屏幕 ").append(size.x).append('×').append(size.y).append("，密度 ").append(getTargetContext().getResources().getDisplayMetrics().density)
                .append("，字体 ").append(getTargetContext().getResources().getConfiguration().fontScale).append("，普通 ").append(expanded[0]).append('×').append(expanded[1]).append('\n');
        });
        saveScreen("overlay-expanded.png");
        runOnMainSync(() -> { service.toggle(); service.hidePanel(); });
        waitForIdleSync(); SystemClock.sleep(3200);
        check(!transport().active() && count("downs") == 0 && list("selectors").isEmpty() && !(Boolean) field(service, "awaitingHalf"), "隐藏悬浮窗后仍执行了延迟演奏");
        runOnMainSync(() -> { service.stop(); service.showPanel(); }); waitForIdleSync();
        tap(panelCenter("播放")); SystemClock.sleep(200); waitForIdleSync();
        runOnMainSync(() -> {
            checkHalfPrompt(); checkPanelBounds(); checkPanelButtons("暂停", "停止");
        });
        saveScreen("overlay-half-toast.png", 0);
        runOnMainSync(() -> {
            check(transport().state == Transport.State.COUNTDOWN, "未进入倒计时");
            View panel = (View) field(service, "panel");
            check((Boolean) field(service, "compactPanel") && !find(panel, "校准").isShown() && !find(panel, "收起").isShown(), "倒计时没有隐藏辅助操作");
            checkPanelBounds(); checkPanelButtons("暂停", "停止");
            check(panel.getHeight() < expanded[1] && panel.getWidth() * panel.getHeight() < expanded[0] * expanded[1], "播放时未减小遮挡面积");
            TextView status = (TextView) field(service, "status");
            check(status.getLineCount() == 1 && status.getLayout().getEllipsisCount(0) == 0, "紧凑进度显示不完整");
            report.append("尺寸：播放 ").append(panel.getWidth()).append('×').append(panel.getHeight()).append('\n');
        });
        await(() -> transport().state == Transport.State.PLAYING && !(Boolean) field(service, "awaitingHalf"), 4500, "提示未自动隐藏或未自动开始演奏");
        runOnMainSync(() -> check(!"半音设为未选中".contentEquals(((TextView) field(service, "status")).getText()), "开始后提示文字未隐藏"));
        saveScreen("overlay-playing.png");
        await(() -> held() == 1, 1000, "布局切换后未演奏");
        tap(panelCenter("暂停"));
        await(() -> transport().state == Transport.State.PAUSED && held() == 0 && !(Boolean) field(service, "compactPanel"), 1500, "真实暂停后未释放并展开");
        runOnMainSync(() -> { checkPanelBounds(); checkPanelButtons("继续", "停止", "校准", "收起"); });
        saveScreen("overlay-paused.png");
        pass("自适应尺寸、无按钮提示自动隐藏并演奏、真实暂停恢复操作");

        runOnMainSync(() -> { service.toggle(); checkHalfPrompt(); prepareHalfOff(); });
        await(() -> held() == 1, 4500, "继续提示结束后未演奏");
        tap(panelCenter("停止"));
        await(() -> transport().state == Transport.State.READY && held() == 0 && !(Boolean) field(service, "compactPanel"), 1500, "真实停止后未释放并展开");
        check(transport().position(SystemClock.uptimeMillis()) == 0, "紧凑条停止未归零");
        pass("紧凑条真实点击停止、释放并归零");

        start("1:32"); await(() -> held() == 1, 4500, "拖动前未演奏");
        final PointF[] origin = new PointF[1];
        runOnMainSync(() -> origin[0] = center((View) field(service, "panelHeader")));
        long now = SystemClock.uptimeMillis();
        pointer(now, now, MotionEvent.ACTION_DOWN, origin[0]);
        try {
            SystemClock.sleep(650);
            runOnMainSync(() -> check((Boolean) field(service, "compactPanel"), "手指未抬起就展开，导致按钮位置变化"));
            pointer(now, SystemClock.uptimeMillis(), MotionEvent.ACTION_MOVE, new PointF(size.x - 4, size.y - 4));
        } finally { pointer(now, SystemClock.uptimeMillis(), MotionEvent.ACTION_UP, new PointF(size.x - 4, size.y - 4)); }
        await(() -> !(Boolean) field(service, "compactPanel"), 1500, "拖动结束后未恢复操作");
        runOnMainSync(() -> { checkPanelBounds(); checkPanelButtons("继续", "停止", "校准", "收起"); });
        saveScreen("overlay-edge.png");
        pass("播放中拖动保持布局、手动中断暂停、靠边展开仍在屏幕内");
    }
    private void checkPanelBounds() {
        View panel = (View) field(service, "panel"); int[] location = new int[2]; panel.getLocationOnScreen(location);
        check(panel.getWidth() > 0 && panel.getHeight() > 0 && location[0] >= 0 && location[1] >= 0
            && location[0] + panel.getWidth() <= size.x && location[1] + panel.getHeight() <= size.y, "悬浮窗超出屏幕边界");
    }
    private void checkPanelButtons(String... labels) {
        View panel = (View) field(service, "panel"); float density = getTargetContext().getResources().getDisplayMetrics().density;
        for (String label : labels) {
            TextView button = (TextView) find(panel, label);
            check(button != null && button.isShown() && button.isEnabled(), "操作按钮不可用：" + label);
            check(button.getWidth() >= Math.round(48 * density) && button.getHeight() >= Math.round(48 * density), "点击面积过小：" + label);
            check(button.getLayout() != null && button.getLayout().getLineCount() == 1 && button.getLayout().getEllipsisCount(0) == 0
                && button.getPaint().measureText(label) <= button.getWidth() - button.getCompoundPaddingLeft() - button.getCompoundPaddingRight(), "按钮文字被截断：" + label);
        }
    }
    private PointF panelCenter(String label) {
        final PointF[] point = new PointF[1]; runOnMainSync(() -> point[0] = center(find((View) field(service, "panel"), label))); return point[0];
    }
    private PointF center(View view) {
        int[] location = new int[2]; view.getLocationOnScreen(location); return new PointF(location[0] + view.getWidth() / 2f, location[1] + view.getHeight() / 2f);
    }
    private void pointer(long down, long time, int action, PointF point) {
        MotionEvent event = MotionEvent.obtain(down, time, action, point.x, point.y, 0);
        try { sendPointerSync(event); waitForIdleSync(); } finally { event.recycle(); }
    }
    private void start(String notes) {
        runOnMainSync(service::stop);
        // 键盘收到 UP 时系统完成回调可能仍在队列中；下一首需等待服务确认释放。
        await(() -> !(Boolean) field(service, "inFlight") && field(service, "held") == null, 1000, "切歌前触摸未释放");
        runOnMainSync(() -> { service.load(Score.jianpu(notes, 120, "触摸回归测试")); service.toggle(); prepareHalfOff(); });
    }
    private void checkHalfPrompt() {
        View panel = (View) field(service, "panel");
        check((Boolean) field(service, "awaitingHalf"), "未显示半音关闭提示");
        check(find(panel, "未选中") == null && find(panel, "已选中") == null, "仍显示半音状态选择按钮");
        check(find(panel, "开始演奏") == null && find(panel, "取消") == null && find(panel, "半音设为未选中").isShown(), "仍有确认按钮或未显示文字提示");
    }
    private void prepareHalfOff() {
        // 在自建键盘模拟用户按提示关闭半音，正式应用不能读取或猜测游戏按钮状态。
        if ((Boolean) field(keyboard, "half")) find(keyboard.getWindow().getDecorView(), "半音").performClick();
    }
    private void tap(PointF point) {
        long now = SystemClock.uptimeMillis();
        MotionEvent down = MotionEvent.obtain(now, now, MotionEvent.ACTION_DOWN, point.x, point.y, 0);
        MotionEvent up = MotionEvent.obtain(now, now + 50, MotionEvent.ACTION_UP, point.x, point.y, 0);
        try { sendPointerSync(down); sendPointerSync(up); waitForIdleSync(); } finally { down.recycle(); up.recycle(); }
    }
    private void saveScreen(String name) throws java.io.IOException {
        saveScreen(name, 4000);
    }
    private void saveScreen(String name, long delay) throws java.io.IOException {
        // 仅测试入口保存自建界面截图；应用正常演奏不会截图。
        SystemClock.sleep(delay); // 普通截图等待校准提示消失；短暂提示本身需立即截图。
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
        final String[] detail = {""};
        if (service != null) runOnMainSync(() -> {
            detail[0] = "；服务状态=" + field(service, "message") + "；播放状态=" + transport().state;
            if (keyboard != null) {
                Point current = new Point(); keyboard.getWindowManager().getDefaultDisplay().getRealSize(current);
                detail[0] += "；键盘活跃=" + TouchTestActivity.active + "；焦点=" + keyboard.hasWindowFocus()
                    + "；屏幕=" + current + "/" + keyboard.getWindowManager().getDefaultDisplay().getRotation()
                    + "；校准=" + settings.width() + "x" + settings.height() + "/" + settings.rotation();
                try {
                    java.lang.reflect.Method method = MelodicaService.class.getDeclaredMethod("foreground"); method.setAccessible(true);
                    detail[0] += "；前台=" + method.invoke(service);
                } catch (Exception error) {detail[0] += "；前台读取失败=" + error;}
            }
        });
        throw new AssertionError(failure + detail[0]);
    }
    private void check(boolean value, String failure) { if (!value) throw new AssertionError(failure); }
    @Override public void runOnMainSync(Runnable action) {
        // 将主线程断言送回测试线程，确保失败时仍执行设置恢复并输出完整报告。
        final Throwable[] failure = new Throwable[1];
        super.runOnMainSync(() -> { try { action.run(); } catch (Throwable error) { failure[0] = error; } });
        if (failure[0] != null) throw new AssertionError(failure[0]);
    }
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
