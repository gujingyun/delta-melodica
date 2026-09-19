package top.aiygzn.melodica;

import org.jsoup.Jsoup;
import org.jsoup.nodes.Document;
import org.jsoup.nodes.Element;
import org.jsoup.nodes.Node;
import org.jsoup.nodes.TextNode;
import org.json.JSONObject;
import java.net.URI;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

/** 聚合来源仅解析公开网页，验证及账号积分下载交由源站处理。 */
public final class ResourceSearch {
    public static final String[] IDS = {"jianpu", "official", "bitmidi", "midiworld", "midishow"};
    public static final String[] NAMES = {"简谱空间", "官网曲库", "BitMidi", "MidiWorld", "MidiShow"};
    public static final class Song {
        public final String source, title, artist, pageUrl, downloadUrl;
        final OnlineLibrary.Song official;
        Song(String source, String title, String artist, String pageUrl, String downloadUrl, OnlineLibrary.Song official) {
            this.source = source; this.title = title; this.artist = artist; this.pageUrl = pageUrl; this.downloadUrl = downloadUrl; this.official = official;
        }
        public String key() { return source + ":" + (downloadUrl.isEmpty() ? pageUrl : downloadUrl); }
        public String label() { for (int i = 0; i < IDS.length; i++) if (IDS[i].equals(source)) return NAMES[i]; return source; }
    }
    public static final class Page {
        public final List<Song> songs = new ArrayList<>();
        public boolean more;
    }
    private ResourceSearch() { }
    public static String searchUrl(String source, String query, int page) throws Exception {
        if (page < 1 || page > 1000) throw new IllegalArgumentException("页码无效");
        String q = URLEncoder.encode(query, "UTF-8");
        switch (source) {
            case "jianpu": return "https://jianpu.space/songList";
            case "official": return OnlineLibrary.CATALOG_URL;
            case "bitmidi": return "https://bitmidi.com/search?q=" + q + "&page=" + (page - 1);
            case "midiworld": return "https://www.midiworld.com/search/" + (page > 1 ? page + "/" : "") + "?q=" + q;
            case "midishow": return "https://www.midishow.com/search/result?q=" + q + "&page=" + page;
            default: throw new IllegalArgumentException("来源无效");
        }
    }
    static String siteUrl(String base, String href) {
        try {
            URI origin = URI.create(base), url = origin.resolve(href);
            if (!origin.getHost().equalsIgnoreCase(url.getHost()) || url.getUserInfo() != null
                || !(url.getScheme().equalsIgnoreCase("https") || url.getScheme().equalsIgnoreCase("http"))
                || url.getPort() != -1 && url.getPort() != 80 && url.getPort() != 443) return "";
            return new URI("https", null, url.getHost(), -1, url.getPath(), url.getQuery(), null).toString();
        } catch (Exception e) { return ""; }
    }
    static boolean verification(String html) {
        String lower = html.toLowerCase(Locale.ROOT), title = Jsoup.parse(html).title().toLowerCase(Locale.ROOT);
        return (title.contains("just a moment") || title.contains("请稍候") || title.contains("attention required") || title.contains("checking your browser"))
            && (lower.contains("cf-chl-") || lower.contains("challenge-platform") || lower.contains("cloudflare"));
    }
    static String html(String url) throws Exception {
        String text = new String(OnlineLibrary.fetch(url, 2 * 1024 * 1024), StandardCharsets.UTF_8);
        if (verification(text)) throw new IllegalArgumentException("需要浏览器人机验证，请在源站下载后导入"); return text;
    }
    public static Page search(String source, String query, int page) throws Exception {
        if (query.trim().isEmpty() || query.length() > 100) throw new IllegalArgumentException("请输入 1～100 个字符的曲名或作者");
        if (source.equals("official")) {
            Page result = new Page(); if (page > 1) return result;
            for (OnlineLibrary.Song song : OnlineLibrary.fetchCatalog()) if (matches(song.title + " " + song.artist + " " + song.description, query))
                result.songs.add(new Song(source, song.title, song.artist, "https://aiygzn.top/melodica/", song.url, song));
            return result;
        }
        if (source.equals("jianpu") && page > 1) return new Page();
        return parse(source, html(searchUrl(source, query, page)), query, page);
    }
    static String simplified(String text) {
        String normalized = Normalizer.normalize(text, Normalizer.Form.NFKC).toLowerCase(Locale.ROOT);
        StringBuilder result = new StringBuilder(normalized.length());
        for (int i = 0; i < normalized.length(); i++) result.append(Chinese.MAP.getOrDefault(normalized.charAt(i), normalized.charAt(i)));
        return result.toString();
    }
    private static final class Chinese {
        static final java.util.Map<Character, Character> MAP = new java.util.HashMap<>();
        static {
            try (java.io.InputStream input = ResourceSearch.class.getResourceAsStream("/traditional-chinese.txt")) {
                if (input != null) {
                    java.io.BufferedReader reader = new java.io.BufferedReader(new java.io.InputStreamReader(input, StandardCharsets.UTF_8)); String line;
                    while ((line = reader.readLine()) != null) if (line.length() == 2) MAP.put(line.charAt(0), line.charAt(1));
                }
            } catch (java.io.IOException ignored) { /* 缺失字表时仍支持原文搜索。 */ }
        }
    }
    static boolean matches(String text, String query) {
        String haystack = simplified(text); for (String term : simplified(query).trim().split("\\s+")) if (!haystack.contains(term)) return false; return true;
    }
    static Page parse(String source, String html, String query, int page) throws Exception {
        if (verification(html)) throw new IllegalArgumentException("需要浏览器人机验证，请在源站下载后导入");
        String base = searchUrl(source, query, page); Document doc = Jsoup.parse(html, base); Page result = new Page(); Set<String> seen = new HashSet<>();
        int valid = 0;
        if (source.equals("jianpu")) {
            for (Element row : doc.select("tr")) {
                org.jsoup.select.Elements cells = row.select("td"); if (cells.size() < 2) continue;
                Element link = cells.get(0).selectFirst("a[href]"); if (link == null) continue;
                String url = siteUrl(base, link.attr("href")), title = cells.get(0).text(), artist = cells.get(1).text();
                if (url.isEmpty() || !URI.create(url).getPath().matches("/songList/(?:[0-9]+|[a-f0-9]{24})") || title.isEmpty()) continue;
                valid++; if (artist.equals("None")) artist = "";
                if (seen.add(url) && matches(title + " " + artist, query)) result.songs.add(new Song(source, truncate(title, 100), artist, url, "", null));
            }
            if (valid == 0) throw new IllegalArgumentException("未返回可识别的曲目目录，可能需要验证或页面已变化");
            return result;
        }
        for (Element link : doc.select("a[href]")) {
            String url = siteUrl(base, link.attr("href")); if (url.isEmpty()) continue;
            URI uri = URI.create(url); String path = uri.getPath(), title = "", download = "";
            if (path.contains("search")) {
                java.util.regex.Matcher number = java.util.regex.Pattern.compile("(?:[?&]page=|/search/)([0-9]+)").matcher(url);
                if (number.find() && Integer.parseInt(number.group(1)) > (source.equals("bitmidi") ? page - 1 : page)) result.more = true;
            }
            if (source.equals("bitmidi") && path.matches("/[^/]+-midi?")) title = link.hasAttr("title") ? link.attr("title") : link.text();
            if (source.equals("midiworld") && path.matches("/download/[0-9]+/?")) {
                Element li = link.closest("li"); if (li != null) { Element copy = li.clone(); copy.select("a").remove(); title = copy.text().replaceAll("[\\s-]+$", ""); } download = url;
            }
            if (source.equals("midishow") && path.matches("/midi/(?:[0-9]+\\.html|[^/]+-[0-9]+)")) {
                Element heading = link.selectFirst("h2,h3,h4"); title = heading == null ? link.attr("title") : heading.text();
            }
            if (title.isEmpty() && (source.equals("bitmidi") && path.matches("/[^/]+-midi?")
                || source.equals("midiworld") && !download.isEmpty()
                || source.equals("midishow") && path.matches("/midi/(?:[0-9]+\\.html|[^/]+-[0-9]+)"))) title = link.text();
            title = title.replaceAll("(?i)\\.midi?$", "").trim();
            if (!title.isEmpty() && seen.add(url)) result.songs.add(new Song(source, truncate(title, 100), "", download.isEmpty() ? url : base, download, null));
        }
        if (result.songs.isEmpty() && !html.toLowerCase(Locale.ROOT).matches("(?s).*(0 results|no results|found nothing|共找到 0|没有找到|未找到).*"))
            throw new IllegalArgumentException("未返回可识别的结果，可能需要验证或页面已变化；可打开源站搜索");
        return result;
    }
    static String truncate(String text, int max) { return text.substring(0, Math.min(max, text.length())); }
    static String notation(String html) {
        Element element = Jsoup.parse(html).getElementById("jianpuOut"); if (element == null) throw new IllegalArgumentException("未找到完整简谱文字，请打开源谱核对");
        StringBuilder text = new StringBuilder(); appendText(element, text); return text.toString();
    }
    private static void appendText(Node node, StringBuilder output) {
        if (node instanceof TextNode) output.append(((TextNode) node).getWholeText());
        else if (node.nodeName().equals("br")) output.append('\n');
        else for (Node child : node.childNodes()) appendText(child, output);
    }
    public static String download(Song song, Library library, String mode) throws Exception {
        OnlineLibrary.checkCancelled();
        if (song.source.equals("midishow")) throw new IllegalArgumentException("请按源站账号和积分规则下载，再导入已下载 MIDI");
        if (song.source.equals("jianpu")) {
            String text = notation(html(song.pageUrl)); Jianpu.Result parsed = Jianpu.source(text, song.title, mode); OnlineLibrary.checkCancelled();
            String id = UUID.nameUUIDFromBytes((song.pageUrl + "\n" + mode + "\n" + text).getBytes(StandardCharsets.UTF_8)) + ".json";
            return library.saveDocument(new Library.Document(parsed.score, text, 120, mode, song.pageUrl, "简谱"), id);
        }
        if (song.official != null) return OnlineLibrary.downloadTo(song.official, library);
        String download = song.downloadUrl;
        if (download.isEmpty() && song.source.equals("bitmidi")) {
            for (Element link : Jsoup.parse(html(song.pageUrl)).select("a[href]")) {
                String url = siteUrl(song.pageUrl, link.attr("href"));
                if (!url.isEmpty() && URI.create(url).getPath().matches("(?i)/uploads/[^/]+\\.midi?")) { download = url; break; }
            }
        }
        if (download.isEmpty()) throw new IllegalArgumentException("未找到公开 MIDI 下载链接，请打开源站查看");
        byte[] bytes = OnlineLibrary.fetch(download, OnlineLibrary.MAX_SONG_BYTES); Score score = MidiReader.read(bytes, song.title);
        ScoreTools.melody(score, -2, true); OnlineLibrary.checkCancelled();
        return library.save(score, OnlineLibrary.digest(bytes) + ".json", new JSONObject().put("kind", "MIDI").put("source_url", song.pageUrl));
    }
}
