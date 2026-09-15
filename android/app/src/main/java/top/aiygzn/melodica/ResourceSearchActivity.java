package top.aiygzn.melodica;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Future;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** 手机端聚合搜谱入口；各来源并行返回，失败或验证不影响其他来源。 */
public final class ResourceSearchActivity extends Activity {
    private static final int IMPORT_REQUEST = 90;
    private final ExecutorService worker = Executors.newFixedThreadPool(5);
    private final List<Future<?>> jobs = new ArrayList<>();
    private final Map<String, ResourceSearch.SearchSong> songs = new LinkedHashMap<>();
    private final Map<String, Integer> pages = new HashMap<>();
    private final Map<String, String> sourceStatus = new LinkedHashMap<>();
    private final Set<String> pending = new HashSet<>(), more = new HashSet<>();
    private final Map<String, CheckBox> sourceChecks = new LinkedHashMap<>();
    private Library library;
    private EditText search;
    private TextView status, sourceSummary, count;
    private ListView list;
    private Button searchButton, cancelButton, moreButton;
    private List<ResourceSearch.SearchSong> visible = new ArrayList<>();
    private ResourceSearch.SearchSong selectedSong;
    private String activeQuery = "";
    private int request;
    private boolean busy;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state); library = new Library(this);
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(16), dp(18), dp(10)); setContentView(root);
        TextView title = label(root, "搜简谱 / MIDI", 26); title.setTextColor(0xff66e3ac);
        label(root, "简谱空间、官网曲库、BitMidi、MidiWorld、MidiShow", 13);
        LinearLayout searchRow = new LinearLayout(this); root.addView(searchRow, new LinearLayout.LayoutParams(-1, dp(58)));
        search = new EditText(this); search.setSingleLine(true); search.setHint("输入曲名或歌手"); search.setInputType(InputType.TYPE_CLASS_TEXT); searchRow.addView(search, new LinearLayout.LayoutParams(0, -1, 1));
        searchButton = button(searchRow, "搜索", this::startSearch); searchButton.setLayoutParams(new LinearLayout.LayoutParams(dp(86), dp(48)));
        cancelButton = button(searchRow, "取消", this::cancelSearch); cancelButton.setLayoutParams(new LinearLayout.LayoutParams(dp(86), dp(48))); cancelButton.setEnabled(false);
        LinearLayout sourceRow = new LinearLayout(this); root.addView(sourceRow, new LinearLayout.LayoutParams(-1, dp(48)));
        for (ResourceSearch.Source source : ResourceSearch.SOURCES) {
            CheckBox check = new CheckBox(this); check.setText(source.label); check.setTextColor(0xffd5e9e5); check.setTextSize(12); check.setChecked(true);
            sourceChecks.put(source.id, check); sourceRow.addView(check, new LinearLayout.LayoutParams(0, -1, 1));
        }
        status = label(root, "输入曲名或歌手，默认搜索全部来源；支持繁简体曲名匹配。", 13);
        sourceSummary = label(root, "", 12); sourceSummary.setTextColor(0xff8ba8a4);
        count = label(root, "", 12); count.setTextColor(0xff8ba8a4);
        list = new ListView(this); list.setDividerHeight(dp(1)); root.addView(list, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout actions = new LinearLayout(this); root.addView(actions, new LinearLayout.LayoutParams(-1, dp(56)));
        moreButton = button(actions, "加载更多", this::loadMore); moreButton.setEnabled(false);
        button(actions, "打开源网页", this::openSource);
        button(actions, "导入已下载 MIDI", this::importDownloaded);
        button(actions, "返回", this::finish);
        search.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) { }
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) { }
            @Override public void afterTextChanged(Editable text) { }
        });
        search.setOnEditorActionListener((view, actionId, event) -> { startSearch(); return true; });
        list.setOnItemClickListener((parent, view, position, id) -> { if (!busy && position < visible.size()) { selectedSong = visible.get(position); showSong(selectedSong); } });
        render();
    }

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private TextView label(LinearLayout parent, String value, int size) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(0xffd5e9e5); view.setPadding(0, dp(4), 0, dp(4)); parent.addView(view); return view;
    }

    private Button button(LinearLayout parent, String title, Runnable click) {
        Button button = new Button(this); button.setText(title); button.setTextSize(12); button.setAllCaps(false); button.setMinWidth(0); button.setMinimumWidth(0);
        parent.addView(button, new LinearLayout.LayoutParams(0, dp(48), 1)); button.setOnClickListener(v -> click.run()); return button;
    }

    private void startSearch() {
        if (busy) return;
        String query = search.getText().toString().trim(); List<String> selected = selectedSources();
        if (query.isEmpty() || query.length() > 100 || selected.isEmpty()) {
            status.setText("请填写 1～100 个字符的曲名或作者，并至少选择一个来源。"); return;
        }
        cancelJobs(); request++; activeQuery = query; songs.clear(); pages.clear(); more.clear(); sourceStatus.clear(); pending.clear();
        for (String source : selected) { pages.put(source, 0); sourceStatus.put(source, "搜索中…"); pending.add(source); }
        busy = true; status.setText("正在搜索“" + activeQuery + "”…"); render(); submit(selected, request);
    }

    private List<String> selectedSources() {
        List<String> result = new ArrayList<>();
        for (ResourceSearch.Source source : ResourceSearch.SOURCES) if (sourceChecks.get(source.id).isChecked()) result.add(source.id);
        return result;
    }

    private void submit(List<String> sourceIds, int token) {
        String query = activeQuery;
        for (String source : sourceIds) {
            int page = pages.getOrDefault(source, 0) + 1; pages.put(source, page); sourceStatus.put(source, "搜索中…"); pending.add(source);
            jobs.add(worker.submit(() -> {
                try {
                    ResourceSearch.SearchPage result = ResourceSearch.search(source, query, page);
                    runOnUiThread(() -> sourceCompleted(token, source, page, result, null));
                } catch (Exception error) {
                    runOnUiThread(() -> sourceCompleted(token, source, page, null, error));
                }
            }));
        }
        updateSummary();
    }

    private void sourceCompleted(int token, String source, int page, ResourceSearch.SearchPage result, Exception error) {
        if (token != request || isFinishing() || isDestroyed()) return;
        pending.remove(source);
        if (error != null) {
            sourceStatus.put(source, error instanceof ResourceSearch.SiteAccessException ? "需在浏览器验证" : "不可用：" + shortError(error));
            more.remove(source);
        } else {
            sourceStatus.put(source, "第 " + page + " 页 · " + result.songs.size() + " 首");
            if (result.hasMore) more.add(source); else more.remove(source);
            for (ResourceSearch.SearchSong song : result.songs) songs.putIfAbsent(song.key(), song);
        }
        busy = !pending.isEmpty(); render();
        if (!busy) {
            if (songs.isEmpty() && !sourceStatus.isEmpty()) status.setText("未找到匹配曲目，或部分来源需要在浏览器中验证。可换用别名后重试。");
            else if (!more.isEmpty()) status.setText("搜索完成。选择曲目下载，或点击“加载更多”继续读取各来源。");
            else status.setText("搜索完成。选择曲目下载或打开源网页。");
        }
    }

    private void loadMore() {
        if (busy || more.isEmpty()) return;
        List<String> sourceIds = new ArrayList<>(more); more.clear(); pending.clear(); request++; busy = true;
        for (String source : sourceIds) { pending.add(source); sourceStatus.put(source, "搜索中…"); }
        status.setText("正在加载更多结果…"); render(); submit(sourceIds, request);
    }

    private void cancelSearch() {
        if (!busy) return;
        request++; cancelJobs(); pending.clear(); busy = false; status.setText("搜索已取消，已找到的曲目仍可下载。"); render();
    }

    private void cancelJobs() { for (Future<?> job : jobs) job.cancel(true); jobs.clear(); }

    private void render() {
        visible = new ArrayList<>(songs.values());
        List<String> rows = new ArrayList<>();
        for (ResourceSearch.SearchSong song : visible) {
            String access = song.downloadable() ? (song.source.equals("jianpu") ? "简谱 · 直接导入" : "MIDI / JSON · 直接下载") : "源站登录 / 积分";
            rows.add(song.title + (song.artist.isEmpty() ? "" : " · " + song.artist) + "\n" + ResourceSearch.sourceLabel(song.source) + " · " + access);
        }
        list.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_list_item_1, rows) {
            @Override public View getView(int position, View convertView, ViewGroup parent) {
                TextView view = (TextView) super.getView(position, convertView, parent); view.setTextColor(Color.WHITE); view.setTextSize(15); view.setSingleLine(false); view.setPadding(dp(8), dp(13), dp(8), dp(13)); return view;
            }
        });
        count.setText("共 " + visible.size() + " 首"); updateSummary();
        searchButton.setEnabled(!busy); cancelButton.setEnabled(busy); moreButton.setEnabled(!busy && !more.isEmpty()); list.setEnabled(!busy);
    }

    private void updateSummary() {
        StringBuilder summary = new StringBuilder();
        for (ResourceSearch.Source source : ResourceSearch.SOURCES) if (sourceStatus.containsKey(source.id)) {
            if (summary.length() > 0) summary.append("\n"); summary.append(source.label).append("：").append(sourceStatus.get(source.id));
        }
        sourceSummary.setText(summary.toString());
    }

    private void showSong(ResourceSearch.SearchSong song) {
        String detail = (song.artist.isEmpty() ? "" : "作者：" + song.artist + "\n")
            + "来源：" + ResourceSearch.sourceLabel(song.source) + "\n\n"
            + (song.source.equals("jianpu") ? "网页简谱会转换为本地曲谱，导入后可离线演奏。" : song.downloadable() ? "下载并校验后保存到本地，之后无需联网即可演奏。" : "此来源需要在浏览器登录并按源站规则下载，再用“导入已下载 MIDI”。");
        AlertDialog.Builder builder = new AlertDialog.Builder(this).setTitle(song.title).setMessage(detail).setNegativeButton("取消", null)
            .setNeutralButton("打开源网页", (dialog, which) -> openUrl(song.pageUrl));
        builder.setPositiveButton(song.downloadable() ? "下载并选用" : "去源网页", (dialog, which) -> { if (song.downloadable()) download(song); else openUrl(song.pageUrl); }).show();
    }

    private void download(ResourceSearch.SearchSong song) {
        if (busy) return;
        busy = true; int token = ++request; render(); status.setText("正在下载并转换“" + song.title + "”…");
        jobs.add(worker.submit(() -> {
            try {
                String cacheKey = "aggregate:" + song.source + ":" + song.key();
                String id = library.onlineId(cacheKey); boolean cached = false;
                if (library.hasOnline(cacheKey)) {
                    try { library.read(id); cached = true; } catch (Exception ignored) { /* 缓存损坏时重新校验下载。 */ }
                }
                if (!cached) id = library.saveOnline(cacheKey, ResourceSearch.download(song));
                String selected = id;
                runOnUiThread(() -> { if (token == request && !isFinishing() && !isDestroyed()) { setResult(RESULT_OK, new Intent().putExtra("songId", selected)); finish(); } });
            } catch (Exception error) { runOnUiThread(() -> downloadFailure(token, error)); }
        }));
    }

    private void downloadFailure(int token, Exception error) {
        if (token != request || isFinishing() || isDestroyed()) return;
        busy = false; render(); status.setText("下载转换失败，可重新点选重试：" + shortError(error));
    }

    private void openSource() {
        ResourceSearch.SearchSong song = selectedSong != null ? selectedSong : (visible.isEmpty() ? null : visible.get(0));
        if (song != null) { openUrl(song.pageUrl); return; }
        String query = search.getText().toString().trim(); if (!query.isEmpty()) {
            List<String> selected = selectedSources(); openUrl(ResourceSearch.searchUrl(selected.isEmpty() ? "midishow" : selected.get(0), query, 1));
        }
    }

    private void openUrl(String url) {
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); }
        catch (Exception error) { status.setText("无法打开源网页：" + shortError(error)); }
    }

    private void importDownloaded() {
        if (busy) return;
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT); intent.addCategory(Intent.CATEGORY_OPENABLE); intent.setType("*/*"); startActivityForResult(intent, IMPORT_REQUEST);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != IMPORT_REQUEST || resultCode != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData(); busy = true; int token = ++request; render(); status.setText("正在导入曲谱…");
        jobs.add(worker.submit(() -> {
            try {
                String title = "导入曲谱";
                try (Cursor cursor = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) { if (cursor != null && cursor.moveToFirst()) title = cursor.getString(0); }
                byte[] bytes;
                try (InputStream input = getContentResolver().openInputStream(uri); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                    if (input == null) throw new IllegalArgumentException("无法读取文件"); byte[] buffer = new byte[8192]; int count;
                    while ((count = input.read(buffer)) != -1) { if (output.size() + count > OnlineLibrary.MAX_SONG_BYTES) throw new IllegalArgumentException("文件不能超过 10 MB"); output.write(buffer, 0, count); }
                    bytes = output.toByteArray();
                }
                Score score;
                if (bytes.length >= 4 && bytes[0] == 'M' && bytes[1] == 'T' && bytes[2] == 'h' && bytes[3] == 'd') score = MidiReader.read(bytes, title);
                else { String text = new String(bytes, StandardCharsets.UTF_8).replace("\ufeff", ""); if (text.trim().startsWith("{")) score = CloudScore.decode(new org.json.JSONObject(text)); else score = Score.jianpu(text, 100, title); }
                String id = library.save(score);
                String selected = id; runOnUiThread(() -> { if (token == request && !isFinishing() && !isDestroyed()) { setResult(RESULT_OK, new Intent().putExtra("songId", selected)); finish(); } });
            } catch (Exception error) { runOnUiThread(() -> downloadFailure(token, error)); }
        }));
    }

    private String shortError(Exception error) {
        String value = ErrorMessages.userMessage(error, "网络或曲谱格式异常");
        return value.length() > 120 ? value.substring(0, 120) : value;
    }

    @Override protected void onDestroy() { request++; cancelJobs(); worker.shutdownNow(); super.onDestroy(); }
}
