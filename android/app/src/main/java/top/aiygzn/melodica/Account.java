package top.aiygzn.melodica;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** 账号会话由 Android Keystore 保护，账号曲库独立保存，游客原文件保留备份。 */
public final class Account {
    public static final String API = "https://aiygzn.top/melodica/account-api";
    private static final String KEY = "melodica-account-session";
    private final Context context;
    private final SharedPreferences preferences;
    private JSONObject session;
    interface Transport {JSONObject request(String method, String path, JSONObject body, String token) throws Exception;}
    private final Transport transport;
    public Account(Context context) {
        this(context, null);
    }
    Account(Context context, Transport transport) {
        this.transport = transport;
        this.context = context.getApplicationContext();
        preferences = this.context.getSharedPreferences("account", Context.MODE_PRIVATE);
        try {
            String encrypted = preferences.getString("session", "");
            if (!encrypted.isEmpty()) session = new JSONObject(new String(decrypt(encrypted), StandardCharsets.UTF_8));
            if (session != null && !session.getJSONObject("user").getString("id").matches("[a-f0-9]{32}")) session = null;
        } catch (Exception ignored) { session = null; /* 凭据无法恢复时要求重新登录，曲库文件仍保留。 */ }
    }
    public String userId() { return session == null ? "" : session.optJSONObject("user").optString("id"); }
    public String email() { return session == null ? "" : session.optJSONObject("user").optString("email"); }
    public boolean signedIn() { return !userId().isEmpty(); }
    public File profile() { return signedIn() ? new File(context.getFilesDir(), "accounts/" + userId()) : context.getFilesDir(); }
    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (!store.containsAlias(KEY)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(KEY, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(KEY, null);
    }
    private String encrypt(byte[] bytes) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        return Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP) + ":" + Base64.encodeToString(cipher.doFinal(bytes), Base64.NO_WRAP);
    }
    private byte[] decrypt(String value) throws Exception {
        String[] parts = value.split(":", 2);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)));
        return cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP));
    }
    public JSONObject request(String method, String path, JSONObject body) throws Exception {
        if (transport != null) return transport.request(method, path, body, session == null ? "" : session.getString("token"));
        HttpURLConnection connection = (HttpURLConnection) new URL(API + path).openConnection();
        connection.setConnectTimeout(8000); connection.setReadTimeout(20000); connection.setInstanceFollowRedirects(false);
        connection.setRequestMethod(method); connection.setRequestProperty("Content-Type", "application/json");
        if (session != null) connection.setRequestProperty("Authorization", "Bearer " + session.getString("token"));
        try {
            if (body != null) {
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                if (bytes.length > 2 * 1024 * 1024) throw new IllegalArgumentException("曲谱超过 2 MB 云同步限制");
                connection.setDoOutput(true); connection.setFixedLengthStreamingMode(bytes.length);
                try (OutputStream out = connection.getOutputStream()) {out.write(bytes);}
            }
            int status = connection.getResponseCode();
            if (status >= 300 && status < 400) throw new IllegalArgumentException("账号服务发生重定向，请稍后重试");
            JSONObject response;
            try (InputStream input = status >= 400 ? connection.getErrorStream() : connection.getInputStream()) {
                if (input == null) throw new IllegalArgumentException("账号服务暂时不可用");
                response = new JSONObject(new String(OnlineLibrary.readLimited(input, 2 * 1024 * 1024, System.nanoTime() + 20_000_000_000L), StandardCharsets.UTF_8));
            }
            if (status >= 400) throw new IllegalArgumentException(response.optString("detail", "账号请求失败，请稍后重试"));
            return response;
        } finally { connection.disconnect(); }
    }
    public void authenticate(String mode, String email, String password, String code) throws Exception {
        JSONObject data = new JSONObject().put("email", email).put("password", password).put("client", "native");
        if (mode.equals("register")) data.put("code", code);
        JSONObject response = request("POST", "/auth/" + mode, data);
        if (!response.getJSONObject("user").getString("id").matches("[a-f0-9]{32}")) throw new IllegalArgumentException("账号标识无效");
        if (!preferences.edit().putString("session", encrypt(response.toString().getBytes(StandardCharsets.UTF_8))).commit()) throw new IllegalStateException("本机登录状态保存失败，请重新登录");
        session = response;
    }
    public String logout() throws Exception {
        String text = "已退出，当前为游客模式";
        try { request("POST", "/auth/logout", new JSONObject()); }
        catch (Exception e) {text = "本机已退出；网络不可用，服务器会话将到期失效";}
        if (!preferences.edit().remove("session").commit()) throw new IllegalStateException("本机凭据清理失败，请重试");
        session = null; return text;
    }
    private File stateFile() { return new File(context.getFilesDir(), "guest-claims.json"); }
    private JSONObject state() throws Exception {
        return stateFile().isFile() ? new JSONObject(new String(Files.readAllBytes(stateFile().toPath()), StandardCharsets.UTF_8))
            : new JSONObject().put("owners", new JSONObject());
    }
    static void writeJson(File target, JSONObject value) throws Exception {
        File folder = target.getParentFile(); if (folder == null || (!folder.isDirectory() && !folder.mkdirs())) throw new IllegalStateException("无法创建曲库目录");
        File temp = File.createTempFile(".account-", ".tmp", folder);
        try {
            Files.write(temp.toPath(), value.toString().getBytes(StandardCharsets.UTF_8));
            Files.move(temp.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        } finally {Files.deleteIfExists(temp.toPath());}
    }
    public boolean guestVisible(String name) {
        try {return !state().getJSONObject("owners").has(name);}
        catch (Exception e) {return false; /* 继承记录损坏时不把已归属曲谱再次当作游客数据。 */}
    }
    public List<File> guestFiles() throws Exception {
        JSONObject owners = state().getJSONObject("owners");
        File[] files = new File(context.getFilesDir(), "songs").listFiles(); List<File> result = new ArrayList<>();
        if (files != null) for (File file : files) if (file.isFile() && file.getName().matches("[a-f0-9-]+\\.json") && !owners.has(file.getName())) result.add(file);
        return result;
    }
    public boolean pendingClaim() throws Exception {return state().has("pending");}
    public int claimGuest() throws Exception {
        if (!signedIn()) throw new IllegalStateException("请先登录");
        JSONObject state = state(), pending = state.optJSONObject("pending");
        if (pending != null && !pending.getString("user").equals(userId())) throw new IllegalArgumentException("有其他账号的游客继承尚未完成，请先登录原账号");
        if (pending == null) {
            JSONArray names = new JSONArray(); for (File file : guestFiles()) names.put(file.getName());
            if (names.length() == 0) return 0;
            pending = new JSONObject().put("user", userId()).put("token", UUID.randomUUID().toString().replace("-", "")).put("files", names);
            state.put("pending", pending); writeJson(stateFile(), state);
        }
        request("POST", "/library/claim", new JSONObject().put("guest_token", pending.getString("token")));
        JSONArray files = pending.getJSONArray("files");
        for (int i = 0; i < files.length(); i++) state.getJSONObject("owners").put(files.getString(i), userId());
        writeJson(stateFile(), state);
        File targetDir = new File(profile(), "songs"); if (!targetDir.isDirectory() && !targetDir.mkdirs()) throw new IllegalStateException("无法创建账号曲库");
        for (int i = 0; i < files.length(); i++) {
            String name = files.getString(i);
            if (!name.matches("[a-f0-9-]+\\.json")) throw new IllegalArgumentException("游客曲目标识无效");
            File source = new File(context.getFilesDir(), "songs/" + name), target = new File(targetDir, name);
            if (source.isFile() && !target.exists()) writeJson(target, new JSONObject(new String(Files.readAllBytes(source.toPath()), StandardCharsets.UTF_8)));
        }
        state.remove("pending"); writeJson(stateFile(), state); return files.length();
    }
    public String sync() throws Exception {
        if (!signedIn()) throw new IllegalStateException("云端同步需要登录；游客可继续使用本地曲库");
        JSONArray remote = request("GET", "/library/songs", null).getJSONArray("songs");
        Set<String> remoteIds = new HashSet<>(), localIds = new HashSet<>();
        for (int i = 0; i < remote.length(); i++) remoteIds.add(remote.getJSONObject(i).getString("id"));
        Library library = new Library(context); int uploaded = 0, downloaded = 0;
        for (Library.Entry entry : library.entries()) {
            if (entry.id.equals("demo")) continue;
            Score score = library.read(entry.id); String id = CloudScore.id(score); localIds.add(id);
            if (!remoteIds.contains(id)) {request("POST", "/library/songs", CloudScore.encode(score)); remoteIds.add(id); uploaded++;}
        }
        for (int i = 0; i < remote.length(); i++) {
            JSONObject entry = remote.getJSONObject(i); String id = entry.getString("id");
            if (localIds.contains(id)) continue;
            if (!id.matches("[a-f0-9]{64}")) throw new IllegalArgumentException("云端曲目标识无效");
            Score score = CloudScore.decode(request("GET", "/library/songs/" + id, null));
            if (!CloudScore.id(score).equals(id)) throw new IllegalArgumentException("云端曲谱内容校验失败");
            library.saveCloud(id, score); downloaded++;
        }
        return "同步完成：上传 " + uploaded + " 首，下载 " + downloaded + " 首";
    }
}
