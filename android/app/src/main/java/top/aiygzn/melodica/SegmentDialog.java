package top.aiygzn.melodica;

import android.app.Activity;
import android.app.AlertDialog;
import android.text.InputType;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** 片段先在对话框中编排，点击应用才替换当前曲目的设置。 */
final class SegmentDialog {
    private final Activity activity;
    private final Settings settings;
    private final Score score;
    private final Runnable applied;
    private final List<ScoreTools.Segment> segments = new ArrayList<>();
    private ListView list;
    private EditText start, end, repeats;
    private int selected = -1;
    SegmentDialog(Activity activity, Settings settings, Score score, Runnable applied) {
        this.activity = activity; this.settings = settings; this.score = score; this.applied = applied;
        try { segments.addAll(settings.segments()); } catch (Exception ignored) { /* 损坏设置允许在此清空重建。 */ }
    }
    void show() {
        LinearLayout box = Ui.column(activity); box.setPadding(Ui.dp(activity, 16), 0, Ui.dp(activity, 16), Ui.dp(activity, 8));
        Ui.text(box, "按原曲秒数编排，支持小数。空列表表示全曲。\n原曲时长 " + String.format(Locale.ROOT, "%.3f 秒", score.duration / 1000.0), 13, Ui.MUTED);
        LinearLayout fields = Ui.row(box);
        start = field(fields, "起点（秒）", "0"); end = field(fields, "终点（秒）", String.format(Locale.ROOT, "%.3f", score.duration / 1000.0)); repeats = field(fields, "重复次数", "1");
        LinearLayout edit = Ui.row(box);
        Ui.button(edit, "添加", () -> change(false), false); Ui.button(edit, "更新选中", () -> change(true), false);
        list = new ListView(activity); list.setChoiceMode(ListView.CHOICE_MODE_SINGLE); box.addView(list, new LinearLayout.LayoutParams(-1, Ui.dp(activity, 160)));
        list.setOnItemClickListener((parent, view, position, id) -> { selected = position; ScoreTools.Segment segment = segments.get(position); start.setText(String.valueOf(segment.start / 1000.0)); end.setText(String.valueOf(segment.end / 1000.0)); repeats.setText(String.valueOf(segment.repeat)); });
        LinearLayout reorder = Ui.row(box);
        Ui.button(reorder, "上移", () -> move(-1), false); Ui.button(reorder, "下移", () -> move(1), false);
        Ui.button(reorder, "删除", () -> { if (selected >= 0 && selected < segments.size()) { segments.remove(selected); selected = -1; render(); } }, false);
        Ui.button(box, "清空，恢复全曲", () -> { segments.clear(); selected = -1; render(); }, false);
        android.widget.ScrollView scroll = new android.widget.ScrollView(activity); scroll.addView(box);
        AlertDialog dialog = new AlertDialog.Builder(activity).setTitle("片段编排").setView(scroll).setPositiveButton("应用", null).setNegativeButton("取消", null).create();
        dialog.setOnShowListener(d -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            try { ScoreTools.arrange(score, segments); settings.segments(segments); applied.run(); dialog.dismiss(); }
            catch (Exception e) { end.setError(ErrorMessages.userMessage(e, "请检查输入后重试")); }
        })); dialog.show(); render();
    }
    private EditText field(LinearLayout row, String hint, String text) {
        EditText view = new EditText(activity); view.setHint(hint); view.setText(text); view.setTextSize(14); view.setSingleLine(true); view.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        row.addView(view, new LinearLayout.LayoutParams(0, -2, 1)); view.setContentDescription(hint); return view;
    }
    private void change(boolean replace) {
        try {
            if (replace && selected < 0) throw new IllegalArgumentException("请先选择要更新的片段");
            double left = Double.parseDouble(start.getText().toString()), right = Double.parseDouble(end.getText().toString());
            if (!Double.isFinite(left) || !Double.isFinite(right)) throw new IllegalArgumentException("请填写有效秒数");
            ScoreTools.Segment segment = new ScoreTools.Segment(Math.round(left * 1000), Math.round(right * 1000), Integer.parseInt(repeats.getText().toString()));
            if (segment.end > score.duration) throw new IllegalArgumentException("终点不能超过原曲时长");
            List<ScoreTools.Segment> draft = new ArrayList<>(segments); if (replace) draft.set(selected, segment); else draft.add(segment); ScoreTools.arrange(score, draft);
            segments.clear(); segments.addAll(draft); render();
        } catch (Exception e) { end.setError(ErrorMessages.userMessage(e, "请检查输入后重试")); }
    }
    private void move(int offset) { int next = selected + offset; if (selected < 0 || next < 0 || next >= segments.size()) return; java.util.Collections.swap(segments, selected, next); selected = next; render(); }
    private void render() {
        List<String> rows = new ArrayList<>();
        for (ScoreTools.Segment segment : segments) rows.add(String.format(Locale.ROOT, "%.3f → %.3f 秒   × %d", segment.start / 1000.0, segment.end / 1000.0, segment.repeat));
        list.setAdapter(new ArrayAdapter<>(activity, android.R.layout.simple_list_item_single_choice, rows)); if (selected >= 0) list.setItemChecked(selected, true);
    }
}
