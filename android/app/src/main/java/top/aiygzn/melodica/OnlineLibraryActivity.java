package top.aiygzn.melodica;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** 线上目录的搜索、分页和下载入口，网络工作不阻塞界面。 */
public final class OnlineLibraryActivity extends Activity {
    private static final int PAGE_SIZE = 10;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private List<OnlineLibrary.Song> catalog = new ArrayList<>(), visible = new ArrayList<>();
    private Library library;
    private EditText search;
    private TextView status, pageInfo;
    private ListView list;
    private Button refresh, previous, next;
    private int page, request;
    private boolean busy;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state); library = new Library(this);
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setPadding(dp(20), dp(18), dp(20), dp(12)); setContentView(root);
        TextView title = label(root, "线上曲库", 26); title.setTextColor(0xff66e3ac);
        label(root, "官网 MIDI / JSON 曲谱 · 下载后可离线演奏", 13);
        search = new EditText(this); search.setSingleLine(true); search.setHint("搜索曲名或作者"); root.addView(search);
        status = label(root, "正在读取目录…", 13);
        list = new ListView(this); list.setDividerHeight(dp(1)); root.addView(list, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout pages = new LinearLayout(this); root.addView(pages);
        previous = button(pages, "上一页", () -> { page--; render(); });
        pageInfo = label(pages, "", 13); pageInfo.setGravity(android.view.Gravity.CENTER);
        pageInfo.setLayoutParams(new LinearLayout.LayoutParams(0, dp(48), 1));
        next = button(pages, "下一页", () -> { page++; render(); });
        LinearLayout actions = new LinearLayout(this); root.addView(actions);
        refresh = button(actions, "刷新目录", this::refreshCatalog);
        button(actions, "返回曲库", this::finish);
        search.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) { }
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) { page = 0; render(); }
            @Override public void afterTextChanged(Editable text) { }
        });
        list.setOnItemClickListener((parent, view, position, id) -> { if (!busy) showSong(visible.get(position)); });
        refreshCatalog();
    }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private TextView label(LinearLayout parent, String text, int size) {
        TextView view = new TextView(this); view.setText(text); view.setTextSize(size); view.setTextColor(0xffd5e9e5); view.setPadding(0, dp(6), 0, dp(6)); parent.addView(view); return view;
    }
    private Button button(LinearLayout row, String title, Runnable click) {
        Button button = new Button(this); button.setText(title); button.setTextSize(13); button.setMinWidth(0); button.setMinimumWidth(0);
        row.addView(button, new LinearLayout.LayoutParams(0, dp(48), 1)); button.setOnClickListener(v -> click.run()); return button;
    }
    private void render() {
        List<OnlineLibrary.Song> filtered = OnlineLibrary.search(catalog, search.getText().toString());
        int pages = Math.max(1, (filtered.size() + PAGE_SIZE - 1) / PAGE_SIZE); page = Math.max(0, Math.min(page, pages - 1));
        visible = new ArrayList<>(filtered.subList(page * PAGE_SIZE, Math.min(filtered.size(), (page + 1) * PAGE_SIZE)));
        List<String> rows = new ArrayList<>();
        for (OnlineLibrary.Song song : visible) rows.add(song.title + "\n" + (song.artist.isEmpty() ? (song.format.equals("score") ? "JSON 曲谱" : "MIDI") : song.artist)
            + " · " + (song.size > 0 ? String.format(Locale.ROOT, "%.1f KB · ", song.size / 1024.0) : "")
            + (library.hasOnline(song.id) ? "已下载 · 点选使用" : "点选下载"));
        list.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_list_item_1, rows) {
            @Override public View getView(int position, View convertView, ViewGroup parent) {
                TextView view = (TextView) super.getView(position, convertView, parent); view.setTextColor(Color.WHITE); view.setTextSize(16);
                view.setSingleLine(false); view.setPadding(dp(8), dp(15), dp(8), dp(15)); return view;
            }
        });
        pageInfo.setText((page + 1) + " / " + pages + " 页 · " + filtered.size() + " 首");
        previous.setEnabled(!busy && page > 0); next.setEnabled(!busy && page + 1 < pages);
        refresh.setEnabled(!busy); search.setEnabled(!busy); list.setEnabled(!busy);
        if (!busy && !catalog.isEmpty()) status.setText(filtered.isEmpty() ? "没有匹配曲目，试试其他关键词" : "共 " + catalog.size() + " 首 · 每页 " + PAGE_SIZE + " 首");
    }
    private boolean current(int token) { return token == request && !isFinishing() && !isDestroyed(); }
    private void refreshCatalog() {
        if (busy) return;
        busy = true; int token = ++request; render(); status.setText("正在读取官网目录…");
        worker.execute(() -> {
            try {
                List<OnlineLibrary.Song> songs = OnlineLibrary.fetchCatalog();
                runOnUiThread(() -> { if (current(token)) { catalog = songs; page = 0; busy = false; render(); if (catalog.isEmpty()) status.setText("线上曲库暂时没有曲目"); } });
            } catch (Exception error) { showFailure(token, "目录读取失败，请检查网络后刷新；本地曲目仍可使用", error); }
        });
    }
    private void showSong(OnlineLibrary.Song song) {
        boolean downloaded = library.hasOnline(song.id);
        String detail = (song.artist.isEmpty() ? "" : "作者：" + song.artist + "\n") + (song.description.isEmpty() ? "" : song.description + "\n\n")
            + (downloaded ? "已保存在本地，选用后可调速、移调和选择音轨。" : "下载并选用这首曲谱，之后无需联网即可演奏。");
        new AlertDialog.Builder(this).setTitle(song.title).setMessage(detail)
            .setPositiveButton(downloaded ? "使用已下载曲目" : "下载并选用", (dialog, which) -> download(song))
            .setNegativeButton("取消", null).show();
    }
    private void download(OnlineLibrary.Song song) {
        if (busy) return;
        busy = true; int token = ++request; render(); status.setText("正在准备「" + song.title + "」…");
        worker.execute(() -> {
            try {
                String id = library.onlineId(song.id); boolean cached = false;
                if (library.hasOnline(song.id)) {
                    try { library.read(id); cached = true; }
                    catch (Exception ignored) { /* 缓存损坏时重新下载，验证成功后再替换。 */ }
                }
                if (!cached) id = library.saveOnline(song.id, OnlineLibrary.download(song));
                OnlineLibrary.checkCancelled(); String selectedId = id;
                runOnUiThread(() -> { if (current(token)) { setResult(RESULT_OK, new Intent().putExtra("songId", selectedId)); finish(); } });
            } catch (Exception error) { showFailure(token, "曲目下载失败，可重新点选重试", error); }
        });
    }
    private void showFailure(int token, String message, Exception error) {
        runOnUiThread(() -> { if (current(token)) { busy = false; render(); status.setText(message + "\n" + ErrorMessages.userMessage(error, "网络或曲谱格式异常")); } });
    }
    @Override protected void onDestroy() { request++; worker.shutdownNow(); super.onDestroy(); }
}
