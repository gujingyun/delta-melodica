package top.aiygzn.melodica;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** 与 Windows 端保持一致的五来源公开简谱与 MIDI 搜索。 */
public final class ResourceSearch {
    public static final int MAX_PAGE_BYTES = 2 * 1024 * 1024;
    private static final String USER_AGENT = "DeltaMelodicaAndroid/" + BuildConfig.VERSION_NAME;
    private static final Pattern LINK = Pattern.compile("(?is)<a\\b([^>]*)>(.*?)</a\\s*>");
    private static final Pattern ATTRIBUTE = Pattern.compile("(?is)([a-zA-Z_:][-a-zA-Z0-9_:.]*)\\s*=\\s*(?:\\\"([^\\\"]*)\\\"|'([^']*)'|([^\\s>]+))");
    private static final Pattern ROW = Pattern.compile("(?is)<tr\\b[^>]*>(.*?)</tr\\s*>");
    private static final Pattern CELL = Pattern.compile("(?is)<td\\b[^>]*>(.*?)</td\\s*>");
    private static final Pattern JIANPU_NOTE = Pattern.compile("(?<![A-Za-z])([+-]?)([#b]?)([0-7])(?::(\\d+(?:/\\d+|\\.\\d+)?))?");

    public static final class Source {
        public final String id, label, baseUrl;
        private Source(String id, String label, String baseUrl) {
            this.id = id; this.label = label; this.baseUrl = baseUrl;
        }
        @Override public String toString() { return label; }
    }

    public static final List<Source> SOURCES = Collections.unmodifiableList(Arrays.asList(
        new Source("jianpu", "简谱空间", "https://jianpu.space/songList"),
        new Source("official", "官网曲库", OnlineLibrary.CATALOG_URL),
        new Source("bitmidi", "BitMidi", "https://bitmidi.com"),
        new Source("midiworld", "MidiWorld", "https://www.midiworld.com"),
        new Source("midishow", "MidiShow", "https://www.midishow.com")
    ));

    public static final class SearchSong {
        public final String source, title, artist, pageUrl, downloadUrl, sha256, format;
        public final long size;
        SearchSong(String source, String title, String pageUrl, String downloadUrl, String artist,
                   long size, String sha256, String format) {
            this.source = source; this.title = title; this.pageUrl = pageUrl; this.downloadUrl = downloadUrl;
            this.artist = artist; this.size = size; this.sha256 = sha256; this.format = format;
        }
        public boolean downloadable() { return !source.equals("midishow"); }
        public String key() { return source + "|" + (downloadUrl.isEmpty() ? pageUrl : downloadUrl); }
    }

    public static final class SearchPage {
        public final List<SearchSong> songs;
        public final boolean hasMore;
        SearchPage(List<SearchSong> songs, boolean hasMore) {
            this.songs = Collections.unmodifiableList(new ArrayList<>(songs)); this.hasMore = hasMore;
        }
    }

    public static final class SiteAccessException extends IOException {
        SiteAccessException(String message) { super(message); }
    }

    private ResourceSearch() { }

    public static Source source(String id) {
        for (Source source : SOURCES) if (source.id.equals(id)) return source;
        throw new IllegalArgumentException("资源来源不正确");
    }

    public static String sourceLabel(String id) { return source(id).label; }

    public static String searchUrl(String sourceId, String query, int page) {
        if (page < 1 || page > 1000) throw new IllegalArgumentException("资源页码不正确");
        String encoded;
        try { encoded = URLEncoder.encode(query, "UTF-8"); }
        catch (Exception error) { throw new IllegalStateException("系统不支持 UTF-8 编码", error); }
        if (sourceId.equals("jianpu")) return "https://jianpu.space/songList";
        if (sourceId.equals("official")) return OnlineLibrary.CATALOG_URL;
        if (sourceId.equals("bitmidi")) return "https://bitmidi.com/search?q=" + encoded + "&page=" + (page - 1);
        if (sourceId.equals("midiworld")) return "https://www.midiworld.com/search/" + (page > 1 ? page + "/" : "") + "?q=" + encoded;
        if (sourceId.equals("midishow")) return "https://www.midishow.com/search/result?q=" + encoded + "&page=" + page;
        throw new IllegalArgumentException("资源来源不正确");
    }

