package top.aiygzn.melodica;

import org.junit.Test;
import static org.junit.Assert.*;

public class AccountResponseTest {
    @Test public void acceptsSuccessfulJson() throws Exception {
        assertEquals(0, AccountResponse.parse(200, "{\"songs\":[]}").getJSONArray("songs").length());
    }

    @Test public void explainsRateLimitWithHtmlOrEmptyBody() throws Exception {
        rejects(429, "<html>Too Many Requests</html>", "请求过于频繁");
        rejects(429, "", "请求过于频繁");
        rejects(401, "", "重新登录");
        rejects(502, "<html>Bad Gateway</html>", "暂时不可用");
    }

    @Test public void malformedSuccessNeverExposesRawContent() throws Exception {
        for (String body : new String[]{"", "\"private-response\"", "[]", "<html>private-response</html>"}) {
            rejects(200, body, "异常内容");
        }
    }

    @Test public void preservesValidationMessageAndHandlesMissingDetail() throws Exception {
        rejects(409, "{\"detail\":\"云端曲库已满\"}", "云端曲库已满");
        rejects(400, "{\"detail\":null}", "账号请求失败");
        rejects(403, "<html>Forbidden</html>", "HTTP 403");
    }

    private static void rejects(int status, String body, String expected) throws Exception {
        try {
            AccountResponse.parse(status, body);
            fail("应拒绝异常响应");
        } catch (IllegalArgumentException error) {
            assertTrue(error.getMessage(), error.getMessage().contains(expected));
            assertFalse(error.getMessage().contains("private-response"));
        }
    }
}
