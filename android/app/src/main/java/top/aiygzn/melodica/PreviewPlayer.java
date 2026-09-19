package top.aiygzn.melodica;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.os.Handler;
import android.os.Looper;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/** 本机合成试听；从不调用无障碍服务或发送游戏触摸。 */
final class PreviewPlayer {
    interface Listener { void progress(long position, boolean playing, String error); }
    private static final int RATE = 22050;
    private final AudioManager manager;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Listener listener;
    private final AudioFocusRequest focus;
    private volatile AudioTrack audio;
    private volatile long generation;
    private Future<?> task;
    private boolean playing;
    PreviewPlayer(Context context, Listener listener) {
        this.listener = listener; manager = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        focus = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
            .setAudioAttributes(attributes()).setOnAudioFocusChangeListener(change -> { if (change < 0) stop(); }, handler).build();
    }
    private static AudioAttributes attributes() { return new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build(); }
    boolean playing() { return playing; }
    void play(Score score, double speed, int transpose, int base) {
        stop();
        if (manager.requestAudioFocus(focus) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) { listener.progress(0, false, "音频被其他应用占用，请稍后重试"); return; }
        long token = ++generation; playing = true; listener.progress(0, true, "");
        task = worker.submit(() -> synthesize(score, speed, transpose, base, token));
    }
    private void synthesize(Score score, double speed, int transpose, int base, long token) {
        AudioTrack track = null;
        try {
            double[] frequencies = new double[score.notes.size()];
            for (int i = 0; i < frequencies.length; i++) frequencies[i] = 440 * Math.pow(2, (Score.map(score.notes.get(i).pitch + transpose, base, true, true, true).pitch - 69) / 12.0);
            int size = Math.max(2048, AudioTrack.getMinBufferSize(RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT));
            track = new AudioTrack.Builder().setAudioAttributes(attributes()).setAudioFormat(new AudioFormat.Builder().setSampleRate(RATE).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                .setBufferSizeInBytes(size).setTransferMode(AudioTrack.MODE_STREAM).build();
            if (token != generation) return;
            audio = track; track.play(); short[] buffer = new short[512]; long frame = 0, total = (long) Math.ceil(score.duration / speed * RATE / 1000); int index = 0;
            long lastReport = -100;
            while (frame < total && token == generation && !Thread.currentThread().isInterrupted()) {
                int count = (int) Math.min(buffer.length, total - frame);
                for (int j = 0; j < count; j++) {
                    double time = (frame + j) * 1000.0 / RATE * speed;
                    while (index + 1 < score.notes.size() && score.notes.get(index).end <= time) index++;
                    Score.Note note = score.notes.get(index); double value = 0, end = ScoreTools.releaseAt(note);
                    if (time >= note.start && time < end) {
                        double elapsed = (time - note.start) / speed / 1000, phase = 2 * Math.PI * frequencies[index] * elapsed;
                        double envelope = Math.min(1, elapsed / .008) * Math.min(1, (end - time) / speed / 8);
                        value = (Math.sin(phase) + .22 * Math.sin(2 * phase) + .12 * Math.sin(3 * phase)) * envelope;
                    }
                    buffer[j] = (short) Math.round(value * 6500);
                }
                int written = 0;
                while (written < count && token == generation) { int n = track.write(buffer, written, count - written, AudioTrack.WRITE_BLOCKING); if (n < 0) throw new IllegalStateException("音频输出中断"); written += n; }
                frame += written; long position = Math.min(score.duration, Math.round((track.getPlaybackHeadPosition() & 0xffffffffL) * 1000.0 / RATE * speed));
                if (position - lastReport >= 60) { lastReport = position; handler.post(() -> { if (token == generation) listener.progress(position, true, ""); }); }
            }
            // 等待已写入的尾音播放完，进度按音频实际消费位置报告。
            while (token == generation && !Thread.currentThread().isInterrupted() && (track.getPlaybackHeadPosition() & 0xffffffffL) < total) Thread.sleep(20);
            handler.post(() -> { if (token == generation) { playing = false; manager.abandonAudioFocusRequest(focus); listener.progress(score.duration, false, ""); } });
        } catch (Exception error) {
            handler.post(() -> { if (token == generation) { playing = false; manager.abandonAudioFocusRequest(focus); listener.progress(0, false, "试听失败：" + ErrorMessages.userMessage(error, "请检查音频输出后重试")); } });
        } finally {
            if (audio == track) audio = null;
            if (track != null) { try { track.stop(); } catch (IllegalStateException ignored) { } track.release(); }
        }
    }
    void stop() {
        generation++; playing = false;
        if (task != null) task.cancel(true);
        AudioTrack current = audio;
        if (current != null) try { current.pause(); current.flush(); } catch (IllegalStateException ignored) { }
        manager.abandonAudioFocusRequest(focus); listener.progress(0, false, "");
    }
    void close() { stop(); worker.shutdownNow(); }
}