    public static SearchPage search(String sourceId, String query, int page) throws Exception {
        query = query == null ? "" : query.trim();
        if (query.isEmpty() || query.length() > 100) throw new IllegalArgumentException("请填写 1～100 个字符的曲名或作者");
        source(sourceId);
        if (sourceId.equals("jianpu")) return page == 1 ? searchJianpu(fetchText(searchUrl(sourceId, query, page)), query) : new SearchPage(Collections.emptyList(), false);
        if (sourceId.equals("official")) return page == 1 ? searchOfficial(query) : new SearchPage(Collections.emptyList(), false);
        String url = searchUrl(sourceId, query, page);
        return parseSearchPage(sourceId, fetchText(url), url, page);
    }

    private static SearchPage searchOfficial(String query) throws Exception {
        List<OnlineLibrary.Song> catalog = OnlineLibrary.fetchCatalog();
        List<SearchSong> songs = new ArrayList<>();
        String[] terms = simplify(query).toLowerCase(Locale.ROOT).split("\\s+");
        for (OnlineLibrary.Song song : catalog) {
            String haystack = simplify(song.title + " " + song.artist + " " + song.description).toLowerCase(Locale.ROOT);
            if (containsAll(haystack, terms)) songs.add(new SearchSong("official", song.title, "https://aiygzn.top/melodica/", song.url,
                song.artist, song.size, song.sha256, song.format));
        }
        return new SearchPage(songs, false);
    }

    static SearchPage searchJianpu(String html, String query) {
        List<SearchSong> songs = new ArrayList<>(); Set<String> seen = new HashSet<>(); int validRows = 0;
        String[] terms = simplify(query).toLowerCase(Locale.ROOT).split("\\s+");
        Matcher rows = ROW.matcher(html);
        while (rows.find()) {
            Matcher cells = CELL.matcher(rows.group(1)); List<String> values = new ArrayList<>(); String href = "";
            while (cells.find()) {
                String cell = cells.group(1); values.add(text(cell));
                if (href.isEmpty()) {
                    Matcher links = LINK.matcher(cell);
                    if (links.find()) href = attribute(links.group(1), "href");
                }
            }
            if (values.size() < 2 || href.isEmpty()) continue;
            String url = siteUrl("https://jianpu.space/songList", href);
            if (url.isEmpty() || !urlPath(url).matches("/songList/(?:\\d+|[a-f0-9]{24})")) continue;
            validRows++;
            String artist = values.get(1).equals("None") ? "" : values.get(1);
            if (containsAll(simplify(values.get(0) + " " + artist).toLowerCase(Locale.ROOT), terms) && seen.add(url))
                songs.add(new SearchSong("jianpu", values.get(0).substring(0, Math.min(100, values.get(0).length())), url, "", artist, -1, "", "jianpu"));
        }
        if (validRows == 0) throw new IllegalArgumentException("简谱空间未返回可识别的曲目目录，可能需要验证或页面结构已变化。");
        return new SearchPage(songs, false);
    }

    static SearchPage parseSearchPage(String source, String html, String url, int page) throws Exception {
        List<SearchSong> songs = new ArrayList<>(); Set<String> seen = new HashSet<>(); boolean hasMore = false;
        Matcher links = LINK.matcher(html);
        while (links.find()) {
            String href = attribute(links.group(1), "href");
            String target = siteUrl(url, href);
            if (target.isEmpty()) continue;
            String path = urlPath(target), title = "", download = "";
            if (path.contains("/search")) {
                int nextPage = pageNumber(target, source);
                if (nextPage > (source.equals("bitmidi") ? page - 1 : page)) hasMore = true;
            }
            String linkText = text(links.group(2));
            if (source.equals("bitmidi") && path.matches("/[^/]+-midi?")) title = firstNonEmpty(attribute(links.group(1), "title"), linkText);
            else if (source.equals("midiworld") && path.matches("/download/\\d+/?")) {
                title = firstNonEmpty(listPrefix(html, links.start()), linkText).replaceFirst("\\s+-$", "").trim(); download = target;
            } else if (source.equals("midishow") && path.matches("/midi/(?:\\d+\\.html|[^/]+-\\d+)")) title = firstNonEmpty(headingText(html, links.start()), attribute(links.group(1), "title"), linkText);
            title = title.replaceFirst("(?i)\\.(?:mid|midi)$", "").trim();
            if (!title.isEmpty() && seen.add(target)) songs.add(new SearchSong(source, limit(title, 180), download.isEmpty() ? target : url,
                download, "", -1, "", "midi"));
        }
        String lower = html.toLowerCase(Locale.ROOT);
        if (songs.isEmpty() && !containsAny(lower, "0 results", "no results", "found nothing", "共找到 0", "没有找到", "未找到"))
            throw new IllegalArgumentException("网站未返回可识别的结果，可能需要验证或页面结构已变化；可打开源站搜索。");
        return new SearchPage(songs, hasMore);
    }

