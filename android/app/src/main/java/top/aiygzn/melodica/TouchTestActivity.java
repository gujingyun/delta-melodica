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
import java.util.Map;

/** 只接收本应用测试画面的真实触摸，便于验证，不代表游戏兼容性。 */
public final class TouchTestActivity extends Activity {
    public static boolean active;
    private int downs, ups, cancels;
    private final Map<Integer, Long> held = new HashMap<>();
    private TextView state;
    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON | WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setPadding(24, 24, 24, 24); setContentView(root);
        TextView title = new TextView(this); title.setText("本地触摸测试  ·  请先在这里校准八个音键"); title.setTextSize(20); root.addView(title);
        TextView help = new TextView(this); help.setText("拖开悬浮条，在下方八键依次校准；播放小星星。可查看重复音、按住时长和停止释放。"); root.addView(help);
        state = new TextView(this); state.setTextSize(18); root.addView(state); update("等待演奏");
        View space = new View(this); root.addView(space, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout keyboard = new LinearLayout(this); root.addView(keyboard, new LinearLayout.LayoutParams(-1, 150));
        for (int i = 0; i < 8; i++) {
            final int key = i; TextView view = new TextView(this); view.setText(Score.LABELS[i]); view.setTextSize(28); view.setGravity(Gravity.CENTER); view.setTextColor(0xff0d1719); view.setBackgroundColor(0xffbdebd9);
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, -1, 1); params.setMargins(4, 0, 4, 0); keyboard.addView(view, params);
            view.setOnTouchListener((v, event) -> {
                if (event.getActionMasked() == MotionEvent.ACTION_DOWN) { downs++; held.put(key, event.getEventTime()); view.setBackgroundColor(0xff66e3ac); update("按下 " + Score.LABELS[key]); }
                if (event.getActionMasked() == MotionEvent.ACTION_UP || event.getActionMasked() == MotionEvent.ACTION_CANCEL) {
                    Long start = held.remove(key); if (event.getActionMasked() == MotionEvent.ACTION_UP) ups++; else cancels++;
                    view.setBackgroundColor(0xffbdebd9); update("释放 " + Score.LABELS[key] + " · " + (start == null ? 0 : event.getEventTime() - start) + " ms");
                }
                return true;
            });
        }
    }
    private void update(String last) {
        String value = "按下 " + downs + " / 抬起 " + ups + " / 取消 " + cancels + " / 按住 " + held.size() + "\n" + last;
        state.setText(value);
        android.util.Log.i("MelodicaTouchTest", value.replace('\n', ' '));
    }
    @Override protected void onResume() { super.onResume(); active = true; }
    @Override protected void onPause() { active = false; if (MelodicaService.instance != null) MelodicaService.instance.pause("已离开本地测试键盘"); super.onPause(); }
}
