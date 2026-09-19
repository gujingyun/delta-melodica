package top.aiygzn.melodica;

import android.app.Activity;
import android.content.Context;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.text.Editable;
import android.text.TextWatcher;

/** 手机界面共用间距和控件，按钮随字体增大而增高。 */
final class Ui {
    static final int BG = 0xff0d1719, CARD = 0xff172729, ACCENT = 0xff66e3ac, TEXT = 0xffedf5f2, MUTED = 0xffa7bebc;
    private Ui() { }
    static int dp(Context c, float value) { return Math.round(value * c.getResources().getDisplayMetrics().density); }
    static LinearLayout column(Context c) { LinearLayout view = new LinearLayout(c); view.setOrientation(LinearLayout.VERTICAL); return view; }
    static GradientDrawable background(Context c, int color, int radius) { GradientDrawable bg = new GradientDrawable(); bg.setColor(color); bg.setCornerRadius(dp(c, radius)); return bg; }
    static LinearLayout root(Activity activity) {
        LinearLayout root = column(activity); root.setPadding(dp(activity, 16), dp(activity, 12), dp(activity, 16), dp(activity, 8)); root.setBackgroundColor(BG); activity.setContentView(root); return root;
    }
    static TextView text(LinearLayout parent, String text, int size, int color) {
        Context c = parent.getContext(); TextView view = new TextView(c); view.setText(text); view.setTextSize(size); view.setTextColor(color);
        view.setPadding(0, dp(c, 4), 0, dp(c, 6)); view.setLineSpacing(dp(c, 2), 1); parent.addView(view); return view;
    }
    static void heading(LinearLayout parent, String title, String description) {
        TextView titleView = text(parent, title, 25, TEXT); titleView.setTypeface(null, Typeface.BOLD);
        if (!description.isEmpty()) text(parent, description, 12, MUTED);
    }
    static LinearLayout card(LinearLayout parent, String title) {
        Context c = parent.getContext(); LinearLayout card = column(c); card.setPadding(dp(c, 14), dp(c, 10), dp(c, 14), dp(c, 14));
        card.setBackground(background(c, CARD, 16)); LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.topMargin = dp(c, 12); parent.addView(card, params);
        if (!title.isEmpty()) { TextView label = text(card, title, 13, ACCENT); label.setTypeface(null, Typeface.BOLD); } return card;
    }
    static LinearLayout row(LinearLayout parent) { LinearLayout row = new LinearLayout(parent.getContext()); row.setGravity(Gravity.CENTER_VERTICAL); row.setBaselineAligned(false); row.setPadding(0, dp(parent.getContext(), 6), 0, 0); parent.addView(row); return row; }
    static Button button(LinearLayout parent, String title, Runnable click, boolean primary) {
        Context c = parent.getContext(); Button button = new Button(c); button.setText(title); button.setAllCaps(false); button.setTextSize(14);
        button.setMinWidth(0); button.setMinimumWidth(0); button.setMinHeight(dp(c, 48)); button.setMinimumHeight(dp(c, 48));
        button.setPadding(dp(c, 8), dp(c, 10), dp(c, 8), dp(c, 10)); button.setTextColor(primary ? BG : TEXT);
        button.setBackground(background(c, primary ? ACCENT : 0xff263c3e, 10));
        LinearLayout.LayoutParams params = parent.getOrientation() == LinearLayout.HORIZONTAL ? new LinearLayout.LayoutParams(0, -2, 1) : new LinearLayout.LayoutParams(-1, -2);
        params.topMargin = parent.getOrientation() == LinearLayout.HORIZONTAL ? 0 : dp(c, 6); params.setMarginEnd(dp(c, 4)); parent.addView(button, params); button.setOnClickListener(v -> click.run()); return button;
    }
    static EditText input(LinearLayout parent, String hint, String value, int type) {
        EditText view = new EditText(parent.getContext()); view.setHint(hint); view.setText(value); view.setInputType(type); view.setTextSize(15); view.setTextColor(TEXT); view.setHintTextColor(MUTED); view.setMinHeight(dp(parent.getContext(), 48)); parent.addView(view, new LinearLayout.LayoutParams(-1, -2)); return view;
    }
    static void watch(EditText text, Runnable changed) {
        text.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) { }
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) { changed.run(); }
            @Override public void afterTextChanged(Editable text) { }
        });
    }
}
