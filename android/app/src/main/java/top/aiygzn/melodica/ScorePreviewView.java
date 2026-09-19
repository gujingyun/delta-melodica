package top.aiygzn.melodica;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.view.MotionEvent;
import android.view.View;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.List;
import java.util.TreeMap;
import java.util.regex.Matcher;

/** 分页谱面，每个音符保留原文坐标；试听反复时回到同一个谱面音符。 */
final class ScorePreviewView extends View {
    interface Select { void select(int start, int end); }
    private static final int PAGE_SIZE = 128;
    private static final class Glyph {
        int left, right, octave, lines; String degree, accidental, dots, tail, lyric = "", before = ""; RectF bounds;
    }
    private final List<Glyph> glyphs = new ArrayList<>();
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Select select;
    private String heading = "";
    private int page, columns = 4, playing = -1;
    ScorePreviewView(Context context, Select select) { super(context); this.select = select; setBackground(Ui.background(context, Ui.CARD, 12)); setContentDescription("简谱预览，点选音符可定位到原文"); }
    int pages() { return Math.max(1, (glyphs.size() + PAGE_SIZE - 1) / PAGE_SIZE); }
    int page() { return page; }
    void clear() { glyphs.clear(); playing = -1; heading = "请修正谱文后预览"; page(0); }
    void page(int value) { page = Math.max(0, Math.min(pages() - 1, value)); requestLayout(); invalidate(); }
    void show(String text, Jianpu.Result parsed, boolean source) {
        glyphs.clear(); TreeMap<Integer, Jianpu.Span> unique = new TreeMap<>(); for (Jianpu.Span span : parsed.spans) unique.putIfAbsent(span.left, span);
        List<String> lyrics = new ArrayList<>();
        if (source) for (String line : text.split("\n")) if (line.trim().startsWith("L:")) {
            try { lyrics.addAll(Jianpu.syllables(Normalizer.normalize(line.trim().substring(2), Normalizer.Form.NFKC))); } catch (IllegalArgumentException ignored) { }
        }
        int lyricIndex = 0, previous = 0;
        for (Jianpu.Span span : unique.values()) {
            String token = Normalizer.normalize(text.substring(span.left, span.right), Normalizer.Form.NFKC); Matcher match = (source ? Jianpu.NOTE : Jianpu.PRECISE).matcher(token);
            if (!match.matches()) continue; Glyph g = new Glyph(); g.left = span.left; g.right = span.right;
            g.degree = match.group(source ? 2 : 3); g.accidental = match.group(source ? 1 : 2); if (g.accidental == null) g.accidental = "";
            String octave = match.group(source ? 3 : 1); g.octave = source ? Jianpu.count(octave, '\'') - Jianpu.count(octave, ',') : Jianpu.count(octave, '+') - Jianpu.count(octave, '-');
            String length = match.group(4);
            g.lines = source ? 2 * Jianpu.count(length, '=') + Jianpu.count(length, '_') : 0; g.dots = source ? match.group(5) : "";
            g.tail = source ? length.startsWith("-") ? length : "" : length == null ? "" : ":" + length;
            String between = text.substring(previous, span.left); int lineEnd = between.lastIndexOf('\n'); if (lineEnd >= 0) between = between.substring(lineEnd + 1);
            g.before = between.replaceAll("[^|:()~\\[12]", ""); previous = span.right;
            if (!g.degree.equals("0") && !g.degree.equals("-")) { if (lyricIndex < lyrics.size()) g.lyric = lyrics.get(lyricIndex).replace("\"", ""); lyricIndex++; }
            if (g.lyric.equals("_") || g.lyric.equals("*")) g.lyric = "";
            glyphs.add(g);
        }
        Matcher key = Jianpu.KEY.matcher(Normalizer.normalize(text, Normalizer.Form.NFKC));
        heading = (source && key.find() ? "1 = " + key.group(1) + key.group(2) + key.group(3) : source ? "1 = C4（缺省）" : "精确音符 · : 后为拍数");
        playing = -1; page(Math.min(page, pages() - 1));
    }
    void mark(Jianpu.Span span) {
        int next = -1;
        if (span != null) for (int i = 0; i < glyphs.size(); i++) if (glyphs.get(i).left == span.left && glyphs.get(i).right == span.right) { next = i; break; }
        if (playing == next) return; playing = next;
        if (next >= 0) { if (page != next / PAGE_SIZE) page(next / PAGE_SIZE); post(() -> { if (playing >= 0 && glyphs.get(playing).bounds != null) { Rect rect = new Rect(); glyphs.get(playing).bounds.roundOut(rect); requestRectangleOnScreen(rect, false); } }); }
        invalidate();
    }
    private int dp(float v) { return Ui.dp(getContext(), v); }
    @Override protected void onMeasure(int width, int height) {
        int available = MeasureSpec.getSize(width); columns = Math.max(2, (available - dp(24)) / dp(62));
        int visible = Math.max(0, Math.min(PAGE_SIZE, glyphs.size() - page * PAGE_SIZE));
        setMeasuredDimension(available, dp(58 + 100 * ((visible + columns - 1) / columns)));
    }
    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas); paint.setColor(Ui.MUTED); paint.setTextSize(dp(12)); paint.setTextAlign(Paint.Align.LEFT); canvas.drawText(heading, dp(14), dp(26), paint);
        float width = (getWidth() - dp(24)) / (float) columns;
        for (int i = page * PAGE_SIZE; i < Math.min(glyphs.size(), (page + 1) * PAGE_SIZE); i++) {
            Glyph g = glyphs.get(i); int local = i % PAGE_SIZE; float x = dp(12) + local % columns * width, y = dp(42 + local / columns * 100);
            g.bounds = new RectF(x, y, x + width - dp(2), y + dp(96));
            paint.setColor(i == playing ? 0xff295b47 : Ui.CARD); canvas.drawRoundRect(g.bounds, dp(8), dp(8), paint);
            paint.setColor(i == playing ? Ui.ACCENT : Ui.TEXT); paint.setTextSize(dp(27)); paint.setTypeface(android.graphics.Typeface.DEFAULT_BOLD); paint.setTextAlign(Paint.Align.CENTER);
            canvas.drawText(g.degree, x + width / 2, y + dp(38), paint); paint.setTypeface(android.graphics.Typeface.DEFAULT);
            paint.setTextSize(dp(12)); canvas.drawText(g.accidental, x + width / 2 - dp(15), y + dp(24), paint);
            canvas.drawText(g.dots, x + width / 2 + dp(16), y + dp(38), paint);
            for (int dot = 0; dot < Math.min(5, Math.abs(g.octave)); dot++) canvas.drawCircle(x + width / 2, y + dp(g.octave > 0 ? 12 - dot * 4 : 53 + Math.min(g.lines, 3) * 4 + dot * 4), dp(1.3f), paint);
            for (int line = 0; line < Math.min(g.lines, 5); line++) canvas.drawLine(x + width / 2 - dp(10), y + dp(44 + line * 4), x + width / 2 + dp(10), y + dp(44 + line * 4), paint);
            paint.setColor(Ui.MUTED); paint.setTextSize(dp(10)); canvas.drawText(shorten(g.tail, 10), x + width / 2, y + dp(74), paint);
            paint.setTextSize(dp(11)); canvas.drawText(shorten(g.lyric, 5), x + width / 2, y + dp(90), paint);
            paint.setTextSize(dp(10)); paint.setTextAlign(Paint.Align.LEFT); canvas.drawText(shorten(g.before, 6), x, y + dp(8), paint);
        }
    }
    private String shorten(String text, int max) { return text.length() <= max ? text : text.substring(0, max - 1) + "…"; }
    @Override public boolean onTouchEvent(MotionEvent event) {
        if (event.getAction() == MotionEvent.ACTION_UP) {
            for (int i = page * PAGE_SIZE; i < Math.min(glyphs.size(), (page + 1) * PAGE_SIZE); i++) {
                Glyph g = glyphs.get(i); if (g.bounds != null && g.bounds.contains(event.getX(), event.getY())) { select.select(g.left, g.right); performClick(); return true; }
            }
        }
        return true;
    }
    @Override public boolean performClick() { super.performClick(); return true; }
}
