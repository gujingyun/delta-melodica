package top.aiygzn.melodica;

import android.app.Instrumentation;
import android.app.UiAutomation;
import android.content.Intent;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.EditText;
import android.widget.ListView;
import android.widget.TextView;
import java.io.File;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.List;
import java.util.function.BooleanSupplier;

/** 专用测试设备上的官网连接与线上曲库界面验证。 */
final class OnlineUiChecks {
    private final Instrumentation test;
    private final StringBuilder report;
    private MainActivity main;
    private OnlineLibraryActivity online;
    private UiAutomation automation;
    OnlineUiChecks(Instrumentation test, StringBuilder report) { this.test = test; this.report = report; }
    void run() throws Exception {
        automation = test.getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
        main = (MainActivity) test.startActivitySync(new Intent(test.getTargetContext(), MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        File downloaded = null; boolean existed = true;
        try {
            open(); await(() -> !(Boolean) field(online, "busy"), 35000, "官网目录请求未结束");
            List<OnlineLibrary.Song> real = songs("catalog"); check(!real.isEmpty(), "官网目录未读取成功：" + ((TextView) field(online, "status")).getText());
            saveScreen("online-catalog-v03.png");
            for (OnlineLibrary.Song song : real) check(!OnlineLibrary.download(song).notes.isEmpty(), "官网 MIDI 无法解析：" + song.title);
            pass("官网目录及当前 " + real.size() + " 首 MIDI 的大小、SHA-256 和解析验证");

            test.runOnMainSync(() -> ((EditText) field(online, "search")).setText("不存在的测试曲目"));
            check(songs("visible").isEmpty() && !((View) field(online, "next")).isEnabled(), "无匹配搜索结果错误");
            List<OnlineLibrary.Song> fixture = new ArrayList<>();
            for (int i = 0; i < 27; i++) fixture.add(new OnlineLibrary.Song("fixture" + i, String.format(java.util.Locale.ROOT, "测试曲目%02d", i), "", "", real.get(0).url, -1, ""));
            test.runOnMainSync(() -> {
                set(online, "catalog", fixture); ((EditText) field(online, "search")).setText("");
                ((View) field(online, "next")).performClick(); ((View) field(online, "next")).performClick();
            });
            check((Integer) field(online, "page") == 2 && songs("visible").size() == 7 && !((View) field(online, "next")).isEnabled(), "分页尾页错误");
            test.runOnMainSync(() -> ((EditText) field(online, "search")).setText("测试曲目26"));
            check((Integer) field(online, "page") == 0 && songs("visible").size() == 1, "搜索没有重置页码");
            pass("搜索、无匹配、27 首分页与搜索重置页码");

            OnlineLibrary.Song chosen = real.get(real.size() - 1); Library library = new Library(main);
            downloaded = new File(main.getFilesDir(), "songs/" + library.onlineId(chosen.id)); existed = downloaded.isFile();
            final boolean cached = existed;
            test.runOnMainSync(() -> { set(online, "catalog", real); ((EditText) field(online, "search")).setText(chosen.title); choose(); });
            clickDialog("取消"); check(downloaded.isFile() == existed, "取消后仍创建曲目");
            test.runOnMainSync(this::choose); clickDialog(cached ? "使用已下载曲目" : "下载并选用");
            await(() -> online.isFinishing() && new Settings(main).selected().equals(library.onlineId(chosen.id)), 35000, "下载后没有返回并选中本地曲目");
            check(library.read(library.onlineId(chosen.id)).title.equals(chosen.title), "下载曲目未保存");
            check(((Library.Entry) ((android.widget.Spinner) field(main, "songs")).getSelectedItem()).id.equals(library.onlineId(chosen.id)), "主界面没有选中线上曲目");
            long modified = downloaded.lastModified(); int files = library.entries().size();
            pass("取消下载、下载并选用、返回主界面并保存本地曲谱");

            open(); await(() -> !(Boolean) field(online, "busy"), 35000, "再次打开目录失败");
            test.runOnMainSync(() -> { ((EditText) field(online, "search")).setText(chosen.title); choose(); });
            clickDialog("使用已下载曲目"); await(online::isFinishing, 3000, "无法使用已下载曲目");
            check(downloaded.lastModified() == modified && library.entries().size() == files, "重复选用产生副本或重新覆盖曲谱");
            pass("已下载标记与重复选用不重复下载／保存");

            open(); test.runOnMainSync(() -> {
                if (!(Boolean) field(online, "busy")) ((View) field(online, "refresh")).performClick();
                check((Boolean) field(online, "busy"), "没有进入目录加载状态"); online.finish();
            }); SystemClock.sleep(600);
            check(new Settings(main).selected().equals(library.onlineId(chosen.id)) && !main.isDestroyed(), "关闭加载页后旧回调改变主界面");
            pass("目录加载中返回，旧回调不改变曲目");
        } finally {
            test.runOnMainSync(() -> { if (online != null && !online.isFinishing()) online.finish(); });
            if (!existed && downloaded != null) java.nio.file.Files.deleteIfExists(downloaded.toPath());
        }
    }
    private void open() {
        Instrumentation.ActivityMonitor monitor = test.addMonitor(OnlineLibraryActivity.class.getName(), null, false);
        test.runOnMainSync(() -> find(main.getWindow().getDecorView(), "官网精选").performClick());
        online = (OnlineLibraryActivity) test.waitForMonitorWithTimeout(monitor, 5000); test.removeMonitor(monitor);
        check(online != null, "线上曲库入口没有打开页面"); test.waitForIdleSync();
    }
    private void choose() { ((ListView) field(online, "list")).performItemClick(null, 0, 0); }
    private void clickDialog(String label) {
        long end = SystemClock.uptimeMillis() + 2000;
        while (SystemClock.uptimeMillis() < end) {
            AccessibilityNodeInfo root = automation.getRootInActiveWindow();
            if (root != null) {
                try { for (AccessibilityNodeInfo node : root.findAccessibilityNodeInfosByText(label)) {
                    try { if (node.isClickable() && node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) return; }
                    finally { node.recycle(); }
                } } finally { root.recycle(); }
            }
            SystemClock.sleep(50);
        }
        throw new AssertionError("未找到弹窗按钮：" + label);
    }
    private void saveScreen(String name) throws Exception {
        SystemClock.sleep(200); android.graphics.Bitmap bitmap = automation.takeScreenshot(); check(bitmap != null, "线上曲库截图失败");
        try (java.io.FileOutputStream output = new java.io.FileOutputStream(new File(test.getTargetContext().getExternalFilesDir(null), name))) {
            check(bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, output), "截图保存失败");
        } finally { bitmap.recycle(); }
    }
    private void await(BooleanSupplier condition, long timeout, String failure) {
        long end = SystemClock.uptimeMillis() + timeout;
        while (SystemClock.uptimeMillis() < end) { boolean[] value = {false}; test.runOnMainSync(() -> value[0] = condition.getAsBoolean()); if (value[0]) return; SystemClock.sleep(40); }
        throw new AssertionError(failure);
    }
    private void pass(String text) { report.append("通过：").append(text).append('\n'); }
    private void check(boolean value, String failure) { if (!value) throw new AssertionError(failure); }
    private Field declared(Object object, String name) throws Exception { Field f = object.getClass().getDeclaredField(name); f.setAccessible(true); return f; }
    private Object field(Object object, String name) { try { return declared(object, name).get(object); } catch (Exception e) { throw new AssertionError(e); } }
    private void set(Object object, String name, Object value) { try { declared(object, name).set(object, value); } catch (Exception e) { throw new AssertionError(e); } }
    @SuppressWarnings("unchecked") private List<OnlineLibrary.Song> songs(String name) { return new ArrayList<>((List<OnlineLibrary.Song>) field(online, name)); }
    private View find(View view, String label) {
        if (view instanceof TextView && label.equals(((TextView) view).getText().toString())) return view;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup) view).getChildCount(); i++) { View found = find(((ViewGroup) view).getChildAt(i), label); if (found != null) return found; }
        return null;
    }
}
