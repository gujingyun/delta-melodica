package top.aiygzn.melodica;

import org.json.JSONException;
import org.json.JSONObject;

/** 网关错误可能返回网页或空正文，不能直接作为账号 JSON 展示。 */
final class AccountResponse {
    private AccountResponse() { }

    static JSONObject parse(int status, String body) throws Exception {
        if (status == 429) throw new IllegalArgumentException("同步请求过于频繁，请稍等片刻后重试；已同步曲谱会保留");
        if (status == 401) throw new IllegalArgumentException("登录已失效，请重新登录后同步");
        if (status >= 500) throw new IllegalArgumentException("账号服务暂时不可用，请稍后重试（HTTP " + status + "）");
        JSONObject response;
        try {
            response = new JSONObject(body);
        } catch (JSONException error) {
            throw new IllegalArgumentException("账号服务返回了异常内容，请稍后重试（HTTP " + status + "）");
        }
        if (status >= 400) {
            Object detail = response.opt("detail");
            throw new IllegalArgumentException(detail instanceof String && !((String) detail).trim().isEmpty()
                ? (String) detail : "账号请求失败，请稍后重试（HTTP " + status + "）");
        }
        return response;
    }
}
