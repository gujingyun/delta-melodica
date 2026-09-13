package top.aiygzn.melodica;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** 仅操作自建界面和临时曲目，不请求无障碍、不访问游戏、不注册真实账号。 */
public final class FeatureChecks extends Instrumentation {
    private final StringBuilder report = new StringBuilder();
    private String layout = "portrait";
    private Activity current;
    @Override public void onCreate(Bundle args) { super.onCreate(args); if (args != null) layout = args.getString("layout", layout); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle(); int code = Activity.RESULT_OK;
        SharedPreferences preferences = getTargetContext().getSharedPreferences("melodica", 0); Map<String, ?> backup = preferences.getAll();
        File folder = new File(new Account(getTargetContext()).profile(), "songs"); Set<String> originals = new HashSet<>(); if (folder.list() != null) java.util.Collections.addAll(originals, folder.list());
        try {
            Library library = new Library(getTargetContext()); Settings settings = new Settings(getTargetContext());
            String source = "/key(C4)\nbpm120\n|:1_ 2_ (3 4) [1 5 :| [2 6 0 5-\nL:小小星星满天亮";
            Score score = Jianpu.source(source, "自编 · 星光练习", "score").score;
            String first = library.saveDocument(new Library.Document(score, source, 120, "score", "", "简谱"));
            String second = library.saveImported(Score.jianpu("1 2 3", 120, "参数隔离测试"), "MIDI");
            settings.selected(first); settings.speed(1.75f); settings.transpose(3); settings.track(-1); settings.setPiano(false); settings.segments(java.util.Collections.singletonList(new ScoreTools.Segment(0, 1000, 2)));
            settings.selected(second); settings.speed(.5f); settings.transpose(-2); settings.setPiano(true);
            Settings restored = new Settings(getTargetContext()); restored.selected(first);
            check(restored.speed() == 1.75 && restored.transpose() == 3 && restored.track() == -1 && !restored.piano(true) && restored.segments().size() == 1, "每曲设置未正确恢复");
            restored.speed(1); restored.transpose(0); restored.segments(new ArrayList<>());
            report.append("通过：每曲速度、移调、音轨、方式、片段隔离与重建恢复\n");
            MainActivity main = (MainActivity) startActivitySync(new Intent(getTargetContext(), MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); current = main; idle();
            screenshot("main"); visible(main, "编辑"); visible(main, "试听"); visible(main, "去演奏"); visible(main, "设置");
            click(main, "试听"); SystemClock.sleep(650); check(((PreviewPlayer) field(main, "previewPlayer")).playing(), "试听未启动"); click(main, "停止试听");
            check(!((PreviewPlayer) field(main, "previewPlayer")).playing(), "试听停止未生效");
            click(main, "演奏"); check(((android.widget.Spinner) field(main, "styles")).getSelectedItemPosition() == 0, "切页后演奏方式被回调覆盖"); screenshot("perform");
            click(main, "设置"); visible(main, "账号 / 云端同步"); screenshot("settings"); click(main, "曲库");
            report.append("通过：三页导航、选择恢复、本机音频启动和停止、可见按钮边界\n");
            ActivityMonitor monitor = addMonitor(ScoreEditorActivity.class.getName(), null, false);
            click(main, "编辑"); ScoreEditorActivity editor = (ScoreEditorActivity) waitForMonitorWithTimeout(monitor, 5000); removeMonitor(monitor); check(editor != null, "编辑器未打开"); current = editor; idle();
            EditText notes = (EditText) field(editor, "notes"); check(source.contentEquals(notes.getText()), "重开未保留原谱"); screenshot("editor-text");
            int firstNote = source.indexOf("1_"); ui(() -> notes.setSelection(firstNote, source.indexOf("[1")));
            click(editor, "试听选中"); SystemClock.sleep(100); check(((PreviewPlayer) field(editor, "player")).playing(), "选段试听未开始"); click(editor, "停止");
            if (!layout.startsWith("landscape")) click(editor, "谱面"); screenshot("editor-score"); visible(editor, "另存到曲库"); visible(editor, "试听全曲");
            click(editor, "试听全曲"); SystemClock.sleep(300); screenshot("editor-follow"); click(editor, "停止");
            if (!layout.startsWith("landscape")) click(editor, "谱文"); ui(() -> notes.setText(source + "\n@")); SystemClock.sleep(550); check(((TextView) field(editor, "status")).getText().toString().contains("请修正"), "错误谱文未被阻止");
            ui(() -> notes.setText(source.replace("1_", "2_"))); SystemClock.sleep(550);
            click(editor, "另存到曲库"); idle(); current = main;
            String saved = new Settings(getTargetContext()).selected(); check(!saved.equals(first), "保存覆盖了原曲");
            check(library.document(first, -2, false).text.equals(source), "原谱文件被修改");
            check(library.document(saved, -2, false).text.contains("2_ 2_"), "修改版原文未保存");
            report.append("通过：原谱重开、选段试听、谱面跟随、错误阻止、另存副本及原曲保留\n");
            monitor = addMonitor(SearchActivity.class.getName(), null, false); click(main, "搜简谱 / MIDI");
            SearchActivity search = (SearchActivity) waitForMonitorWithTimeout(monitor, 5000); removeMonitor(monitor); check(search != null, "聚合搜索入口未打开"); current = search; idle();
            visible(search, "聚合搜索"); visible(search, "返回曲库"); boolean[] sources = (boolean[]) field(search, "sources"); for (boolean enabled : sources) check(enabled, "未默认启用所有来源"); screenshot("search");
            ui(search::finish); current = main; idle(); report.append("通过：聚合搜索页面、五个来源默认全选、返回入口\n");
        } catch (Throwable error) { code = Activity.RESULT_CANCELED; report.append("失败：").append(android.util.Log.getStackTraceString(error)); }
        finally {
            if (current != null) ui(current::finish); waitForIdleSync();
            SharedPreferences.Editor edit = preferences.edit().clear();
            for (Map.Entry<String, ?> entry : backup.entrySet()) {
                Object v = entry.getValue(); String key = entry.getKey();
                if (v instanceof String) edit.putString(key, (String) v); else if (v instanceof Integer) edit.putInt(key, (Integer) v);
                else if (v instanceof Long) edit.putLong(key, (Long) v); else if (v instanceof Float) edit.putFloat(key, (Float) v); else if (v instanceof Boolean) edit.putBoolean(key, (Boolean) v);
            }
            edit.commit(); if (folder.listFiles() != null) for (File file : folder.listFiles()) if (!originals.contains(file.getName()) && !file.delete()) report.append("测试文件清理失败：").append(file.getName());
        }
        result.putString("stream", report.toString()); finish(code, result);
    }
    private static Object field(Object object, String name) throws Exception { Field field = object.getClass().getDeclaredField(name); field.setAccessible(true); return field.get(object); }
    private void ui(Runnable action) {
        java.util.concurrent.atomic.AtomicReference<Throwable> error = new java.util.concurrent.atomic.AtomicReference<>();
        super.runOnMainSync(() -> { try { action.run(); } catch (Throwable e) { error.set(e); } });
        if (error.get() != null) throw new AssertionError(error.get().getMessage(), error.get());
    }
    private void idle() { waitForIdleSync(); SystemClock.sleep(450); }
    private static void check(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static View find(View root, String text) {
        if (!root.isShown()) return null;
        if (root instanceof TextView && text.contentEquals(((TextView) root).getText())) return root;
        if (root instanceof ViewGroup) for (int i = 0; i < ((ViewGroup) root).getChildCount(); i++) { View found = find(((ViewGroup) root).getChildAt(i), text); if (found != null) return found; }
        return null;
    }
    private void visible(Activity activity, String title) {
        ui(() -> {
            View view = find(activity.getWindow().getDecorView(), title); check(view != null, "未找到：" + title); Rect rect = new Rect();
            check(view.getGlobalVisibleRect(rect) && rect.height() >= view.getHeight() - 2 && rect.width() >= view.getWidth() - 2, "控件被裁切：" + title + " 可见=" + rect + " 控件=" + view.getWidth() + "x" + view.getHeight());
        });
    }
    private void click(Activity activity, String title) { ui(() -> { View view = find(activity.getWindow().getDecorView(), title); check(view != null, "未找到按钮：" + title); view.performClick(); }); idle(); }
    private void screenshot(String name) throws Exception {
        Bitmap bitmap = getUiAutomation().takeScreenshot(); check(bitmap != null, "截图失败");
        File file = new File(getTargetContext().getExternalFilesDir(null), "v06-" + layout + "-" + name + ".png");
        try (FileOutputStream out = new FileOutputStream(file)) { bitmap.compress(Bitmap.CompressFormat.PNG, 100, out); } finally { bitmap.recycle(); }
    }
}
