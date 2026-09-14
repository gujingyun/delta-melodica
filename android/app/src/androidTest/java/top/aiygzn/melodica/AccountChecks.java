package top.aiygzn.melodica;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;

/** 只使用隔离目录、虚构账号与假服务，不发邮件、不修改真实曲库或无障碍授权。 */
public final class AccountChecks extends Instrumentation {
    private final StringBuilder report = new StringBuilder();
    @Override public void onCreate(Bundle arguments) {super.onCreate(arguments); start();}
    @Override public void onStart() {
        Bundle result = new Bundle(); int status = Activity.RESULT_OK;
        try {
            String namespace = "account-check-" + UUID.randomUUID();
            File folder = new File(getTargetContext().getCacheDir(), namespace); folder.mkdirs();
            Context isolated = new ContextWrapper(getTargetContext()) {
                @Override public Context getApplicationContext() {return this;}
                @Override public File getFilesDir() {return folder;}
                @Override public SharedPreferences getSharedPreferences(String name, int mode) {return super.getSharedPreferences(namespace + "-" + name, mode);}
            };
            FakeServer server = new FakeServer();
            try {
                Library guest = new Library(isolated); String name = guest.save(Score.jianpu("1 2 3", 100, "游客测试曲"));
                Account first = new Account(isolated, server);
                try {first.sync(); throw new AssertionError("游客可以云同步");} catch (IllegalStateException expected) { }
                first.authenticate("register", "first@example.com", "test-password-123", "123456");
                check(!isolated.getSharedPreferences("account", 0).getString("session", "").contains("token-first"), "令牌以明文保存");
                check(new Account(isolated).userId().equals(first.userId()), "Keystore 会话恢复失败");
                server.loseClaim = true;
                try {first.claimGuest(); throw new AssertionError("未模拟到断网");} catch (java.io.IOException expected) { }
                first = new Account(isolated, server);
                check(first.claimGuest() == 1, "游客继承未恢复"); check(first.claimGuest() == 0, "游客被重复继承");
                check(new File(folder, "songs/" + name).isFile(), "游客原文件丢失");
                first.sync(); first.sync(); check(server.songs.get("first").size() == 1, "同步重试产生重复曲目");
                report.append("通过：游客登录提示、Keystore 加密与恢复、继承断网重试、原文件保留、重复同步去重\n");
                first.logout(); check(new Library(isolated).entries().size() == Library.BUILTIN_COUNT, "游客可见已归属曲目");
                first.authenticate("register", "second@example.com", "test-password-123", "123456");
                check(first.claimGuest() == 0, "第二账号继承了第一账号曲目"); check(new Library(isolated).entries().size() == Library.BUILTIN_COUNT, "账号曲库串号");
                first.logout(); first.authenticate("login", "first@example.com", "test-password-123", "");
                File local = new File(first.profile(), "songs/" + name); check(local.delete(), "测试副本未移除");
                first.sync(); check(new Library(isolated).entries().size() == Library.BUILTIN_COUNT + 1, "云端曲谱未下载到账号曲库");
                first.logout(); report.append("通过：退出登录、账号隔离、云端下载与本地可读曲谱\n");
            } finally {
                isolated.getSharedPreferences("account", 0).edit().clear().commit();
                remove(folder);
            }
            AccountActivity activity = (AccountActivity) startActivitySync(new Intent(getTargetContext(), AccountActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            try {
                waitForIdleSync(); SystemClock.sleep(700);
                runOnMainSync(() -> {
                    View register = find(activity.getWindow().getDecorView(), "注册");
                    check(register != null, "未找到注册入口"); register.performClick();
                });
                waitForIdleSync(); SystemClock.sleep(400);
                check(find(activity.getWindow().getDecorView(), "验证邮箱并注册") != null, "注册按钮未显示");
                Bitmap bitmap = getUiAutomation().takeScreenshot();
                File screenshot = new File(getTargetContext().getExternalFilesDir(null), "account-register.png");
                try (FileOutputStream output = new FileOutputStream(screenshot)) {bitmap.compress(Bitmap.CompressFormat.PNG, 100, output);}
                bitmap.recycle(); report.append("通过：注册页面展示与截图\n");
            } finally {runOnMainSync(activity::finish);}
            MainActivity main = (MainActivity) startActivitySync(new Intent(getTargetContext(), MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            try {
                waitForIdleSync(); SystemClock.sleep(500); saveScreen("release-main.png");
                ActivityMonitor infoMonitor = addMonitor(DataInfoActivity.class.getName(), null, false);
                runOnMainSync(() -> {
                    View info = find(main.getWindow().getDecorView(), "权限与数据说明");
                    check(info != null, "主界面缺少权限与数据说明"); info.performClick();
                });
                Activity information = waitForMonitorWithTimeout(infoMonitor, 3000); removeMonitor(infoMonitor);
                check(information != null, "权限与数据说明页面未打开");
                try {
                    waitForIdleSync(); SystemClock.sleep(500);
                    check(find(information.getWindow().getDecorView(), "权限与数据说明") != null, "说明页面标题缺失");
                    saveScreen("release-data-information.png");
                } finally {runOnMainSync(information::finish);}
                report.append("通过：正式版主界面、离线权限与数据说明入口及截图\n");
            } finally {runOnMainSync(main::finish);}
        } catch (Throwable error) {status = Activity.RESULT_CANCELED; report.append("失败：").append(android.util.Log.getStackTraceString(error));}
        result.putString("stream", report.toString()); finish(status, result);
    }
    private static void check(boolean ok, String message) {if (!ok) throw new AssertionError(message);}
    private void saveScreen(String name) throws Exception {
        Bitmap bitmap = getUiAutomation().takeScreenshot(); check(bitmap != null, "截图失败");
        try (FileOutputStream output = new FileOutputStream(new File(getTargetContext().getExternalFilesDir(null), name))) {
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, output);
        } finally {bitmap.recycle();}
    }
    private static void remove(File target) throws Exception {
        if (target.isDirectory()) for (File child : target.listFiles()) remove(child);
        java.nio.file.Files.deleteIfExists(target.toPath());
    }
    private static View find(View root, String label) {
        if (root instanceof TextView && label.contentEquals(((TextView) root).getText())) return root;
        if (root instanceof ViewGroup) for (int i = 0; i < ((ViewGroup) root).getChildCount(); i++) {View match = find(((ViewGroup) root).getChildAt(i), label); if (match != null) return match;}
        return null;
    }
    private static final class FakeServer implements Account.Transport {
        final Map<String, Map<String, JSONObject>> songs = new HashMap<>();
        final Map<String, String> claims = new HashMap<>();
        boolean loseClaim;
        public JSONObject request(String method, String path, JSONObject body, String token) throws Exception {
            if (path.equals("/auth/register") || path.equals("/auth/login")) {
                String who = body.getString("email").startsWith("first") ? "first" : "second";
                songs.computeIfAbsent(who, ignored -> new HashMap<>());
                return new JSONObject().put("token", "token-" + who).put("expires_at", 9999999999L)
                    .put("user", new JSONObject().put("id", who.equals("first") ? "a".repeat(32) : "b".repeat(32)).put("email", body.getString("email")));
            }
            String who = token.replace("token-", ""); if (!songs.containsKey(who)) throw new IllegalStateException("请登录");
            if (path.equals("/auth/logout")) return new JSONObject();
            if (path.equals("/library/claim")) {
                String key = body.getString("guest_token"); String owner = claims.putIfAbsent(key, who);
                if (owner != null && !owner.equals(who)) throw new IllegalStateException("已归属其他账号");
                if (loseClaim) {loseClaim = false; throw new java.io.IOException("模拟服务器已接受但响应丢失");}
                return new JSONObject();
            }
            if (path.equals("/library/songs") && method.equals("POST")) {
                String id = CloudScore.id(CloudScore.decode(body)); songs.get(who).put(id, body); return new JSONObject().put("id", id);
            }
            if (path.equals("/library/songs")) {
                JSONArray list = new JSONArray(); for (Map.Entry<String, JSONObject> song : songs.get(who).entrySet()) list.put(new JSONObject().put("id", song.getKey()).put("title", song.getValue().getString("title")));
                return new JSONObject().put("songs", list);
            }
            return songs.get(who).get(path.substring(path.lastIndexOf('/') + 1));
        }
    }
}
