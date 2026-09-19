package top.aiygzn.melodica;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.PointF;

/** 校准数据只保存在本机；旋转或分辨率变化后要求重新校准。 */
public final class Settings {
    private final SharedPreferences prefs;
    private final String profile;
    public Settings(Context context) {
        prefs = context.getSharedPreferences("melodica", Context.MODE_PRIVATE);
        Account account = new Account(context); profile = account.signedIn() ? "account:" + account.userId() + ":" : "";
    }
    private String songKey(String key) { return profile + "song:" + selected() + ":" + key; }
    public int base() { return prefs.getInt("base", 60); }
    public void base(int value) { prefs.edit().putInt("base", value).apply(); }
    public boolean fastSwitch() { return prefs.getBoolean("fastSwitch", false); }
    public void fastSwitch(boolean value) { prefs.edit().putBoolean("fastSwitch", value).apply(); }
    public int transpose() { return prefs.getInt(songKey("transpose"), profile.isEmpty() ? prefs.getInt("transpose", 0) : 0); }
    public void transpose(int value) { prefs.edit().putInt(songKey("transpose"), value).apply(); }
    public double speed() { return prefs.getFloat(songKey("speed"), profile.isEmpty() ? prefs.getFloat("speed", 1) : 1); }
    public void speed(float value) { prefs.edit().putFloat(songKey("speed"), value).apply(); }
    public int track() { return prefs.getInt(songKey("track"), -2); }
    public void track(int value) { prefs.edit().putInt(songKey("track"), value).apply(); }
    public boolean piano(boolean fallback) { return prefs.getBoolean(songKey("piano"), fallback); }
    public void setPiano(boolean value) { prefs.edit().putBoolean(songKey("piano"), value).apply(); }
    public java.util.List<ScoreTools.Segment> segments() {
        java.util.List<ScoreTools.Segment> result = new java.util.ArrayList<>();
        try {
            org.json.JSONArray data = new org.json.JSONArray(prefs.getString(songKey("segments"), "[]"));
            for (int i = 0; i < data.length(); i++) { org.json.JSONArray item = data.getJSONArray(i); result.add(new ScoreTools.Segment(item.getLong(0), item.getLong(1), item.getInt(2))); }
        } catch (Exception e) { throw new IllegalArgumentException("片段设置损坏，请清空后重新设置", e); }
        return result;
    }
    public void segments(java.util.List<ScoreTools.Segment> segments) {
        org.json.JSONArray data = new org.json.JSONArray();
        for (ScoreTools.Segment segment : segments) data.put(new org.json.JSONArray().put(segment.start).put(segment.end).put(segment.repeat));
        prefs.edit().putString(songKey("segments"), data.toString()).apply();
    }
    public Score prepare(Score score, boolean fallback) { return ScoreTools.arrange(ScoreTools.melody(score, track(), piano(fallback)), segments()); }
    static void inherit(Context context, String user, String id) {
        SharedPreferences preferences = context.getSharedPreferences("melodica", Context.MODE_PRIVATE);
        String source = "song:" + id + ":", target = "account:" + user + ":" + source;
        SharedPreferences.Editor editor = preferences.edit();
        for (java.util.Map.Entry<String, ?> entry : preferences.getAll().entrySet()) {
            if (!entry.getKey().startsWith(source)) continue;
            String key = target + entry.getKey().substring(source.length()); if (preferences.contains(key)) continue;
            Object value = entry.getValue();
            if (value instanceof String) editor.putString(key, (String) value); else if (value instanceof Float) editor.putFloat(key, (Float) value);
            else if (value instanceof Integer) editor.putInt(key, (Integer) value); else if (value instanceof Boolean) editor.putBoolean(key, (Boolean) value);
        }
        editor.apply();
    }
    public String target() { return prefs.getString("target", ""); }
    public String selected() { return prefs.getString(profile + "selected", "demo"); }
    public void selected(String value) { prefs.edit().putString(profile + "selected", value).apply(); }
    public String editor() { return prefs.getString("editor", Score.STAR); }
    public void editor(String value) { prefs.edit().putString("editor", value).apply(); }
    public int width() { return prefs.getInt("width", 0); }
    public int height() { return prefs.getInt("height", 0); }
    public int rotation() { return prefs.getInt("rotation", -1); }
    public boolean calibrated() {
        if (prefs.getInt("calibrationVersion", 0) != 2) return false;
        for (int i = 0; i < Score.LABELS.length; i++) {
            PointF p = point(i);
            if (p == null || !Float.isFinite(p.x) || !Float.isFinite(p.y) || p.x >= width() || p.y >= height()) return false;
        }
        return true;
    }
    public PointF point(int index) {
        float x = prefs.getFloat("x" + index, -1), y = prefs.getFloat("y" + index, -1);
        return x < 0 || y < 0 ? null : new PointF(x, y);
    }
    public void calibrate(String target, int width, int height, int rotation, PointF[] points) {
        if (points.length != Score.LABELS.length) throw new IllegalArgumentException("需要校准全部 12 个位置");
        for (PointF p : points) if (p == null || !Float.isFinite(p.x) || !Float.isFinite(p.y) || p.x < 0 || p.y < 0 || p.x >= width || p.y >= height)
            throw new IllegalArgumentException("校准位置无效");
        SharedPreferences.Editor edit = prefs.edit().putInt("calibrationVersion", 2).putString("target", target).putInt("width", width).putInt("height", height).putInt("rotation", rotation);
        for (int i = 0; i < Score.LABELS.length; i++) {
            edit.remove("x" + i).remove("y" + i);
            if (points[i] != null) edit.putFloat("x" + i, points[i].x).putFloat("y" + i, points[i].y);
        }
        edit.apply();
    }
    public Score.Fingering fingering(int pitch) { return Score.map(pitch + transpose(), base(), true, true, true); }
}
