package top.aiygzn.melodica;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/** 搜索逐站返回，取消及关闭后旧任务不再改变当前页面。 */
public final class SearchActivity extends Activity {
    private final ExecutorService workers = Executors.newFixedThreadPool(5);
    private final List<Future<?>> jobs = new ArrayList<>();
    private final List<ResourceSearch.Song> results = new ArrayList<>();
    private final Map<String, Integer> pages = new HashMap<>();
    private final Map<String, String> messages = new java.util.LinkedHashMap<>();
    private final Set<String> more = new HashSet<>(), seen = new HashSet<>();
    private final boolean[] sources = {true, true, true, true, true};
    private EditText query;
    private TextView status;
    private ListView list;
    private Button cancel, loadMore, filters;
    private int request, pending;
    private boolean downloading;
    private String searched = "", selectedId = "";
    private Library library;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state); library = new Library(this);
        LinearLayout root = Ui.root(this); Ui.heading(root, "搜简谱 / MIDI", "搜索后下载到当前曲库，随时离线编辑和演奏");
        query = Ui.input(root, "曲名、歌手或作者", state == null ? "" : state.getString("query", ""), android.text.InputType.TYPE_CLASS_TEXT); query.setSingleLine(true);
        query.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH); query.setOnEditorActionListener((v, action, event) -> { search(false); return true; });
        LinearLayout actions = Ui.row(root); Ui.button(actions, "聚合搜索", () -> search(false), true); cancel = Ui.button(actions, "取消", this::cancelSearch, false); cancel.setEnabled(false);
        filters = Ui.button(root, "全部 5 个来源 · 点此选择", () -> {
            boolean[] chosen = sources.clone();
            new AlertDialog.Builder(this).setTitle("选择搜索来源").setMultiChoiceItems(ResourceSearch.NAMES, chosen, (dialog, which, checked) -> chosen[which] = checked)
                .setPositiveButton("应用", (d, w) -> { System.arraycopy(chosen, 0, sources, 0, sources.length); int count = 0; for (boolean enabled : sources) if (enabled) count++; filters.setText("已选 " + count + " 个来源 · 点此选择"); })
                .setNegativeButton("取消", null).show();
        }, false);
        status = Ui.text(root, "简谱支持按谱面规则、跟随源站播放。\n未标调号或速度时使用 1=C4、120 BPM。", 12, Ui.MUTED);
        status.setMaxLines(3); status.setOnClickListener(v -> new AlertDialog.Builder(this).setTitle("各来源搜索状态").setMessage(status.getText()).setPositiveButton("知道了", null).show());
        list = new ListView(this); list.setDividerHeight(Ui.dp(this, 8)); root.addView(list, new LinearLayout.LayoutParams(-1, 0, 1));
        list.setOnItemClickListener((parent, view, position, id) -> { if (!downloading) choose(results.get(position)); });
        LinearLayout footer = Ui.row(root); loadMore = Ui.button(footer, "加载更多", () -> search(true), false); loadMore.setEnabled(false);
        Ui.button(footer, "打开源站", this::browserSites, false); Ui.button(footer, "返回曲库", this::finish, false);
        if (getResources().getConfiguration().orientation == android.content.res.Configuration.ORIENTATION_LANDSCAPE) {
            root.getChildAt(1).setVisibility(android.view.View.GONE);
            root.removeView(query); actions.addView(query, 0, new LinearLayout.LayoutParams(0, -2, 2));
            status.setMaxLines(2);
        }
        getWindow().getDecorView().setOnApplyWindowInsetsListener((view, insets) -> {
            boolean keyboard = android.os.Build.VERSION.SDK_INT >= 30 ? insets.isVisible(android.view.WindowInsets.Type.ime()) : insets.getSystemWindowInsetBottom() > Ui.dp(this, 160);
            boolean landscape = getResources().getConfiguration().orientation == android.content.res.Configuration.ORIENTATION_LANDSCAPE;
            root.getChildAt(0).setVisibility(keyboard ? android.view.View.GONE : android.view.View.VISIBLE);
            root.getChildAt(1).setVisibility(keyboard || landscape ? android.view.View.GONE : android.view.View.VISIBLE);
            int lines = keyboard ? 1 : landscape ? 2 : 3; if (status.getMaxLines() != lines) status.setMaxLines(lines);
            return view.onApplyWindowInsets(insets);
        });
        if (state != null && state.getBooleanArray("sources") != null) {
            System.arraycopy(state.getBooleanArray("sources"), 0, sources, 0, sources.length); int count = 0; for (boolean enabled : sources) if (enabled) count++;
            filters.setText("已选 " + count + " 个来源 · 点此选择");
        }
    }
    private void cancelJobs() { request++; for (Future<?> job : jobs) job.cancel(true); jobs.clear(); pending = 0; downloading = false; }
    private boolean current(int token) { return token == request && !isFinishing() && !isDestroyed(); }
    private void cancelSearch() { cancelJobs(); status.setText("已取消，已返回的结果保留"); render(); }
    private void search(boolean append) {
        String text = query.getText().toString().trim();
        if (text.isEmpty() || text.length() > 100) { query.setError("请输入 1～100 个字符"); return; }
        if (!append) { cancelJobs(); results.clear(); pages.clear(); more.clear(); messages.clear(); seen.clear(); searched = text; }
        else if (!text.equals(searched)) { search(false); return; }
        if (downloading || pending > 0) return;
        int token = request; List<String> selected = new ArrayList<>();
        for (int i = 0; i < sources.length; i++) if (sources[i] && (!append || more.contains(ResourceSearch.IDS[i]))) selected.add(ResourceSearch.IDS[i]);
        if (selected.isEmpty()) { status.setText("请至少选择一个来源"); render(); return; }
        ((android.view.inputmethod.InputMethodManager) getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(query.getWindowToken(), 0);
        pending = selected.size(); status.setText("正在搜索 " + pending + " 个来源…"); render();
        for (String source : selected) {
            int page = pages.getOrDefault(source, 0) + 1; more.remove(source);
            jobs.add(workers.submit(() -> {
                try {
                    ResourceSearch.Page result = ResourceSearch.search(source, text, page);
                    runOnUiThread(() -> {
                        if (!current(token)) return;
                        for (ResourceSearch.Song song : result.songs) if (results.size() < 5000 && seen.add(song.key())) results.add(song);
                        pages.put(source, page); if (result.more && results.size() < 5000) more.add(source);
                        messages.put(source, result.songs.isEmpty() ? "没有匹配结果" : "找到 " + result.songs.size() + " 首"); finishedSource();
                    });
                } catch (Exception error) { runOnUiThread(() -> { if (current(token)) { messages.put(source, error.getMessage()); finishedSource(); } }); }
            }));
        }
    }
    private void finishedSource() {
        pending--; StringBuilder text = new StringBuilder("已找到 " + results.size() + " 首 · 点此查看来源状态" + (pending > 0 ? " · 还有 " + pending + " 个来源搜索中" : ""));
        for (int i = 0; i < ResourceSearch.IDS.length; i++) if (messages.containsKey(ResourceSearch.IDS[i])) text.append("\n").append(ResourceSearch.NAMES[i]).append("：").append(messages.get(ResourceSearch.IDS[i]));
        status.setText(text); render();
    }
    private void render() {
        List<String> labels = new ArrayList<>();
        for (ResourceSearch.Song song : results) labels.add(song.title + "\n" + song.label() + (song.artist.isEmpty() ? "" : " · " + song.artist) + (song.source.equals("midishow") ? " · 源站下载" : ""));
        list.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_list_item_1, labels) {
            @Override public android.view.View getView(int position, android.view.View convert, android.view.ViewGroup parent) {
                TextView view = (TextView) super.getView(position, convert, parent); view.setTextColor(Ui.TEXT); view.setTextSize(15); view.setMinHeight(Ui.dp(SearchActivity.this, 64)); view.setBackground(Ui.background(SearchActivity.this, Ui.CARD, 10)); return view;
            }
        });
        cancel.setEnabled(pending > 0 || downloading); loadMore.setEnabled(pending == 0 && !downloading && !more.isEmpty()); list.setEnabled(!downloading);
    }
    private void choose(ResourceSearch.Song song) {
        if (song.source.equals("midishow")) {
            new AlertDialog.Builder(this).setTitle(song.title).setMessage("此来源需在浏览器完成验证，并按账号／积分规则下载。回到主界面点「导入文件」选择已下载 MIDI。")
                .setPositiveButton("打开源网页", (d, w) -> open(song.pageUrl)).setNegativeButton("取消", null).show(); return;
        }
        LinearLayout box = Ui.column(this); box.setPadding(Ui.dp(this, 20), 0, Ui.dp(this, 20), 0);
        Ui.text(box, song.label() + (song.artist.isEmpty() ? "" : " · " + song.artist), 14, Ui.MUTED);
        final String[] mode = {"score"};
        if (song.source.equals("jianpu")) {
            android.widget.Spinner rules = new android.widget.Spinner(this); box.addView(rules); rules.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, new String[]{"按谱面规则", "跟随源站播放"}));
            rules.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
                @Override public void onItemSelected(android.widget.AdapterView<?> parent, android.view.View view, int position, long id) { mode[0] = position == 0 ? "score" : "source"; }
                @Override public void onNothingSelected(android.widget.AdapterView<?> parent) { }
            });
            Ui.text(box, "保留原谱、歌词和导入模式；缺省 1=C4、120 BPM。导入后可编辑并试听。", 13, Ui.MUTED);
        }
        new AlertDialog.Builder(this).setTitle(song.title).setView(box)
            .setPositiveButton("下载并选用", (d, w) -> download(song, mode[0], false))
            .setNeutralButton("导入后试听", (d, w) -> download(song, mode[0], true)).setNegativeButton("取消", null).show();
    }
    private void download(ResourceSearch.Song song, String mode, boolean preview) {
        cancelJobs(); int token = request; downloading = true; status.setText("正在导入「" + song.title + "」…"); render();
        jobs.add(workers.submit(() -> {
            try {
                String id = ResourceSearch.download(song, library, mode);
                runOnUiThread(() -> {
                    if (!current(token)) return; downloading = false; selectedId = id; setResult(RESULT_OK, new Intent().putExtra("songId", id)); render();
                    if (preview) startActivityForResult(new Intent(this, ScoreEditorActivity.class).putExtra("songId", id).putExtra("preview", true), 20);
                    else finish();
                });
            } catch (Exception error) { runOnUiThread(() -> { if (current(token)) { downloading = false; status.setText("导入失败：" + error.getMessage() + "\n可重试或打开源站查看"); render(); } }); }
        }));
    }
    private void browserSites() {
        new AlertDialog.Builder(this).setTitle("在浏览器搜索当前曲名").setItems(ResourceSearch.NAMES, (d, index) -> {
            try { open(ResourceSearch.searchUrl(ResourceSearch.IDS[index], query.getText().toString().trim(), 1)); }
            catch (Exception e) { status.setText(e.getMessage()); }
        }).show();
    }
    private void open(String url) { try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); } catch (android.content.ActivityNotFoundException e) { status.setText("手机未安装可用浏览器"); } }
    @Override protected void onSaveInstanceState(Bundle state) { super.onSaveInstanceState(state); state.putString("query", query.getText().toString()); state.putBooleanArray("sources", sources); }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == 20) { if (result == RESULT_OK && data != null) selectedId = data.getStringExtra("songId"); setResult(RESULT_OK, new Intent().putExtra("songId", selectedId)); finish(); }
    }
    @Override protected void onDestroy() { cancelJobs(); workers.shutdownNow(); super.onDestroy(); }
}
