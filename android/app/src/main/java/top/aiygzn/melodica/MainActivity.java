package top.aiygzn.melodica;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ComponentName;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.provider.Settings;
import android.text.InputType;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.TreeSet;

/** 安卓曲库和设置入口，无障碍权限始终交由系统页面和用户开启。 */
public final class MainActivity extends Activity {
    private top.aiygzn.melodica.Settings settings;
    private Library library;
    private List<Library.Entry> entries;
    private Score original, selected;
    private Spinner songs, tracks;
    private TextView serviceStatus, songInfo, targetInfo;
    private Button permissionButton;
    private LinearLayout content;
    private boolean refreshing;
    private final android.os.Handler statusHandler = new android.os.Handler(android.os.Looper.getMainLooper());
    private final Runnable refreshStatus = new Runnable() {
        @Override public void run() { if (!isDestroyed()) { updateStatus(); statusHandler.postDelayed(this, 700); } }
    };
    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState); settings = new top.aiygzn.melodica.Settings(this); library = new Library(this);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true);
        content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL); content.setPadding(dp(22), dp(28), dp(22), dp(32));
        scroll.addView(content); setContentView(scroll);
        TextView eyebrow = text(content, "DELTA MELODICA  /  ANDROID", 11, 0xff66e3ac); eyebrow.setLetterSpacing(.12f);
        TextView title = text(content, "三角洲口风琴", 30, Color.WHITE); title.setTypeface(null, Typeface.BOLD);
        text(content, "把熟悉的旋律，带进手游。", 14, 0xffa7bebc);
        action(content, "账号 / 云端同步", () -> startActivityForResult(new Intent(this, AccountActivity.class), 12), false);
        LinearLayout setup = card("01  连接演奏服务");
        serviceStatus = text(setup, "", 14, Color.WHITE);
        text(setup, "首次需在系统设置中开启一次。平时停止、隐藏悬浮窗会保留授权，下次直接使用；只有点击播放后才演奏。", 12, 0xffa7bebc);
        permissionButton = action(setup, "开启无障碍服务", this::requestService, false);
        LinearLayout libraryCard = card("02  选择一首曲目");
        songs = new Spinner(this); libraryCard.addView(songs);
        songInfo = text(libraryCard, "", 13, 0xffa7bebc);
        tracks = new Spinner(this); libraryCard.addView(tracks);
        LinearLayout importRow = new LinearLayout(this); libraryCard.addView(importRow);
        action(importRow, "导入 MIDI / 简谱", this::importFile, false);
        action(importRow, "输入简谱", this::editScore, false);
        action(libraryCard, "线上曲库", () -> startActivityForResult(new Intent(this, OnlineLibraryActivity.class), 11), false);
        LinearLayout params = card("03  调整演奏");
        text(params, "速度倍率", 12, 0xffa7bebc);
        Spinner speeds = new Spinner(this); params.addView(speeds);
        Float[] values = {.25f, .5f, .75f, 1f, 1.25f, 1.5f, 1.75f, 2f};
        String[] speedLabels = new String[values.length]; int speedIndex = 3;
        for (int i = 0; i < values.length; i++) { speedLabels[i] = String.format(Locale.ROOT, "%.2f 倍", values[i]); if (Math.abs(values[i] - settings.speed()) < .01) speedIndex = i; }
        adapter(speeds, speedLabels); speeds.setSelection(speedIndex);
        speeds.setOnItemSelectedListener(listener(i -> { settings.speed(values[i]); prepare(); }));
        text(params, "移调（半音）", 12, 0xffa7bebc);
        Spinner transposes = new Spinner(this); params.addView(transposes); String[] transposeLabels = new String[49];
        for (int i = 0; i < 49; i++) transposeLabels[i] = (i >= 24 ? "+" : "") + (i - 24);
        adapter(transposes, transposeLabels); transposes.setSelection(settings.transpose() + 24);
        transposes.setOnItemSelectedListener(listener(i -> { settings.transpose(i - 24); prepare(); }));
        action(params, "音键与变音设置", this::mappingDialog, false);
        LinearLayout launch = card("04  进入游戏演奏");
        targetInfo = text(launch, "", 12, 0xffa7bebc);
        text(launch, "进入口风琴演奏画面 → 校准八个音键及半音、升调、自然音、降调 → 播放前确认半音是否选中。首次播放倒计时 3 秒。", 14, Color.WHITE);
        action(launch, "显示悬浮控制条", () -> { if (service()) { prepare(); MelodicaService.instance.showPanel(); toast("已显示，请进入游戏演奏画面"); } }, true);
        action(launch, "打开本地测试键盘", () -> { if (MelodicaService.instance != null) { prepare(); MelodicaService.instance.showPanel(); } startActivity(new Intent(this, TouchTestActivity.class)); }, false);
        action(launch, "停止并隐藏悬浮窗", () -> {
            if (MelodicaService.instance != null) { MelodicaService.instance.stop(); MelodicaService.instance.hidePanel(); }
            updateStatus(); toast(serviceEnabled() ? "已停止并隐藏，保留无障碍授权" : "已停止并隐藏悬浮窗");
        }, false);
        text(content, "预览版 0.5  ·  Android 8.0+\n日常停止保留无障碍授权。线上曲库、12 点校准及音区切换优化继续可用；演奏期间禁用收起。", 11, 0xff789795);
        songs.setOnItemSelectedListener(listener(this::selectSong));
        refreshLibrary(); updateStatus();
    }
    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private TextView text(LinearLayout parent, String value, int size, int color) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color); view.setPadding(0, dp(5), 0, dp(6)); view.setLineSpacing(dp(2), 1); parent.addView(view); return view;
    }
    private LinearLayout card(String title) {
        LinearLayout card = new LinearLayout(this); card.setOrientation(LinearLayout.VERTICAL); card.setPadding(dp(16), dp(12), dp(16), dp(14));
        GradientDrawable background = new GradientDrawable(); background.setColor(0xff172729); background.setCornerRadius(dp(18)); card.setBackground(background);
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-1, -2); layout.topMargin = dp(18); content.addView(card, layout);
        TextView label = text(card, title, 12, 0xff66e3ac); label.setTypeface(null, Typeface.BOLD); return card;
    }
    private Button action(LinearLayout parent, String label, Runnable click, boolean primary) {
        Button button = new Button(this); button.setText(label); button.setTextSize(14); button.setAllCaps(false); button.setMinWidth(0); button.setMinimumWidth(0);
        button.setTextColor(primary ? 0xff0d1719 : 0xffd5e9e5);
        GradientDrawable bg = new GradientDrawable(); bg.setColor(primary ? 0xff66e3ac : 0xff263c3e); bg.setCornerRadius(dp(10)); button.setBackground(bg);
        LinearLayout.LayoutParams layout = parent.getOrientation() == LinearLayout.HORIZONTAL ? new LinearLayout.LayoutParams(0, dp(48), 1) : new LinearLayout.LayoutParams(-1, dp(48));
        layout.topMargin = dp(10); layout.rightMargin = dp(4); parent.addView(button, layout); button.setOnClickListener(v -> click.run()); return button;
    }
    private interface Select { void run(int index); }
    private AdapterView.OnItemSelectedListener listener(Select select) {
        return new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) { select.run(position); }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        };
    }
    private <T> void adapter(Spinner spinner, T[] labels) {
        ArrayAdapter<T> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, labels); adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); spinner.setAdapter(adapter);
    }
    private void refreshLibrary() {
        entries = library.entries(); adapter(songs, entries.toArray(new Library.Entry[0])); int selectedIndex = 0;
        for (int i = 0; i < entries.size(); i++) if (entries.get(i).id.equals(settings.selected())) selectedIndex = i;
        songs.setSelection(selectedIndex); selectSong(selectedIndex);
    }
    private void selectSong(int index) {
        if (index < 0 || index >= entries.size()) return;
        try {
            settings.selected(entries.get(index).id); original = library.read(entries.get(index).id);
            TreeSet<Integer> ids = new TreeSet<>(); for (Score.Note n : original.notes) ids.add(n.track);
            List<Integer> trackIds = new ArrayList<>(); trackIds.add(original.recommendedTrack()); trackIds.add(-1); trackIds.addAll(ids);
            List<String> labels = new ArrayList<>(); labels.add("自动旋律 · 音轨 " + (trackIds.get(0) + 1)); labels.add("全部音轨 · 高声部");
            for (int id : ids) labels.add("音轨 " + (id + 1));
            refreshing = true; tracks.setOnItemSelectedListener(null); adapter(tracks, labels.toArray(new String[0])); tracks.setSelection(0); refreshing = false;
            tracks.setOnItemSelectedListener(listener(i -> { if (!refreshing) { selected = original.melody(trackIds.get(i)); prepare(); describe(); } }));
            selected = original.melody(trackIds.get(0)); prepare(); describe();
        } catch (Exception e) { toast("曲谱读取失败：" + e.getMessage()); }
    }
    private void describe() { if (selected != null) songInfo.setText(selected.notes.size() + " 个旋律音  ·  原曲 " + MelodicaService.time(selected.duration)); }
    private void prepare() { if (selected != null && MelodicaService.instance != null) MelodicaService.instance.load(selected); }
    private boolean service() {
        if (MelodicaService.instance != null) return true;
        if (serviceEnabled()) toast("已授权，等待系统连接；若长时间未恢复，可进入「管理无障碍授权」检查服务状态");
        else requestService();
        return false;
    }
    boolean serviceEnabled() {
        // 已授权但服务尚未绑定时，不能把它误报为没有权限。
        String enabled = Settings.Secure.getString(getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        if (enabled == null) return false;
        ComponentName own = new ComponentName(this, MelodicaService.class);
        for (String name : enabled.split(":")) if (own.equals(ComponentName.unflattenFromString(name))) return true;
        return false;
    }
    private void requestService() {
        if (serviceEnabled()) { openAccessibilitySettings(); return; }
        new AlertDialog.Builder(this).setTitle("开启演奏服务")
            .setMessage("本工具使用无障碍手势，在你标记的音键位置发送触摸。读取窗口所属应用用于切出暂停；不读取文字、不截图。公开曲库仅下载；账号注册继承及主动云同步会上传可演奏曲谱副本到私有曲库，不上传窗口信息或校准设置。\n\n请在系统页面找到「三角洲口风琴 · 演奏服务」并开启。首次必须由你确认；之后使用「停止并隐藏悬浮窗」可保留授权，无需每次重新开启。")
            .setPositiveButton("前往系统设置", (d, w) -> openAccessibilitySettings())
            .setNegativeButton("取消", null).show();
    }
    private void openAccessibilitySettings() {
        try { startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)); }
        catch (ActivityNotFoundException | SecurityException e) { toast("系统未提供跳转入口，请在手机设置的无障碍页面开启演奏服务"); }
    }
    private void toast(String text) { android.widget.Toast.makeText(this, text, android.widget.Toast.LENGTH_LONG).show(); }
    @Override protected void onResume() { super.onResume(); if (settings != null) { updateStatus(); statusHandler.removeCallbacks(refreshStatus); statusHandler.postDelayed(refreshStatus, 700); } }
    @Override protected void onPause() { statusHandler.removeCallbacks(refreshStatus); super.onPause(); }
    private void updateStatus() {
        boolean enabled = serviceEnabled();
        String state = MelodicaService.instance != null ? "●  演奏服务已连接 · 授权已保留"
            : enabled ? "◐  已授权，等待系统连接；无需重复申请" : "○  未授权，请先开启无障碍服务";
        if (!state.contentEquals(serviceStatus.getText())) serviceStatus.setText(state);
        String label = enabled ? "管理无障碍授权" : "开启无障碍服务";
        if (!label.contentEquals(permissionButton.getText())) permissionButton.setText(label);
        targetInfo.setText(!settings.calibrated() ? "需要重新校准：八个音键 + 四个变音按钮" : "已绑定：" + settings.target() + "\n12 点校准画面：" + settings.width() + " × " + settings.height());
    }
    private void mappingDialog() {
        LinearLayout box = new LinearLayout(this); box.setOrientation(LinearLayout.VERTICAL); box.setPadding(dp(22), dp(12), dp(22), dp(12));
        text(box, "中央 1 的 MIDI 音高（默认 C4 = 60）", 13, Color.WHITE);
        EditText base = new EditText(this); base.setInputType(InputType.TYPE_CLASS_NUMBER); base.setText(String.valueOf(settings.base())); box.addView(base);
        text(box, "升调 / 自然音 / 降调为三选一，点击后保持；半音独立开关，可与任一音区组合。请校准全部 12 个按钮。", 13, Color.WHITE);
        text(box, "当前映射：升调高一个八度，降调低一个八度，半音升半音；超出总音域时按八度折回。开始和续播前请如实确认游戏内半音状态。手动调整变音前请先暂停。", 12, 0xffa7bebc);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("音键与变音").setView(box).setPositiveButton("保存", null).setNegativeButton("取消", null).create();
        dialog.setOnShowListener(d -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            try { int value = Integer.parseInt(base.getText().toString()); if (value < 24 || value > 96) throw new IllegalArgumentException("中央音高需为 24～96");
                settings.base(value); prepare(); dialog.dismiss();
            } catch (Exception e) { base.setError("中央音高需为 24～96"); }
        })); dialog.show();
    }
    private void editScore() {
        LinearLayout box = new LinearLayout(this); box.setOrientation(LinearLayout.VERTICAL); box.setPadding(dp(20), dp(8), dp(20), dp(8));
        EditText title = new EditText(this); title.setHint("曲名"); title.setText("自定义简谱"); box.addView(title);
        EditText bpm = new EditText(this); bpm.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL); bpm.setText("100"); bpm.setHint("BPM：20～300"); box.addView(bpm);
        EditText notes = new EditText(this); notes.setMinLines(4); notes.setMaxLines(7); notes.setText(settings.editor()); notes.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE); box.addView(notes);
        text(box, "空格分隔：1 2 3:2 0 +1 -5 #4\n0 为休止，:2 两拍，:1/2 半拍，+ / - 为八度。", 12, 0xffa7bebc);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("保存简谱").setView(box).setPositiveButton("保存到曲库", null).setNegativeButton("取消", null).create();
        dialog.setOnShowListener(d -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            try { Score score = Score.jianpu(notes.getText().toString(), Double.parseDouble(bpm.getText().toString()), title.getText().toString().trim().isEmpty() ? "自定义简谱" : title.getText().toString().trim());
                settings.selected(library.save(score)); settings.editor(notes.getText().toString()); refreshLibrary(); dialog.dismiss();
            } catch (Exception e) { notes.setError(e.getMessage()); }
        })); dialog.show();
    }
    private void importFile() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT); intent.addCategory(Intent.CATEGORY_OPENABLE); intent.setType("*/*"); startActivityForResult(intent, 10);
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == 12) {library = new Library(this); refreshLibrary(); return;}
        if (request == 11 && result == RESULT_OK && data != null && data.getStringExtra("songId") != null) {
            settings.selected(data.getStringExtra("songId")); refreshLibrary(); toast("已选用线上曲目，可离线演奏"); return;
        }
        if (request != 10 || result != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData(); toast("正在导入曲谱…");
        new Thread(() -> {
            try {
                String title = "导入曲谱";
                try (Cursor cursor = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
                    if (cursor != null && cursor.moveToFirst()) title = cursor.getString(0);
                }
                byte[] bytes;
                try (InputStream in = getContentResolver().openInputStream(uri); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                    if (in == null) throw new IllegalArgumentException("无法读取文件");
                    byte[] buffer = new byte[8192]; int count;
                    while ((count = in.read(buffer)) != -1) { if (out.size() + count > 10 * 1024 * 1024) throw new IllegalArgumentException("文件不能超过 10 MB"); out.write(buffer, 0, count); }
                    bytes = out.toByteArray();
                }
                Score score;
                if (bytes.length >= 4 && bytes[0] == 'M' && bytes[1] == 'T' && bytes[2] == 'h' && bytes[3] == 'd') score = MidiReader.read(bytes, title);
                else {
                    String text = new String(bytes, StandardCharsets.UTF_8).replace("\ufeff", "");
                    if (text.trim().startsWith("{")) score = CloudScore.decode(new org.json.JSONObject(text));
                    else {if (bytes.length > 512000) throw new IllegalArgumentException("文本简谱过大"); score = Score.jianpu(text, 100, title);}
                }
                String id = library.save(score);
                runOnUiThread(() -> { settings.selected(id); if (!isDestroyed()) { refreshLibrary(); toast("已加入曲库"); } });
            } catch (Exception e) { runOnUiThread(() -> { if (!isDestroyed()) toast("导入失败：" + e.getMessage()); }); }
        }, "导入曲谱").start();
    }
}
