package top.aiygzn.melodica;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.text.Spannable;
import android.text.style.BackgroundColorSpan;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.List;

/** 全屏编辑器，保存新副本，手机旋转和进后台时保留编辑草稿。 */
public final class ScoreEditorActivity extends Activity {
    private Library library;
    private Settings settings;
    private EditText title, bpm, notes;
    private TextView status, pageLabel;
    private LinearLayout textPane, previewPane, pageControls;
    private ScrollView textScroll;
    private ScorePreviewView preview;
    private PreviewPlayer player;
    private String mode = "precise", url = "", initial = "";
    private boolean changing, valid, showPreview;
    private final List<String> undo = new ArrayList<>(), redo = new ArrayList<>();
    private String previousText = "";
    private Jianpu.Result parsed, playingResult;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable validateTask = this::validate;
    private BackgroundColorSpan highlight;
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved); library = new Library(this); settings = new Settings(this);
        if (MelodicaService.instance != null) MelodicaService.instance.pause("打开乐曲编辑器");
        Library.Document document;
        try {
            String id = getIntent().getStringExtra("songId");
            document = id == null ? new Library.Document(Score.jianpu(Score.STAR, 100, "自定义简谱"), Score.STAR, 100, "precise", "", "简谱")
                : library.document(id, getIntent().getIntExtra("track", -2), getIntent().getBooleanExtra("piano", library.kind(id).equals("MIDI")));
        } catch (Exception e) { android.widget.Toast.makeText(this, "曲谱读取失败：" + ErrorMessages.userMessage(e, "请检查输入后重试"), android.widget.Toast.LENGTH_LONG).show(); finish(); return; }
        mode = saved == null ? document.mode : saved.getString("mode", document.mode); url = document.url;
        LinearLayout root = Ui.root(this); Ui.heading(root, "乐曲编辑", "另存为修改版 · 原曲保留");
        title = Ui.input(root, "曲名", saved == null ? document.score.title : saved.getString("title"), InputType.TYPE_CLASS_TEXT); title.setSingleLine(true);
        LinearLayout options = Ui.row(root);
        Spinner formats = new Spinner(this); options.addView(formats, new LinearLayout.LayoutParams(0, -2, 1));
        formats.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, new String[]{"精确音符", "原谱 · 谱面规则", "原谱 · 源站播放"}));
        formats.setSelection(mode.equals("precise") ? 0 : mode.equals("score") ? 1 : 2);
        bpm = new EditText(this); bpm.setHint("BPM"); bpm.setSingleLine(true); bpm.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL); bpm.setText(saved == null ? String.valueOf(document.bpm) : saved.getString("bpm"));
        options.addView(bpm, new LinearLayout.LayoutParams(Ui.dp(this, 90), -2)); bpm.setEnabled(mode.equals("precise")); bpm.setContentDescription("精确音符 BPM");
        LinearLayout tabs = Ui.row(root); Ui.button(tabs, "谱文", () -> show(false), false); Ui.button(tabs, "谱面", () -> { validate(); show(true); }, false);
        android.widget.FrameLayout area = new android.widget.FrameLayout(this); root.addView(area, new LinearLayout.LayoutParams(-1, 0, 1));
        textPane = Ui.column(this); area.addView(textPane, new android.widget.FrameLayout.LayoutParams(-1, -1));
        android.widget.HorizontalScrollView symbolScroll = new android.widget.HorizontalScrollView(this); textPane.addView(symbolScroll);
        LinearLayout symbols = new LinearLayout(this); symbolScroll.addView(symbols);
        for (String item : new String[]{"升八度", "降八度", "半拍", "附点", "连线", "休止", "小节", "撤销", "重做", "调号", "速度", "移调"}) Ui.button(symbols, item, () -> symbol(item), false).setLayoutParams(new LinearLayout.LayoutParams(Ui.dp(this, 72), -2));
        textScroll = new ScrollView(this); textPane.addView(textScroll, new LinearLayout.LayoutParams(-1, 0, 1));
        notes = new EditText(this); notes.setId(R.id.score_text); notes.setTextSize(18); notes.setGravity(android.view.Gravity.TOP); notes.setMinLines(8); notes.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS); notes.setTextColor(Ui.TEXT); notes.setText(saved == null ? document.text : saved.getString("notes"));
        textScroll.addView(notes, new ScrollView.LayoutParams(-1, -2)); previousText = notes.getText().toString();
        previewPane = Ui.column(this); area.addView(previewPane, new android.widget.FrameLayout.LayoutParams(-1, -1));
        LinearLayout paging = Ui.row(previewPane); Ui.button(paging, "上一页", () -> changePage(-1), false); pageLabel = Ui.text(paging, "", 12, Ui.MUTED); Ui.button(paging, "下一页", () -> changePage(1), false);
        pageControls = paging;
        ScrollView scoreScroll = new ScrollView(this); previewPane.addView(scoreScroll, new LinearLayout.LayoutParams(-1, 0, 1));
        preview = new ScorePreviewView(this, (left, right) -> { notes.requestFocus(); notes.setSelection(left, right); show(false); textScroll.post(() -> notes.bringPointIntoView(left)); }); scoreScroll.addView(preview);
        status = Ui.text(root, "", 12, Ui.MUTED); status.setMaxLines(3); status.setOnClickListener(v -> new AlertDialog.Builder(this).setTitle("曲谱提示").setMessage(status.getText()).setPositiveButton("知道了", null).show());
        LinearLayout playback = Ui.row(root); Ui.button(playback, "试听全曲", () -> play(false), false); Ui.button(playback, "试听选中", () -> play(true), false); Ui.button(playback, "停止", () -> player.stop(), false);
        LinearLayout footer = Ui.row(root); Ui.button(footer, "另存到曲库", this::save, true); Ui.button(footer, "返回", this::onBackPressed, false);
        if (getResources().getConfiguration().orientation == android.content.res.Configuration.ORIENTATION_LANDSCAPE) {
            root.getChildAt(0).setVisibility(View.GONE); root.getChildAt(1).setVisibility(View.GONE);
            root.removeView(title); root.removeView(options);
            LinearLayout metadata = new LinearLayout(this); metadata.addView(title, new LinearLayout.LayoutParams(0, -2, 1)); metadata.addView(options, new LinearLayout.LayoutParams(0, -2, 1)); root.addView(metadata, 2);
            root.removeView(playback); root.removeView(footer); LinearLayout commands = Ui.row(root);
            commands.addView(playback, new LinearLayout.LayoutParams(0, -2, 1.3f)); commands.addView(footer, new LinearLayout.LayoutParams(0, -2, 1)); status.setMaxLines(2);
            tabs.setVisibility(View.GONE); status.setMaxLines(1);
            area.removeAllViews(); LinearLayout split = new LinearLayout(this); split.setBaselineAligned(false);
            split.addView(textPane, new LinearLayout.LayoutParams(0, -1, 1));
            LinearLayout.LayoutParams right = new LinearLayout.LayoutParams(0, -1, 1); right.setMarginStart(Ui.dp(this, 10)); split.addView(previewPane, right);
            area.addView(split, new android.widget.FrameLayout.LayoutParams(-1, -1));
        }
        player = new PreviewPlayer(this, this::onProgress);
        // 键盘可能首先聚焦曲名；先收起说明区，避免谱文被压成零高后无法获得焦点。
        getWindow().getDecorView().setOnApplyWindowInsetsListener((view, insets) -> {
            boolean keyboard = android.os.Build.VERSION.SDK_INT >= 30
                ? insets.isVisible(android.view.WindowInsets.Type.ime())
                : insets.getSystemWindowInsetBottom() > Ui.dp(this, 160);
            boolean landscape = getResources().getConfiguration().orientation == android.content.res.Configuration.ORIENTATION_LANDSCAPE;
            root.getChildAt(0).setVisibility(keyboard || landscape ? View.GONE : View.VISIBLE); root.getChildAt(1).setVisibility(keyboard || landscape ? View.GONE : View.VISIBLE);
            title.setVisibility(keyboard && !title.hasFocus() ? View.GONE : View.VISIBLE); options.setVisibility(keyboard && !bpm.hasFocus() ? View.GONE : View.VISIBLE);
            tabs.setVisibility(keyboard || landscape ? View.GONE : View.VISIBLE);
            int lines = keyboard || landscape ? 1 : 3; if (status.getMaxLines() != lines) status.setMaxLines(lines);
            return view.onApplyWindowInsets(insets);
        });
        root.getViewTreeObserver().addOnGlobalFocusChangeListener((oldFocus, newFocus) -> getWindow().getDecorView().requestApplyInsets());
        Ui.watch(notes, () -> {
            if (changing) return; String current = notes.getText().toString();
            if (!current.equals(previousText)) { undo.add(previousText); if (undo.size() > 30) undo.remove(0); redo.clear(); previousText = current; changed(); }
        });
        Ui.watch(title, this::changed); Ui.watch(bpm, this::changed);
        formats.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(android.widget.AdapterView<?> parent, View view, int position, long id) {
                String next = new String[]{"precise", "score", "source"}[position]; if (next.equals(mode)) return;
                mode = next; bpm.setEnabled(mode.equals("precise")); changed();
            }
            @Override public void onNothingSelected(android.widget.AdapterView<?> parent) { }
        });
        initial = saved == null ? snapshot() : saved.getString("initial", snapshot()); show(saved != null && saved.getBoolean("preview")); validate();
        if (saved != null) { int left = Math.min(notes.length(), saved.getInt("left")), right = Math.min(notes.length(), saved.getInt("right")); notes.setSelection(left, right); }
        if (saved == null && getIntent().getBooleanExtra("preview", false)) handler.post(() -> { show(true); play(false); });
    }
    private String snapshot() { return title.getText() + "\n" + (source() ? "" : bpm.getText()) + "\n" + mode + "\n" + notes.getText(); }
    private boolean source() { return !mode.equals("precise"); }
    private void show(boolean previewing) {
        boolean split = getResources().getConfiguration().orientation == android.content.res.Configuration.ORIENTATION_LANDSCAPE;
        showPreview = previewing; previewPane.setVisibility(previewing || split ? View.VISIBLE : View.GONE); textPane.setVisibility(!previewing || split ? View.VISIBLE : View.GONE);
        if (previewing) ((android.view.inputmethod.InputMethodManager) getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(notes.getWindowToken(), 0);
    }
    private void changed() { if (changing) return; if (player != null) player.stop(); valid = false; handler.removeCallbacks(validateTask); handler.postDelayed(validateTask, 350); }
    private void validate() {
        handler.removeCallbacks(validateTask);
        try {
            String name = title.getText().toString().trim(); if (name.isEmpty() || name.length() > 100) throw new IllegalArgumentException("曲名需为 1～100 个字符");
            parsed = source() ? Jianpu.source(notes.getText().toString(), name, mode) : Jianpu.precise(notes.getText().toString(), Double.parseDouble(bpm.getText().toString()), name);
            preview.show(notes.getText().toString(), parsed, source()); pageLabel.setText((preview.page() + 1) + "/" + preview.pages()); valid = true;
            pageControls.setVisibility(preview.pages() == 1 && getResources().getConfiguration().orientation == android.content.res.Configuration.ORIENTATION_LANDSCAPE ? View.GONE : View.VISIBLE);
            if (source()) {
                java.util.regex.Matcher tempo = java.util.regex.Pattern.compile("(?im)^bpm\\s*[:=]?\\s*(\\d+(?:\\.\\d+)?)").matcher(java.text.Normalizer.normalize(notes.getText().toString(), java.text.Normalizer.Form.NFKC));
                String value = tempo.find() ? tempo.group(1) : "120"; changing = true; bpm.setText(value); changing = false;
            }
            status.setText(parsed.score.notes.size() + " 音 · " + MelodicaService.time(parsed.score.duration) + (parsed.warnings.isEmpty() ? " · 点谱面可定位文字" : "\n" + String.join("；", parsed.warnings)));
        } catch (Exception e) { valid = false; parsed = null; preview.clear(); status.setText("请修正：" + ErrorMessages.userMessage(e, "请检查输入后重试")); }
    }
    private void changePage(int amount) { preview.page(preview.page() + amount); pageLabel.setText((preview.page() + 1) + "/" + preview.pages()); }
    private void play(boolean selection) {
        validate(); if (!valid) return;
        try {
            Jianpu.Result result = selection ? parsed.selection(Math.min(notes.getSelectionStart(), notes.getSelectionEnd()), Math.max(notes.getSelectionStart(), notes.getSelectionEnd())) : parsed;
            player.stop(); playingResult = result; player.play(result.score, 1, 0, settings.base());
            // play 内部停止旧试听后再恢复本轮时间轴。
            playingResult = result;
        } catch (Exception e) { status.setText(ErrorMessages.userMessage(e, "请检查输入后重试")); }
    }
    private void onProgress(long position, boolean active, String error) {
        if (highlight != null) { notes.getText().removeSpan(highlight); highlight = null; }
        if (!error.isEmpty()) status.setText(error);
        if (!active) {
            preview.mark(null);
            if (error.isEmpty() && parsed != null) status.setText("试听已停止 · " + parsed.score.notes.size() + " 音 · " + MelodicaService.time(parsed.score.duration));
            return;
        }
        Jianpu.Span selected = null;
        if (playingResult != null) for (Jianpu.Span span : playingResult.spans) if (position >= span.start && position < span.end) { selected = span; break; }
        preview.mark(selected); pageLabel.setText((preview.page() + 1) + "/" + preview.pages());
        if (selected != null && selected.right <= notes.length()) {
            highlight = new BackgroundColorSpan(0xff295b47); notes.getText().setSpan(highlight, selected.left, selected.right, Spannable.SPAN_EXCLUSIVE_EXCLUSIVE);
            if (!showPreview) notes.bringPointIntoView(selected.left);
        }
        status.setText("本机试听 " + MelodicaService.time(position) + " / " + MelodicaService.time(playingResult == null ? 0 : playingResult.score.duration));
    }
    private void replaceText(String text) { notes.setText(text); notes.setSelection(notes.length()); }
    private void symbol(String symbol) {
        if (symbol.equals("撤销") || symbol.equals("重做")) {
            List<String> from = symbol.equals("撤销") ? undo : redo, to = symbol.equals("撤销") ? redo : undo;
            if (from.isEmpty()) return; to.add(notes.getText().toString()); changing = true; previousText = from.remove(from.size() - 1); replaceText(previousText); changing = false; changed(); return;
        }
        if (symbol.equals("调号") || symbol.equals("速度") || symbol.equals("移调")) { header(symbol); return; }
        int left = Math.min(notes.getSelectionStart(), notes.getSelectionEnd()), right = Math.max(notes.getSelectionStart(), notes.getSelectionEnd());
        String text = notes.getText().toString();
        if (symbol.equals("小节") || symbol.equals("休止")) { notes.getText().replace(left, right, symbol.equals("小节") ? " | " : " 0 "); return; }
        if (symbol.equals("连线")) { notes.getText().replace(left, right, "(" + (right > left ? text.substring(left, right) : "1 2") + ")"); return; }
        java.util.regex.Matcher match = (source() ? Jianpu.NOTE : Jianpu.PRECISE).matcher(text);
        while (match.find()) if (match.start() <= left && match.end() >= right && (match.end() > left || right == left && match.end() == left)) {
            String token = match.group(), changed;
            if (symbol.equals("升八度") || symbol.equals("降八度")) {
                if (source()) changed = (match.group(1) == null ? "" : match.group(1)) + match.group(2) + octave(match.group(3), symbol.equals("升八度"), true) + match.group(4) + match.group(5);
                else changed = octave(match.group(1), symbol.equals("升八度"), false) + match.group(2) + match.group(3) + (match.group(4) == null ? "" : ":" + match.group(4));
            } else if (source()) {
                String length = match.group(4), dots = match.group(5);
                if (symbol.equals("附点")) dots = dots.length() >= 2 ? "" : dots + ".";
                else if (length.startsWith("-")) { status.setText("长音请直接修改时值"); return; }
                else length = length.endsWith("_") ? length.substring(0, length.length() - 1) + "=" : length + "_";
                changed = (match.group(1) == null ? "" : match.group(1)) + match.group(2) + match.group(3) + length + dots;
            } else {
                double beats = match.group(4) == null ? 1 : fraction(match.group(4)); beats *= symbol.equals("半拍") ? .5 : 1.5;
                changed = match.group(1) + match.group(2) + match.group(3) + ":" + String.format(java.util.Locale.ROOT, "%.9f", beats).replaceAll("0+$", "").replaceAll("\\.$", "");
            }
            notes.getText().replace(match.start(), match.end(), changed); return;
        }
        status.setText("请将光标放在一个完整音符后，或选中该音符");
    }
    private static String octave(String old, boolean up, boolean source) {
        char high = source ? '\'' : '+', low = source ? ',' : '-'; int value = Jianpu.count(old, high) - Jianpu.count(old, low) + (up ? 1 : -1);
        StringBuilder result = new StringBuilder(); for (int i = 0; i < Math.abs(value); i++) result.append(value >= 0 ? high : low); return result.toString();
    }
    private static double fraction(String value) { String[] numbers = value.split("/"); return Double.parseDouble(numbers[0]) / (numbers.length == 2 ? Double.parseDouble(numbers[1]) : 1); }
    private void header(String kind) {
        LinearLayout box = Ui.column(this); box.setPadding(Ui.dp(this, 20), 0, Ui.dp(this, 20), 0);
        EditText input = Ui.input(box, kind.equals("调号") ? "例如 C4、Bb3" : kind.equals("速度") ? "BPM" : "半音数，例如 +2、-1", "", InputType.TYPE_CLASS_TEXT);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(kind).setView(box).setPositiveButton("应用", null).setNegativeButton("取消", null).create();
        dialog.setOnShowListener(d -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            try {
                String value = input.getText().toString().trim(), text = notes.getText().toString(), edited;
                if (kind.equals("移调")) edited = Jianpu.transpose(text, Integer.parseInt(value), source(), mode);
                else if (!source()) { if (kind.equals("调号")) throw new IllegalArgumentException("精确音符请使用移调"); double tempo = Double.parseDouble(value); Jianpu.precise(text, tempo, "校验"); bpm.setText(value); dialog.dismiss(); return; }
                else {
                    java.util.regex.Pattern pattern = kind.equals("调号") ? Jianpu.KEY : java.util.regex.Pattern.compile("(?im)^bpm\\s*[:=]?\\s*\\d+(?:\\.\\d+)?");
                    java.util.regex.Matcher match = pattern.matcher(text); String replacement = kind.equals("调号") ? "/key(" + value + ")" : "bpm" + value;
                    edited = match.find() ? text.substring(0, match.start()) + replacement + text.substring(match.end()) : replacement + "\n" + text;
                    Jianpu.source(edited, "校验", mode);
                }
                replaceText(edited); dialog.dismiss();
            } catch (Exception e) { input.setError(ErrorMessages.userMessage(e, "请检查输入后重试")); }
        })); dialog.show();
    }
    private void save() {
        validate(); if (!valid) return; player.stop();
        try {
            String id = library.saveDocument(new Library.Document(parsed.score, notes.getText().toString(), source() ? 120 : Double.parseDouble(bpm.getText().toString()), mode, url, "简谱"));
            initial = snapshot(); setResult(RESULT_OK, new Intent().putExtra("songId", id)); finish();
        } catch (Exception e) { status.setText("保存失败，编辑内容仍保留：" + ErrorMessages.userMessage(e, "请检查输入后重试")); }
    }
    @Override public void onBackPressed() {
        if (player != null) player.stop();
        if (title == null || snapshot().equals(initial)) { super.onBackPressed(); return; }
        new AlertDialog.Builder(this).setTitle("保留修改？").setMessage("当前修改尚未另存到曲库。").setPositiveButton("另存", (d, w) -> save()).setNegativeButton("放弃修改", (d, w) -> finish()).setNeutralButton("继续编辑", null).show();
    }
    @Override protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out); out.putString("title", title.getText().toString()); out.putString("notes", notes.getText().toString()); out.putString("bpm", bpm.getText().toString());
        out.putString("mode", mode); out.putString("initial", initial); out.putBoolean("preview", showPreview); out.putInt("left", notes.getSelectionStart()); out.putInt("right", notes.getSelectionEnd());
    }
    @Override protected void onPause() { if (player != null) player.stop(); super.onPause(); }
    @Override protected void onDestroy() { handler.removeCallbacksAndMessages(null); if (player != null) player.close(); super.onDestroy(); }
}
