package top.aiygzn.melodica;

import java.io.InterruptedIOException;
import java.net.ConnectException;
import java.net.NoRouteToHostException;
import java.net.SocketException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import java.util.regex.Pattern;

/** 统一处理用户可见错误，避免把网络端点和本机地址显示到界面。 */
public final class ErrorMessages {
    private static final Pattern IPV4 = Pattern.compile("(?<![\\d.])(?:\\d{1,3}\\.){3}\\d{1,3}(?![\\d.])");
    private static final Pattern IPV6 = Pattern.compile("(?i)(?<![0-9a-f:])(?:[0-9a-f]{1,4}:){2,}[0-9a-f:]+(?![0-9a-f:])");
    private static final Pattern URL = Pattern.compile("(?i)https?://\\S+");
    private static final Pattern DOMAIN = Pattern.compile("(?i)(?<![a-z0-9-])(?:[a-z0-9-]+\\.)+[a-z]{2,}(?::\\d+)?(?![a-z0-9-])");
    private static final Pattern PORT = Pattern.compile("(?i)(?:\\bport|端口)\\s*[:：]?\\s*\\d+");

    private ErrorMessages() { }

    public static String userMessage(Throwable error, String fallback) {
        if (error == null) return fallback;
        if (isNetworkError(error)) return fallback;
        String message = redact(error.getMessage());
        return message.isEmpty() ? fallback : message;
    }

    public static String redact(String message) {
        if (message == null || message.trim().isEmpty()) return "";
        String result = URL.matcher(message).replaceAll("[网络地址已隐藏]");
        result = IPV4.matcher(result).replaceAll("[地址已隐藏]");
        result = IPV6.matcher(result).replaceAll("[地址已隐藏]");
        result = DOMAIN.matcher(result).replaceAll("[域名已隐藏]");
        result = PORT.matcher(result).replaceAll("端口已隐藏");
        return result.trim();
    }

    private static boolean isNetworkError(Throwable error) {
        Throwable current = error;
        while (current != null) {
            if (current instanceof ConnectException || current instanceof NoRouteToHostException
                || current instanceof SocketException || current instanceof SocketTimeoutException
                || current instanceof UnknownHostException || current instanceof InterruptedIOException) return true;
            String name = current.getClass().getName().toLowerCase(java.util.Locale.ROOT);
            if (name.contains("ssl") || name.contains("socket") || name.contains("connect") || name.contains("timeout")) return true;
            current = current.getCause();
        }
        return false;
    }
}
