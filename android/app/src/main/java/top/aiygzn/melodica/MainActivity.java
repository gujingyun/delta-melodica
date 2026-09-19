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
    private Button permissionButton, updateButton;
    private boolean checkingUpdate;
    private final java.util.concurrent.ExecutorService updateWorker = java.util.concurrent.Executors.newSingleThreadExecutor();
    private LinearLayout content;
    private boolean refreshing;
    private final android.os.Handler statusHandler = new android.os.Handler(android.os.Looper.getMainLooper());
    private final Runnable refreshStatus = new Runnable() {
        @Override public void run() { if (!isDestroyed()) { updateStatus(); statusHandler.postDelayed(this, 700); } }
    };

    private android.widget.ViewFlipper pages;
    private android.widget.ListView localSongs;
    private EditText filter;
    private Spinner speeds, transposes, styles;
    private TextView selectedTitle, selectedDetail, segmentInfo, accountStatus;
    private Button previewButton;
    private PreviewPlayer previewPlayer;
    private final List<Library.Entry> filtered = new ArrayList<>();
    private final List<Button> tabs = new ArrayList<>();
    private static final Float[] SPEEDS = {.25f, .5f, .75f, 1f, 1.25f, 1.5f, 1.75f, 2f};
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved); settings = new top.aiygzn.melodica.Settings(this); library = new Library(this);
        LinearLayout root = Ui.root(this);
        Ui.text(root, "DELTA MELODICA  /  " + BuildConfig.VERSION_NAME, 10, Ui.ACCENT).setLetterSpacing(.12f);
        pages = new android.widget.ViewFlipper(this); root.addView(pages, new LinearLayout.LayoutParams(-1, 0, 1));
        content = Ui.column(this); pages.addView(content);
        Ui.heading(content, "我的曲库", "找到一首歌，编辑后带进手游。");
        LinearLayout imports = Ui.row(content);
        action(imports, "搜简谱 / MIDI", () -> startActivityForResult(new Intent(this, SearchActivity.class), 11), true);
        action(imports, "导入文件", this::importFile, false);
        LinearLayout sources = Ui.row(content);
        action(sources, "输入简谱", this::editScore, false);
        action(sources, "官网精选", () -> startActivityForResult(new Intent(this, OnlineLibraryActivity.class), 11), false);
        filter = Ui.input(content, "搜索本地曲名", "", InputType.TYPE_CLASS_TEXT); filter.setSingleLine(true);
        localSongs = new android.widget.ListView(this); localSongs.setDividerHeight(dp(6));
        content.addView(localSongs, new LinearLayout.LayoutParams(-1, 0, 1));
        localSongs.setOnItemClickListener((parent, view, position, id) -> {
            Library.Entry entry = filtered.get(position); int index = entries.indexOf(entry); songs.setSelection(index); selectSong(index);
        });
        Ui.watch(filter, this::renderLocal);
        LinearLayout chosen = card("当前曲目");
        selectedTitle = text(chosen, "小星星", 18, Ui.TEXT); selectedTitle.setMaxLines(2); selectedTitle.setEllipsize(android.text.TextUtils.TruncateAt.END);
        selectedDetail = text(chosen, "", 12, Ui.MUTED);
        LinearLayout songActions = Ui.row(chosen);
        action(songActions, "编辑", this::editSelected, false);
        previewButton = action(songActions, "试听", this::previewSong, false);
        action(songActions, "去演奏", () -> showPage(1), true);
        if (getResources().getConfiguration().orientation == android.content.res.Configuration.ORIENTATION_LANDSCAPE) {
            content.removeView(chosen); pages.removeView(content); LinearLayout landscape = new LinearLayout(this);
            landscape.addView(content, new LinearLayout.LayoutParams(0, -1, 1.4f));
            LinearLayout.LayoutParams detail = new LinearLayout.LayoutParams(0, -2, 1); detail.setMarginStart(dp(12)); landscape.addView(chosen, detail); pages.addView(landscape);
        }
        previewPlayer = new PreviewPlayer(this, (position, playing, error) -> {
            previewButton.setText(playing ? "停止试听" : "试听");
            if (!error.isEmpty()) toast(ErrorMessages.redact(error));
            else if (playing && selected != null) selectedDetail.setText("本机试听 " + MelodicaService.time(position) + " / " + MelodicaService.time(selected.duration));
            else describe();
        });
        content = scrollPage(); Ui.heading(content, "演奏", "每首曲目的设置会自动记住。");
        LinearLayout songCard = card("选择与整理");
        songs = new Spinner(this); songCard.addView(songs); songInfo = text(songCard, "", 12, Ui.MUTED);
        text(songCard, "旋律音轨", 12, Ui.MUTED); tracks = new Spinner(this); songCard.addView(tracks);
        text(songCard, "演奏方式", 12, Ui.MUTED); styles = new Spinner(this); songCard.addView(styles);
        adapter(styles, new String[]{"原谱 · 分音", "钢琴适配 · 连奏"});
        styles.setOnItemSelectedListener(listener(i -> { if (!refreshing && settings.piano(defaultPiano()) != (i == 1)) { settings.setPiano(i == 1); applySong(); } }));
        LinearLayout params = card("速度与移调");
        text(params, "速度倍率", 12, Ui.MUTED); speeds = new Spinner(this); params.addView(speeds);
        String[] speedLabels = new String[SPEEDS.length]; for (int i = 0; i < SPEEDS.length; i++) speedLabels[i] = String.format(Locale.ROOT, "%.2f 倍", SPEEDS[i]); adapter(speeds, speedLabels);
        speeds.setOnItemSelectedListener(listener(i -> { if (!refreshing && Math.abs(settings.speed() - SPEEDS[i]) > .001) { settings.speed(SPEEDS[i]); prepare(); describe(); } }));
        text(params, "移调（半音）", 12, Ui.MUTED); transposes = new Spinner(this); params.addView(transposes);
        String[] transposeLabels = new String[49]; for (int i = 0; i < 49; i++) transposeLabels[i] = (i >= 24 ? "+" : "") + (i - 24); adapter(transposes, transposeLabels);
        transposes.setOnItemSelectedListener(listener(i -> { if (!refreshing && settings.transpose() != i - 24) { settings.transpose(i - 24); prepare(); describe(); } }));
        segmentInfo = text(params, "", 12, Ui.MUTED);
        action(params, "片段编排", () -> { if (original != null) new SegmentDialog(this, settings, original, this::applySong).show(); }, false);
        LinearLayout launch = card("进入游戏");
        targetInfo = text(launch, "", 12, Ui.MUTED);
        text(launch, "进入口风琴画面 → 校准 12 个按钮 → 将半音设为未选中 → 播放。提示 3 秒后自动演奏。", 13, Ui.TEXT);
        action(launch, "显示悬浮控制条", () -> { if (selected != null && service()) { prepare(); MelodicaService.instance.showPanel(); toast("已显示，请进入游戏演奏画面"); } }, true);
        action(launch, "停止并隐藏悬浮窗", () -> {
            if (MelodicaService.instance != null) { MelodicaService.instance.stop(); MelodicaService.instance.hidePanel(); }
            updateStatus(); toast("已停止并隐藏，保留已有无障碍授权");
        }, false);
        content = scrollPage(); Ui.heading(content, "设置", "连接演奏服务，管理账号与本机校准。");
        LinearLayout accountCard = card("账号与云端曲库"); accountStatus = text(accountCard, "", 14, Ui.TEXT);
        action(accountCard, "账号 / 云端同步", () -> startActivityForResult(new Intent(this, AccountActivity.class), 12), false);
        LinearLayout setup = card("演奏服务"); serviceStatus = text(setup, "", 14, Ui.TEXT);
        text(setup, "首次在系统设置中开启一次。日常停止、隐藏悬浮窗会保留授权。只有点击播放才演奏。", 12, Ui.MUTED);
        permissionButton = action(setup, "开启无障碍服务", this::requestService, false);
        LinearLayout mapping = card("音键与校准");
        action(mapping, "音键与变音设置", this::mappingDialog, false);
        action(mapping, "打开本地测试键盘", () -> { if (MelodicaService.instance != null) { prepare(); MelodicaService.instance.showPanel(); } startActivity(new Intent(this, TouchTestActivity.class)); }, false);
        text(mapping, "切出目标应用、锁屏或旋转会暂停。更换游戏键位或屏幕方向后，请重新校准。", 12, Ui.MUTED);
        action(content, "权限与数据说明", () -> startActivity(new Intent(this, DataInfoActivity.class)), false);
        updateButton = action(content, "检查更新", this::checkUpdate, false);
        text(content, "v" + BuildConfig.VERSION_NAME + " · Android 8.0+\n手机合成音仅供旋律和节奏试听，游戏音色以实际演奏为准。", 12, Ui.MUTED);
        LinearLayout navigation = Ui.row(root); String[] names = {"曲库", "演奏", "设置"};
        for (int i = 0; i < names.length; i++) { final int index = i; tabs.add(action(navigation, names[i], () -> showPage(index), false)); }
        songs.setOnItemSelectedListener(listener(this::selectSong)); refreshLibrary(); updateStatus(); showPage(saved == null ? 0 : saved.getInt("page", 0));
    }
    private LinearLayout scrollPage() {
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true); LinearLayout box = Ui.column(this); box.setPadding(0, 0, 0, dp(16)); scroll.addView(box); pages.addView(scroll); return box;
    }
    private void showPage(int index) {
        pages.setDisplayedChild(index);
        for (int i = 0; i < tabs.size(); i++) { tabs.get(i).setTextColor(i == index ? Ui.BG : Ui.MUTED); tabs.get(i).setBackground(Ui.background(this, i == index ? Ui.ACCENT : Ui.BG, 10)); }
        ((android.view.inputmethod.InputMethodManager) getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(pages.getWindowToken(), 0);
    }
    private int dp(float value) { return Ui.dp(this, value); }
    private TextView text(LinearLayout parent, String value, int size, int color) { return Ui.text(parent, value, size, color); }
    private LinearLayout card(String title) { return Ui.card(content, title); }
    private Button action(LinearLayout parent, String label, Runnable click, boolean primary) { return Ui.button(parent, label, click, primary); }
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
        entries = library.entries(); original = null; refreshing = true; adapter(songs, entries.toArray(new Library.Entry[0])); int index = 0;
        for (int i = 0; i < entries.size(); i++) if (entries.get(i).id.equals(settings.selected())) index = i;
        songs.setSelection(index); refreshing = false; selectSong(index); renderLocal();
    }
    private void renderLocal() {
        if (entries == null || localSongs == null) return;
        filtered.clear(); List<String> labels = new ArrayList<>();
        for (Library.Entry entry : entries) if (ResourceSearch.matches(entry.title, filter.getText().toString())) {
            filtered.add(entry); labels.add((entry.id.equals(settings.selected()) ? "●  " : "") + entry.title);
        }
        localSongs.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_list_item_1, labels) {
            @Override public View getView(int position, View convert, android.view.ViewGroup parent) {
                TextView view = (TextView) super.getView(position, convert, parent); view.setTextColor(filtered.get(position).id.equals(settings.selected()) ? Ui.ACCENT : Ui.TEXT);
                view.setTextSize(15); view.setMinHeight(dp(56)); view.setBackground(Ui.background(MainActivity.this, Ui.CARD, 10)); return view;
            }
        });
    }
    private boolean defaultPiano() { return library.kind(settings.selected()).equals("MIDI"); }
    private void selectSong(int index) {
        if (refreshing || entries == null || index < 0 || index >= entries.size()) return;
        if (original != null && settings.selected().equals(entries.get(index).id)) return;
        if (previewPlayer != null) previewPlayer.stop();
        try {
            settings.selected(entries.get(index).id); original = library.read(settings.selected());
            TreeSet<Integer> ids = new TreeSet<>(); for (Score.Note n : original.notes) ids.add(n.track);
            List<Integer> trackIds = new ArrayList<>(); trackIds.add(-2); trackIds.add(-1); trackIds.addAll(ids);
            List<String> labels = new ArrayList<>(); labels.add("自动旋律 · 音轨 " + (original.recommendedTrack() + 1)); labels.add("全部音轨 · 高声部"); for (int id : ids) labels.add("音轨 " + (id + 1));
            refreshing = true; tracks.setOnItemSelectedListener(null); adapter(tracks, labels.toArray(new String[0]));
            int track = trackIds.indexOf(settings.track()); if (track < 0) { track = 0; settings.track(-2); } tracks.setSelection(track);
            int speed = 3; for (int i = 0; i < SPEEDS.length; i++) if (Math.abs(SPEEDS[i] - settings.speed()) < .001) speed = i; speeds.setSelection(speed);
            transposes.setSelection(Math.max(0, Math.min(48, settings.transpose() + 24))); styles.setSelection(settings.piano(defaultPiano()) ? 1 : 0);
            refreshing = false; tracks.setOnItemSelectedListener(listener(i -> { if (!refreshing && settings.track() != trackIds.get(i)) { settings.track(trackIds.get(i)); applySong(); } }));
            applySong(); renderLocal();
        } catch (Exception e) { refreshing = false; selected = null; toast("曲谱读取失败：" + ErrorMessages.userMessage(e, "请检查输入后重试")); }
    }
    private void applySong() {
        if (original == null) return;
        try { selected = settings.prepare(original, defaultPiano()); prepare(); describe(); }
        catch (Exception e) { selected = null; if (MelodicaService.instance != null) MelodicaService.instance.stop(); songInfo.setText("请修正设置：" + ErrorMessages.userMessage(e, "请检查输入后重试")); toast(ErrorMessages.userMessage(e, "请检查输入后重试")); }
    }
    private void describe() {
        if (selected == null || selectedTitle == null) return;
        String detail = selected.notes.size() + " 音 · " + MelodicaService.time(Math.round(selected.duration / settings.speed())) + " · " + String.format(Locale.ROOT, "%.2f", settings.speed()) + " 倍";
        selectedTitle.setText(selected.title); selectedDetail.setText(detail); if (songInfo != null) songInfo.setText(detail);
        if (segmentInfo != null) { try { int count = settings.segments().size(); segmentInfo.setText(count == 0 ? "演奏全曲 · 可设置片段" : "已编排 " + count + " 个片段 · 原曲 " + MelodicaService.time(original.duration)); } catch (Exception e) { segmentInfo.setText(ErrorMessages.userMessage(e, "请检查输入后重试")); } }
    }
    private void prepare() {
        if (previewPlayer != null && previewPlayer.playing()) previewPlayer.stop();
        if (selected != null && MelodicaService.instance != null) MelodicaService.instance.load(selected);
    }
    private void previewSong() {
        if (previewPlayer.playing()) { previewPlayer.stop(); return; } if (selected == null) return;
        if (MelodicaService.instance != null) MelodicaService.instance.pause("本机试听");
        previewPlayer.play(selected, settings.speed(), settings.transpose(), settings.base());
    }
    private void editSelected() {
        if (original == null) return;
        startActivityForResult(new Intent(this, ScoreEditorActivity.class).putExtra("songId", settings.selected()).putExtra("track", settings.track()).putExtra("piano", settings.piano(defaultPiano())), 13);
    }
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
    private void checkUpdate() {
        if (checkingUpdate) return;
        checkingUpdate = true; updateButton.setEnabled(false); updateButton.setText("正在检查更新…");
        updateWorker.execute(() -> {
            try {
                AppUpdate latest = AppUpdate.fetch();
                runOnUiThread(() -> showUpdateResult(latest));
            } catch (Exception error) {
                String message = ErrorMessages.userMessage(error, "请检查网络后重试");
                runOnUiThread(() -> showUpdateFailure(message));
            }
        });
    }
    private void showUpdateResult(AppUpdate latest) {
        if (isFinishing() || isDestroyed()) return;
        checkingUpdate = false; updateButton.setEnabled(true); updateButton.setText("检查更新");
        if (latest.versionCode > BuildConfig.VERSION_CODE) {
            String message = "当前版本：v" + BuildConfig.VERSION_NAME + "\n最新版本：v" + latest.version;
            if (!latest.notes.isEmpty()) message += "\n\n更新内容：\n" + latest.notes;
            new AlertDialog.Builder(this).setTitle("发现新版本").setMessage(message)
                .setPositiveButton("下载更新", (dialog, which) -> openUrl(latest.fileUrl))
                .setNegativeButton("稍后", null).show();
        } else {
            new AlertDialog.Builder(this).setTitle("已是最新版本")
                .setMessage("当前版本：v" + BuildConfig.VERSION_NAME + "\n官网版本：v" + latest.version)
                .setPositiveButton("知道了", null).show();
        }
    }
    private void showUpdateFailure(String message) {
        if (isFinishing() || isDestroyed()) return;
        checkingUpdate = false; updateButton.setEnabled(true); updateButton.setText("检查更新");
        new AlertDialog.Builder(this).setTitle("检查更新失败").setMessage(message)
            .setPositiveButton("知道了", null).show();
    }
    private void openUrl(String url) {
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); }
        catch (Exception error) { toast("无法打开下载地址：" + ErrorMessages.userMessage(error, "请稍后重试")); }
    }
    @Override protected void onResume() {
        super.onResume();
        if (settings != null) {
            Library.Entry shown = (Library.Entry) songs.getSelectedItem();
            if (shown != null && !shown.id.equals(settings.selected())) refreshLibrary();
            updateStatus(); statusHandler.removeCallbacks(refreshStatus); statusHandler.postDelayed(refreshStatus, 700);
        }
    }
    @Override protected void onPause() { statusHandler.removeCallbacks(refreshStatus); if (previewPlayer != null) previewPlayer.stop(); super.onPause(); }
    @Override protected void onDestroy() { updateWorker.shutdownNow(); if (previewPlayer != null) previewPlayer.close(); statusHandler.removeCallbacksAndMessages(null); super.onDestroy(); }
    @Override protected void onSaveInstanceState(Bundle state) { super.onSaveInstanceState(state); state.putInt("page", pages.getDisplayedChild()); }
    private void updateStatus() {
        boolean enabled = serviceEnabled();
        Account account = new Account(this); accountStatus.setText(account.signedIn() ? account.email() : "游客模式 · 本地曲库可离线使用");
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
    private void editScore() { startActivityForResult(new Intent(this, ScoreEditorActivity.class), 13); }
    private void importFile() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT); intent.addCategory(Intent.CATEGORY_OPENABLE); intent.setType("*/*"); startActivityForResult(intent, 10);
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == 12) {settings = new top.aiygzn.melodica.Settings(this); library = new Library(this); refreshLibrary(); updateStatus(); return;}
        if ((request == 11 || request == 13) && result == RESULT_OK && data != null && data.getStringExtra("songId") != null) {
            settings.selected(data.getStringExtra("songId")); refreshLibrary(); toast("已加入并选用，可离线编辑和演奏"); return;
        }
        if (request != 10 || result != RESULT_OK || data == null || data.getData() == null) return;
        final Library destination = library;
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
                String id = destination.importBytes(bytes, title);
                runOnUiThread(() -> { if (!isDestroyed() && !isFinishing() && destination == library) { settings.selected(id); refreshLibrary(); toast("已加入曲库"); } });
            } catch (Exception e) { runOnUiThread(() -> { if (!isDestroyed()) toast("导入失败：" + ErrorMessages.userMessage(e, "请检查输入后重试")); }); }
        }, "导入曲谱").start();
    }
}
