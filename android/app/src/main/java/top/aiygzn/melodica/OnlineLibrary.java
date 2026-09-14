package top.aiygzn.melodica;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InterruptedIOException;
import java.net.HttpURLConnection;
import java.net.URI;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/** 官网公开目录及 MIDI／JSON 曲谱下载；不发送本地曲谱或设置。 */
public final class OnlineLibrary {
    public static final String CATALOG_URL = "https://aiygzn.top/melodica/songs.json";
    static final int MAX_CATALOG_BYTES = 1024 * 1024, MAX_SONG_BYTES = 10 * 1024 * 1024;
    public static final class Song {
        public final String id, title, artist, description, url, sha256, format;
        public final long size;
        Song(String id, String title, String artist, String description, String url, long size, String sha256) {
            this(id, title, artist, description, url, size, sha256, "midi");
        }
        Song(String id, String title, String artist, String description, String url, long size, String sha256, String format) {
            this.id = id; this.title = title; this.artist = artist; this.description = description; this.url = url; this.size = size; this.sha256 = sha256;
            this.format = format;
        }
    }
    private OnlineLibrary() { }
    public static List<Song> fetchCatalog() throws Exception { return parseCatalog(fetch(CATALOG_URL, MAX_CATALOG_BYTES)); }
    public static List<Song> parseCatalog(byte[] bytes) throws Exception {
        if (bytes.length > MAX_CATALOG_BYTES) throw new IOException("线上目录超过 1 MB");
        JSONArray songs = new JSONObject(new String(bytes, StandardCharsets.UTF_8)).getJSONArray("songs");
        if (songs.length() > 500) throw new IOException("线上目录最多支持 500 首曲目");
        List<Song> result = new ArrayList<>(); Set<String> ids = new HashSet<>();
        for (int i = 0; i < songs.length(); i++) {
            JSONObject item = songs.getJSONObject(i);
            String id = text(item, "id", 80, true);
            if (!id.matches("[A-Za-z0-9][A-Za-z0-9._-]*") || !ids.add(id)) throw new IOException("目录曲目标识无效或重复");
            String title = text(item, "title", 100, true), artist = text(item, "artist", 100, false), description = text(item, "description", 300, false);
            String url = checkedUrl(URI.create(CATALOG_URL).resolve(text(item, "url", 500, true)).toString()).toString();
            String format = item.isNull("format") ? "midi" : text(item, "format", 10, true);
            if (!format.equals("midi") && !format.equals("score")) throw new IOException("目录曲谱格式不支持：" + format);
            long size = -1;
            if (!item.isNull("size")) {
                Object value = item.get("size");
                if (!(value instanceof Integer) && !(value instanceof Long)) throw new IOException("目录文件大小无效");
                size = ((Number) value).longValue();
                if (size <= 0 || size > MAX_SONG_BYTES) throw new IOException("目录文件大小无效");
            }
            String hash = text(item, "sha256", 64, false).toLowerCase(Locale.ROOT);
            if (!item.isNull("sha256") && !hash.matches("[a-f0-9]{64}")) throw new IOException("目录 SHA-256 无效");
            result.add(new Song(id, title, artist, description, url, size, hash, format));
        }
        return result;
    }
    private static String text(JSONObject item, String key, int max, boolean required) throws Exception {
        if (!required && item.isNull(key)) return "";
        Object value = item.get(key);
        if (!(value instanceof String)) throw new IOException("目录字段「" + key + "」需为文本");
        String result = ((String) value).trim();
        if ((required && result.isEmpty()) || result.length() > max) throw new IOException("目录字段「" + key + "」长度无效");
        for (int i = 0; i < result.length(); i++) if (result.charAt(i) < 32) throw new IOException("目录字段包含无效字符");
        return result;
    }
    public static List<Song> search(List<Song> songs, String query) {
        String needle = query.trim().toLowerCase(Locale.ROOT); List<Song> result = new ArrayList<>();
        for (Song song : songs) if ((song.title + " " + song.artist).toLowerCase(Locale.ROOT).contains(needle)) result.add(song);
        return result;
    }
    public static Score download(Song song) throws Exception { return decode(song, fetch(song.url, MAX_SONG_BYTES)); }
    static Score decode(Song song, byte[] bytes) throws Exception {
        checkCancelled();
        if (bytes.length > MAX_SONG_BYTES || (song.size >= 0 && bytes.length != song.size)) throw new IOException("曲谱文件大小校验失败");
        if (!song.sha256.isEmpty() && !digest(bytes).equalsIgnoreCase(song.sha256)) throw new IOException("曲谱文件 SHA-256 校验失败");
        if (song.format.equals("score")) {
            Score score = CloudScore.decode(new JSONObject(new String(bytes, StandardCharsets.UTF_8)));
            return new Score(song.title, score.notes, score.duration);
        }
        if (!song.format.equals("midi")) throw new IOException("不支持此曲谱格式");
        return MidiReader.read(bytes, song.title);
    }
    static String digest(byte[] bytes) throws Exception {
        StringBuilder result = new StringBuilder();
        for (byte b : MessageDigest.getInstance("SHA-256").digest(bytes)) result.append(String.format(Locale.ROOT, "%02x", b & 255));
        return result.toString();
    }
    static URI checkedUrl(String value) throws IOException {
        try {
            URI url = URI.create(value);
            if (!"https".equalsIgnoreCase(url.getScheme()) || url.getHost() == null || url.getUserInfo() != null || url.getFragment() != null)
                throw new IllegalArgumentException();
            return url;
        } catch (IllegalArgumentException e) { throw new IOException("下载地址必须为有效的 HTTPS 地址"); }
    }
    static void checkCancelled() throws InterruptedIOException {
        if (Thread.currentThread().isInterrupted()) throw new InterruptedIOException("操作已取消");
    }
    static byte[] readLimited(InputStream input, int maximum, long deadline) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buffer = new byte[8192]; int count;
        while (true) {
            checkCancelled();
            if (System.nanoTime() >= deadline) throw new IOException("网络请求超时，请重试");
            count = input.read(buffer);
            if (count < 0) break;
            if (out.size() + count > maximum) throw new IOException("下载文件超出大小限制");
            out.write(buffer, 0, count);
        }
        checkCancelled(); return out.toByteArray();
    }
    private static byte[] fetch(String address, int maximum) throws IOException {
        URI url = checkedUrl(address); long deadline = System.nanoTime() + 30_000_000_000L;
        for (int redirect = 0; redirect <= 3; redirect++) {
            checkCancelled();
            if (System.nanoTime() >= deadline) throw new IOException("网络请求超时，请重试");
            HttpURLConnection connection = (HttpURLConnection) url.toURL().openConnection();
            connection.setConnectTimeout(8000); connection.setReadTimeout(10000); connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty("User-Agent", "DeltaMelodicaAndroid/" + BuildConfig.VERSION_NAME); connection.setRequestProperty("Accept-Encoding", "identity");
            try {
                int code = connection.getResponseCode();
                if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308) {
                    String location = connection.getHeaderField("Location");
                    if (location == null || redirect == 3) throw new IOException("服务器重定向无效");
                    try { url = checkedUrl(url.resolve(location).toString()); }
                    catch (IllegalArgumentException e) { throw new IOException("服务器重定向无效", e); }
                    continue;
                }
                if (code != 200) throw new IOException("服务器返回 HTTP " + code);
                if (connection.getContentLengthLong() > maximum) throw new IOException("下载文件超出大小限制");
                try (InputStream input = connection.getInputStream()) { return readLimited(input, maximum, deadline); }
            } finally { connection.disconnect(); }
        }
        throw new IOException("服务器重定向次数过多");
    }
}
