package top.aiygzn.melodica;

import org.junit.Test;
import java.net.ConnectException;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/** 用户可见异常消息的网络地址脱敏测试。 */
public class ErrorMessagesTest {
    @Test public void hidesNetworkExceptionDetails() {
        ConnectException error = new ConnectException("failed to connect to music.example.test/203.0.113.10 (port 443) from /192.0.2.10 (port 35066) after 8000ms");
        assertEquals("网络连接失败，请检查网络后重试", ErrorMessages.userMessage(error, "网络连接失败，请检查网络后重试"));
    }

    @Test public void redactsAddressesFromNonNetworkMessages() {
        String value = ErrorMessages.redact("来源 https://music.example.test:443/path，地址 203.0.113.10，端口 35066");
        assertFalse(value.contains("music.example.test")); assertFalse(value.contains("203.0.113.10")); assertFalse(value.contains("35066"));
        assertTrue(value.contains("网络地址已隐藏")); assertTrue(value.contains("地址已隐藏"));
    }

    @Test public void keepsUsefulLocalValidationMessage() {
        assertEquals("曲目不能超过 30 分钟", ErrorMessages.userMessage(new IllegalArgumentException("曲目不能超过 30 分钟"), "失败"));
    }
}
