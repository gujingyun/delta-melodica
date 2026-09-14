package top.aiygzn.melodica;

import android.app.Activity;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/** 离线展示当前版本的权限用途和数据处理范围。 */
public final class DataInfoActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        ScrollView scroll = new ScrollView(this);
        LinearLayout content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL);
        int padding = Math.round(22 * getResources().getDisplayMetrics().density);
        content.setPadding(padding, padding, padding, padding); scroll.addView(content); setContentView(scroll);
        TextView title = new TextView(this); title.setText("权限与数据说明"); title.setTextSize(26); content.addView(title);
        TextView body = new TextView(this); body.setText(R.string.data_information); body.setTextSize(15);
        body.setPadding(0, padding, 0, padding); body.setLineSpacing(6, 1); content.addView(body);
        Button back = new Button(this); back.setText("返回"); content.addView(back); back.setOnClickListener(v -> finish());
    }
}
