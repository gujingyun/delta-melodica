package top.aiygzn.melodica;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.text.InputType;
import android.graphics.Color;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;

/** 账号操作独立页面；后台请求不阻塞界面，离开页面后不回调旧视图。 */
public final class AccountActivity extends Activity {
    private Account account;
    private LinearLayout content;
    private TextView status;
    private EditText email, password, code;
    private final List<android.view.View> controls = new ArrayList<>();
    private String mode = "login";
    private boolean running;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state); account = new Account(this);
        if (MelodicaService.instance != null) MelodicaService.instance.pause("打开账号面板");
        render();
    }
    private int dp(int n) {return Math.round(n * getResources().getDisplayMetrics().density);}
    private TextView text(String value, int size) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(Color.WHITE); view.setPadding(0, dp(8), 0, dp(8)); content.addView(view); return view;
    }
    private Button button(String title, Runnable action) {
        Button view = new Button(this); view.setText(title); view.setAllCaps(false); content.addView(view); view.setOnClickListener(v -> action.run()); controls.add(view); return view;
    }
    private EditText input(String hint, int type) {
        EditText view = new EditText(this); view.setHint(hint); view.setSingleLine(true); view.setInputType(type); content.addView(view); controls.add(view); return view;
    }
    private void render() {
        controls.clear(); ScrollView scroll = new ScrollView(this); content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL); content.setPadding(dp(22), dp(20), dp(22), dp(24)); scroll.addView(content); setContentView(scroll);
        text("账号与云端曲库", 26);
        if (account.signedIn()) {
            text(account.email(), 18); text("邮箱已验证 · 本机账号曲库可离线演奏", 13);
            button("同步我的云端曲库", () -> run(account::sync, false));
            button("合并本机游客曲库…", this::merge);
            button("退出登录，使用游客模式", () -> run(account::logout, true));
        } else {
            text("游客模式 · 本地导入、演奏和公开曲库可用", 13);
            LinearLayout tabs = new LinearLayout(this); content.addView(tabs);
            for (String item : new String[]{"login", "register", "reset"}) {
                Button tab = new Button(this); tab.setText(item.equals("login") ? "登录" : item.equals("register") ? "注册" : "找回密码");
                tabs.addView(tab, new LinearLayout.LayoutParams(0, -2, 1)); controls.add(tab); tab.setOnClickListener(v -> {mode = item; render();});
                tab.setEnabled(!mode.equals(item));
            }
            email = input("邮箱地址", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS);
            password = input(mode.equals("reset") ? "新密码（10～128 字符）" : "密码（10～128 字符）", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
            if (!mode.equals("login")) {
                code = input("6 位邮箱验证码", InputType.TYPE_CLASS_NUMBER);
                button("发送邮箱验证码", () -> {
                    final String address = email.getText().toString().trim(), purpose = mode;
                    run(() -> account.request("POST", "/auth/request-code", new JSONObject().put("email", address).put("purpose", purpose)).getString("message"), false);
                });
            }
            button(mode.equals("login") ? "登录" : mode.equals("register") ? "验证邮箱并注册" : "验证邮箱并重置密码", this::submit);
            text("注册后，本机游客曲谱自动归入此账号并上传到私有云端。原文件保留为本机备份。", 13);
        }
        status = text("", 14); button("返回本地曲库", () -> {setResult(RESULT_OK); finish();});
    }
    private interface Work {String run() throws Exception;}
    private void run(Work work, boolean refresh) {
        if (running) return;
        running = true; status.setText("正在处理…"); for (android.view.View view : controls) view.setEnabled(false);
        new Thread(() -> {
            String message;
            try {message = work.run();} catch (Exception error) {message = "未完成：" + (error.getMessage() == null ? "请检查网络并重试；本机曲谱仍保留" : error.getMessage());}
            final String result = message;
            runOnUiThread(() -> {
                if (isDestroyed() || isFinishing()) return;
                running = false; for (android.view.View view : controls) view.setEnabled(true);
                if (refresh) render(); status.setText(result); setResult(RESULT_OK);
            });
        }, "账号与云同步").start();
    }
    private void submit() {
        final String selected = mode, address = email.getText().toString().trim(), secret = password.getText().toString(), verification = mode.equals("login") ? "" : code.getText().toString().trim();
        if (secret.length() < 10 || secret.length() > 128) {status.setText("密码需为 10～128 个字符"); return;}
        password.setText("");
        run(() -> {
            if (selected.equals("reset")) return account.request("POST", "/auth/reset-password", new JSONObject().put("email", address).put("password", secret).put("code", verification)).getString("message");
            account.authenticate(selected, address, secret, verification);
            if (selected.equals("register")) {account.claimGuest(); return account.sync();}
            return "已登录。可同步云端曲库；本机游客曲目可点击「合并本机游客曲库」加入账号。";
        }, true);
    }
    private void merge() {
        new AlertDialog.Builder(this).setTitle("合并游客曲库").setMessage("将本机尚未归属账号的游客曲谱加入当前账号，并同步至私有云端？同一批曲谱不会再次自动归入其他账号。")
            .setPositiveButton("合并并同步", (d, w) -> run(() -> {account.claimGuest(); return account.sync();}, false)).setNegativeButton("取消", null).show();
    }
    @Override public void onBackPressed() {if (!running) {setResult(RESULT_OK); super.onBackPressed();} else status.setText("正在处理，请稍候；本机曲谱会保留。");}
}
