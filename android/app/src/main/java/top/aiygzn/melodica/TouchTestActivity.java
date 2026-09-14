package top.aiygzn.melodica;

import android.app.Activity;
import android.os.Bundle;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.HashMap;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** 只接收本应用测试画面的真实触摸，便于验证，不代表游戏兼容性。 */
public final class TouchTestActivity extends Activity {
    public static boolean active;
    private int downs, ups, cancels;
    private int octave, selectorWhileHeld;
    private boolean half;
    private final List<Integer> pitches = new ArrayList<>(), selectors = new ArrayList<>();
    private final List<Long> noteDownTimes = new ArrayList<>(), noteUpTimes = new ArrayList<>();
    private final Map<Integer, TextView> toneButtons = new HashMap<>();
    private final Map<Integer, Long> held = new HashMap<>();
    private TextView state;
    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setPadding(24, 24, 24, 24); setContentView(root);
        TextView title = new TextView(this); title.setText("本地触摸测试  ·  八个音键 + 四个变音按钮"); title.setTextSize(20); root.addView(title);
        TextView help = new TextView(this); help.setText("校准顺序：1～高1、半音、升调、自然音、降调。音区三选一，半音独立开关；播放前请将半音设为未选中。"); root.addView(help);
        state = new TextView(this); state.setTextSize(18); root.addView(state); update("等待演奏");
        View space = new View(this); root.addView(space, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout modes = new LinearLayout(this); root.addView(modes, new LinearLayout.LayoutParams(-1, 120));
        for (int id : new int[]{Score.HALF, Score.HIGH, Score.NATURAL, Score.LOW}) {
            TextView view = new TextView(this); view.setText(Score.LABELS[id]); view.setTextSize(20); view.setGravity(Gravity.CENTER);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, -1, 1); params.setMargins(4, 4, 4, 12); modes.addView(view, params); toneButtons.put(id, view);
            view.setOnClickListener(v -> {
                if (!held.isEmpty()) selectorWhileHeld++;
                selectors.add(id);
                if (id == Score.HALF) half = !half;
                else octave = id == Score.HIGH ? 12 : id == Score.LOW ? -12 : 0;
                updateTones(); update("点击 " + Score.LABELS[id]);
            });
        }
        updateTones();
        LinearLayout keyboard = new LinearLayout(this); root.addView(keyboard, new LinearLayout.LayoutParams(-1, 150));
        for (int i = 0; i < 8; i++) {
            final int key = i; TextView view = new TextView(this); view.setText(Score.LABELS[i]); view.setTextSize(28); view.setGravity(Gravity.CENTER); view.setTextColor(0xff0d1719); view.setBackgroundColor(0xffbdebd9);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, -1, 1); params.setMargins(4, 0, 4, 0); keyboard.addView(view, params);
            view.setOnTouchListener((v, event) -> {
                if (event.getActionMasked() == MotionEvent.ACTION_DOWN) {
                    downs++; held.put(key, event.getEventTime()); pitches.add(60 + Score.SCALE[key] + octave + (half ? 1 : 0));
                    noteDownTimes.add(event.getEventTime());
                    view.setBackgroundColor(0xff66e3ac); update("按下 " + Score.LABELS[key] + " · MIDI " + pitches.get(pitches.size() - 1));
                }
                if (event.getActionMasked() == MotionEvent.ACTION_UP || event.getActionMasked() == MotionEvent.ACTION_CANCEL) {
                    Long start = held.remove(key); if (event.getActionMasked() == MotionEvent.ACTION_UP) { ups++; noteUpTimes.add(event.getEventTime()); } else cancels++;
                    view.setBackgroundColor(0xffbdebd9); update("释放 " + Score.LABELS[key] + " · " + (start == null ? 0 : event.getEventTime() - start) + " ms");
                }
                return true;
            });
        }
    }
    private void updateTones() {
        for (var entry : toneButtons.entrySet()) {
            int id = entry.getKey(); boolean selected = id == Score.HALF ? half : id == (octave < 0 ? Score.LOW : octave > 0 ? Score.HIGH : Score.NATURAL);
            entry.getValue().setSelected(selected); entry.getValue().setTextColor(selected ? 0xff102829 : 0xffd5e9e5);
            entry.getValue().setBackgroundColor(selected ? 0xff66e3ac : 0xff263c3e);
        }
    }
    private void update(String last) {
        String value = "按下 " + downs + " / 抬起 " + ups + " / 取消 " + cancels + " / 按住 " + held.size()
            + "\n" + (octave < 0 ? "降调" : octave > 0 ? "升调" : "自然音") + " · 半音" + (half ? "已选中" : "未选中") + " · " + last;
        state.setText(value);
        android.util.Log.i("MelodicaTouchTest", value.replace('\n', ' '));
    }
    @Override protected void onResume() { super.onResume(); active = true; }
    @Override protected void onPause() { active = false; if (MelodicaService.instance != null) MelodicaService.instance.pause("已离开本地测试键盘"); super.onPause(); }
}