    public static Score download(SearchSong song) throws Exception {
        if (!song.downloadable()) throw new IllegalArgumentException("MidiShow 需在源站按账号与积分规则下载，之后导入 MIDI。");
        if (song.source.equals("jianpu")) return downloadJianpu(song);
        String url = resolveDownload(song);
        byte[] bytes = fetch(url, song.format.equals("score") ? 2 * 1024 * 1024 : OnlineLibrary.MAX_SONG_BYTES);
        OnlineLibrary.Song onlineSong = new OnlineLibrary.Song("aggregate", song.title, song.artist, "", url, song.size, song.sha256, song.format.equals("score") ? "score" : "midi");
        return OnlineLibrary.decode(onlineSong, bytes);
    }

    private static Score downloadJianpu(SearchSong song) throws Exception {
        String html = fetchText(song.pageUrl); String block = jianpuBlock(html);
        if (block.isEmpty()) throw new IllegalArgumentException("未找到完整简谱文字；此页面可能需要验证或不支持直接导入。");
        String raw = textWithBreaks(block);
        String notation = extractJianpu(raw);
        if (notation.isEmpty()) throw new IllegalArgumentException("未找到可识别的简谱音符。");
        return Score.jianpu(notation, 120, song.title);
    }

    private static String jianpuBlock(String html) {
        Matcher start = Pattern.compile("(?is)<div\\b[^>]*\\bid\\s*=\\s*[\\\"']jianpuOut[\\\"'][^>]*>").matcher(html);
        if (!start.find()) return "";
        int depth = 1, position = start.end(); Matcher tags = Pattern.compile("(?is)</?div\\b[^>]*>").matcher(html);
        tags.region(position, html.length());
        while (tags.find()) {
            if (tags.group().startsWith("</")) depth--; else depth++;
            if (depth == 0) return html.substring(position, tags.start());
        }
        return "";
    }

    private static String extractJianpu(String raw) {
        StringBuilder notation = new StringBuilder();
        for (String line : Normalizer.normalize(raw, Normalizer.Form.NFKC).split("\\R")) {
            String lower = line.trim().toLowerCase(Locale.ROOT);
            if (lower.startsWith("bpm") || lower.startsWith("/key") || lower.startsWith("key(") || lower.startsWith("l:")) continue;
            Matcher notes = JIANPU_NOTE.matcher(line);
            while (notes.find()) {
                if (notation.length() > 0) notation.append(' ');
                notation.append(notes.group());
            }
        }
        return notation.toString();
    }

    private static String resolveDownload(SearchSong song) throws Exception {
        if (!song.downloadUrl.isEmpty()) return song.downloadUrl;
        if (!song.source.equals("bitmidi")) throw new IllegalArgumentException("未找到公开 MIDI 下载链接，请打开源站查看。");
        Matcher links = LINK.matcher(fetchText(song.pageUrl));
        while (links.find()) {
            String target = siteUrl(song.pageUrl, attribute(links.group(1), "href"));
            if (!target.isEmpty() && urlPath(target).matches("/uploads/[^/]+\\.midi?")) return target;
        }
        throw new IllegalArgumentException("未找到公开 MIDI 下载链接，请打开源站查看。");
    }

