package top.aiygzn.melodica;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.PointF;

/** 校准数据只保存在本机；旋转或分辨率变化后要求重新校准。 */
public final class Settings {
    private final SharedPreferences prefs;
    public Settings(Context context) { prefs = context.getSharedPreferences("melodica", Context.MODE_PRIVATE); }
    public boolean modifier(int index) { return prefs.getBoolean("modifier" + index, false); }
    public void modifier(int index, boolean value) { prefs.edit().putBoolean("modifier" + index, value).apply(); }
    public int base() { return prefs.getInt("base", 60); }
    public void base(int value) { prefs.edit().putInt("base", value).apply(); }
    public int transpose() { return prefs.getInt("transpose", 0); }
    public void transpose(int value) { prefs.edit().putInt("transpose", value).apply(); }
    public double speed() { return prefs.getFloat("speed", 1); }
    public void speed(float value) { prefs.edit().putFloat("speed", value).apply(); }
    public String target() { return prefs.getString("target", ""); }
    public String selected() { return prefs.getString("selected", "demo"); }
    public void selected(String value) { prefs.edit().putString("selected", value).apply(); }
    public String editor() { return prefs.getString("editor", Score.STAR); }
    public void editor(String value) { prefs.edit().putString("editor", value).apply(); }
    public int width() { return prefs.getInt("width", 0); }
    public int height() { return prefs.getInt("height", 0); }
    public int rotation() { return prefs.getInt("rotation", -1); }
    public PointF point(int index) {
        float x = prefs.getFloat("x" + index, -1), y = prefs.getFloat("y" + index, -1);
        return x < 0 || y < 0 ? null : new PointF(x, y);
    }
    public void calibrate(String target, int width, int height, int rotation, PointF[] points) {
        SharedPreferences.Editor edit = prefs.edit().putString("target", target).putInt("width", width).putInt("height", height).putInt("rotation", rotation);
        for (int i = 0; i < 11; i++) {
            edit.remove("x" + i).remove("y" + i);
            if (points[i] != null) edit.putFloat("x" + i, points[i].x).putFloat("y" + i, points[i].y);
        }
        edit.apply();
    }
    public Score.Fingering fingering(int pitch) { return Score.map(pitch + transpose(), base(), modifier(8), modifier(9), modifier(10)); }
}
