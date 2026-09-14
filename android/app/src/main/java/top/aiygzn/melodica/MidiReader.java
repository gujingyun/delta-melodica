package top.aiygzn.melodica;

import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** 读取标准 PPQ MIDI 0／1，跨音轨合并速度表，过滤打击乐。 */
public final class MidiReader {
    private static final class Event {
        long tick; int order, track, channel, pitch, value, type;
        Event(long tick, int order, int track, int channel, int pitch, int value, int type) {
            this.tick = tick; this.order = order; this.track = track; this.channel = channel;
            this.pitch = pitch; this.value = value; this.type = type;
        }
    }
    private static int vlq(DataInputStream in) throws IOException {
        int result = 0;
        for (int i = 0; i < 4; i++) {
            int value = in.readUnsignedByte(); result = (result << 7) | (value & 127);
            if ((value & 128) == 0) return result;
        }
        throw new IOException("MIDI 可变长数字超过 4 字节");
    }
    public static Score read(byte[] bytes, String title) throws IOException {
        if (bytes.length > 10 * 1024 * 1024) throw new IOException("MIDI 不能超过 10 MB");
        DataInputStream in = new DataInputStream(new ByteArrayInputStream(bytes));
        if (in.readInt() != 0x4d546864) throw new IOException("文件不是标准 MIDI");
        int header = in.readInt();
        if (header < 6 || header > in.available()) throw new IOException("MIDI 文件头损坏");
        int format = in.readUnsignedShort(), tracks = in.readUnsignedShort(), ppq = in.readUnsignedShort();
        if (format > 1 || ppq == 0 || (ppq & 0x8000) != 0 || tracks < 1 || tracks > 256 || (format == 0 && tracks != 1))
            throw new IOException("仅支持 PPQ MIDI 0／1，最多 256 条音轨");
        in.skipBytes(header - 6);
        List<Event> events = new ArrayList<>();
        int order = 0;
        for (int track = 0; track < tracks; track++) {
            if (in.readInt() != 0x4d54726b) throw new IOException("MIDI 缺少音轨块");
            int length = in.readInt();
            if (length < 0 || length > in.available()) throw new IOException("MIDI 音轨长度损坏");
            byte[] chunk = new byte[length];
            in.readFully(chunk);
            DataInputStream data = new DataInputStream(new ByteArrayInputStream(chunk));
            long tick = 0; int running = 0;
            while (data.available() > 0) {
                if (++order > 500000) throw new IOException("MIDI 事件过多");
                tick += vlq(data);
                int status = data.readUnsignedByte(), first = -1;
                if (status < 128) {
                    if (running == 0) throw new IOException("MIDI 连续状态损坏");
                    first = status; status = running;
                }
                if (status == 0xff) {
                    running = 0;
                    int type = data.readUnsignedByte(), size = vlq(data);
                    if (size > data.available()) throw new IOException("MIDI 元事件截断");
                    if (type == 0x51) {
                        if (size != 3) throw new IOException("MIDI 速度事件损坏");
                        int tempo = (data.readUnsignedByte() << 16) | (data.readUnsignedByte() << 8) | data.readUnsignedByte();
                        if (tempo == 0) throw new IOException("MIDI 速度不能为零");
                        events.add(new Event(tick, order, track, 0, 0, tempo, 0));
                    } else data.skipBytes(size);
                    if (type == 0x2f) break;
                } else if (status == 0xf0 || status == 0xf7) {
                    running = 0; int size = vlq(data);
                    if (size > data.available()) throw new IOException("MIDI 系统事件截断");
                    data.skipBytes(size);
                } else if (status >= 0x80 && status < 0xf0) {
                    running = status;
                    int type = status >> 4, a = first < 0 ? data.readUnsignedByte() : first;
                    int b = (type == 0xc || type == 0xd) ? 0 : data.readUnsignedByte();
                    if (a > 127 || b > 127) throw new IOException("MIDI 数据字节损坏");
                    if ((type == 8 || type == 9) && (status & 15) != 9)
                        events.add(new Event(tick, order, track, status & 15, a, b, type == 9 && b > 0 ? 1 : 2));
                } else throw new IOException("不支持的 MIDI 系统消息");
            }
            events.add(new Event(tick, order++, track, 0, 0, 0, 3));
        }
        events.sort(Comparator.comparingLong((Event e) -> e.tick).thenComparingInt(e -> e.order));
        Map<Integer, ArrayDeque<Long>> held = new HashMap<>();
        List<Score.Note> notes = new ArrayList<>();
        long lastTick = 0; double ms = 0; int tempo = 500000;
        for (Event e : events) {
            ms += (e.tick - lastTick) * (double) tempo / ppq / 1000; lastTick = e.tick;
            if (ms > 1800000) throw new IOException("MIDI 不能超过 30 分钟");
            long now = Math.round(ms);
            int key = e.track * 2048 + e.channel * 128 + e.pitch;
            if (e.type == 0) tempo = e.value;
            else if (e.type == 1) held.computeIfAbsent(key, k -> new ArrayDeque<>()).add(now);
            else if (e.type == 2 && held.containsKey(key) && !held.get(key).isEmpty()) {
                long start = held.get(key).removeFirst();
                if (now > start) notes.add(new Score.Note(start, now, e.pitch, e.track));
            } else if (e.type == 3) {
                // 缺失 note-off 的音符只延续到所属音轨结束。
                for (var entry : held.entrySet()) if (entry.getKey() / 2048 == e.track) {
                    while (!entry.getValue().isEmpty()) {
                        long start = entry.getValue().removeFirst();
                        if (now > start) notes.add(new Score.Note(start, now, entry.getKey() % 128, e.track));
                    }
                }
            }
            if (notes.size() > 30000) throw new IOException("MIDI 音符超过 30000 个");
        }
        return new Score(title, notes, Math.round(ms));
    }
}