    private static String fetchText(String url) throws IOException {
        String html = new String(fetch(url, MAX_PAGE_BYTES), StandardCharsets.UTF_8);
        if (verificationPage(html)) throw new SiteAccessException("需要浏览器人机验证；请在源站完成验证、下载后导入。");
        return html;
    }

    private static boolean verificationPage(String html) {
        Matcher title = Pattern.compile("(?is)<title[^>]*>(.*?)</title>").matcher(html);
        String value = title.find() ? text(title.group(1)).toLowerCase(Locale.ROOT) : "";
        String lower = html.toLowerCase(Locale.ROOT);
        return (value.contains("just a moment") || value.contains("请稍候") || value.contains("attention required") || value.contains("checking your browser"))
            && (lower.contains("cf-chl-") || lower.contains("challenge-platform") || lower.contains("cloudflare"));
    }

    private static byte[] fetch(String address, int maximum) throws IOException {
        URI url = OnlineLibrary.checkedUrl(address); long deadline = System.nanoTime() + 30_000_000_000L;
        for (int redirect = 0; redirect <= 3; redirect++) {
            OnlineLibrary.checkCancelled();
            if (System.nanoTime() >= deadline) throw new IOException("网络请求超时，请重试");
            HttpURLConnection connection = (HttpURLConnection) url.toURL().openConnection();
            connection.setConnectTimeout(8000); connection.setReadTimeout(10000); connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty("User-Agent", USER_AGENT); connection.setRequestProperty("Accept", "text/html,application/json,*/*");
            try {
                int code = connection.getResponseCode();
                if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308) {
                    String location = connection.getHeaderField("Location");
                    if (location == null || redirect == 3) throw new IOException("服务器重定向无效");
                    url = OnlineLibrary.checkedUrl(url.resolve(location).toString()); continue;
                }
                if (code == 403 || code == 429) {
                    throw new SiteAccessException(code == 403 ? "网站拒绝后台访问；请在浏览器打开源站完成验证。" : "网站请求过于频繁，请稍后重试。");
                }
                if (code != 200) throw new IOException("服务器返回 HTTP " + code);
                if (connection.getContentLengthLong() > maximum) throw new IOException("下载文件超出大小限制");
                try (InputStream input = connection.getInputStream()) { return readLimited(input, maximum, deadline); }
            } finally { connection.disconnect(); }
        }
        throw new IOException("服务器重定向次数过多");
    }

    private static byte[] readLimited(InputStream input, int maximum, long deadline) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream(); byte[] buffer = new byte[8192];
        while (true) {
            OnlineLibrary.checkCancelled();
            if (System.nanoTime() >= deadline) throw new IOException("网络请求超时，请重试");
            int count = input.read(buffer); if (count < 0) break;
            if (out.size() + count > maximum) throw new IOException("下载文件超出大小限制");
            out.write(buffer, 0, count);
        }
        OnlineLibrary.checkCancelled(); return out.toByteArray();
    }

    private static String siteUrl(String base, String href) {
        if (href == null || href.trim().isEmpty()) return "";
        try {
            URI root = URI.create(base), value = root.resolve(href.trim());
            if (!"https".equalsIgnoreCase(value.getScheme()) || value.getHost() == null || root.getHost() == null
                || !value.getHost().equalsIgnoreCase(root.getHost()) || value.getUserInfo() != null || value.getFragment() != null) return "";
            return new URI("https", value.getRawAuthority(), value.getRawPath(), value.getRawQuery(), null).toString();
        } catch (Exception ignored) { return ""; }
    }

    private static String urlPath(String url) { try { return URI.create(url).getPath(); } catch (Exception e) { return ""; } }

    private static String listPrefix(String html, int position) {
        String before = html.substring(0, position); int open = Math.max(before.lastIndexOf("<li"), before.lastIndexOf("<LI"));
        int close = Math.max(before.lastIndexOf("</li>"), before.lastIndexOf("</LI>"));
        if (open <= close) return "";
        int content = before.indexOf('>', open); return content < 0 ? "" : text(before.substring(content + 1));
    }

    private static String headingText(String html, int position) {
        String before = html.substring(0, position); int start = -1; String tag = "";
        for (String candidate : new String[]{"h2", "h3", "h4"}) {
            int value = Math.max(before.lastIndexOf("<" + candidate), before.lastIndexOf("<" + candidate.toUpperCase(Locale.ROOT)));
            if (value > start) { start = value; tag = candidate; }
        }
        if (start < 0) return "";
        int end = html.toLowerCase(Locale.ROOT).indexOf("</" + tag + ">", position);
        if (end < 0) return "";
        return text(html.substring(start, end));
    }

    private static String attribute(String raw, String wanted) {
        Matcher matcher = ATTRIBUTE.matcher(raw);
        while (matcher.find()) if (wanted.equalsIgnoreCase(matcher.group(1))) return decode(matcher.group(2) != null ? matcher.group(2) : matcher.group(3) != null ? matcher.group(3) : matcher.group(4));
        return "";
    }

    private static String text(String raw) { return decode(raw.replaceAll("(?is)<script\\b.*?</script\\s*>", " ").replaceAll("(?is)<style\\b.*?</style\\s*>", " ").replaceAll("(?is)<[^>]+>", " ").replaceAll("\\s+", " ")).trim(); }

    private static String textWithBreaks(String raw) { return decode(raw.replaceAll("(?is)<br\\s*/?>", "\\n").replaceAll("(?is)<[^>]+>", " ")); }

    private static String decode(String value) {
        String decoded = value.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", "\"").replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">");
        Matcher numeric = Pattern.compile("&#(x[0-9a-fA-F]+|\\d+);").matcher(decoded); StringBuffer result = new StringBuffer();
        while (numeric.find()) {
            try { int code = numeric.group(1).startsWith("x") ? Integer.parseInt(numeric.group(1).substring(1), 16) : Integer.parseInt(numeric.group(1)); numeric.appendReplacement(result, Matcher.quoteReplacement(new String(Character.toChars(code)))); }
            catch (Exception ignored) { numeric.appendReplacement(result, Matcher.quoteReplacement(numeric.group())); }
        }
        numeric.appendTail(result); return result.toString();
    }

    private static int pageNumber(String url, String source) {
        try {
            URI value = URI.create(url); String path = value.getPath();
            if (source.equals("midiworld")) {
                Matcher match = Pattern.compile("/search/(\\d+)/").matcher(path); if (match.matches()) return Integer.parseInt(match.group(1));
            }
            String page = queryParam(value.getRawQuery(), "page"); if (!page.isEmpty()) return Integer.parseInt(page) + (source.equals("bitmidi") ? 1 : 0);
        } catch (Exception ignored) { }
        return 0;
    }

    private static String queryParam(String query, String wanted) {
        if (query == null) return "";
        for (String part : query.split("&")) { String[] values = part.split("=", 2); if (values.length == 2 && values[0].equals(wanted)) return values[1]; }
        return "";
    }

    private static boolean containsAll(String value, String[] terms) { for (String term : terms) if (!term.isEmpty() && !value.contains(term)) return false; return true; }
    private static boolean containsAny(String value, String... markers) { for (String marker : markers) if (value.contains(marker)) return true; return false; }
    private static String firstNonEmpty(String... values) { for (String value : values) if (value != null && !value.trim().isEmpty()) return value.trim(); return ""; }
    private static String limit(String value, int length) { return value.substring(0, Math.min(length, value.length())); }

    private static String simplify(String value) {
        String normalized = Normalizer.normalize(value, Normalizer.Form.NFKC);
        String traditional = "國軍樂風學聲調網頁體現說後會這個與專區臺萬無為標題時間開關門進線場點燈雲書現實話長東門義氣親愛車頭級號錄單對應發來過還從裡見種樣線電報節樂"
            + "萬與為於於";
        String simplified = "国军乐风学声调网页体现说后会这个与专区台万无为标题时间开关门进线场点灯云书现实话长东门义气亲爱车头级号录单对应发来过还从里见种样线电报节乐"
            + "万与为于于";
        StringBuilder result = new StringBuilder(normalized.length());
        for (int i = 0; i < normalized.length(); i++) {
            char current = normalized.charAt(i); int index = traditional.indexOf(current);
            result.append(index >= 0 && index < simplified.length() ? simplified.charAt(index) : current);
        }
        return result.toString();
    }
}
