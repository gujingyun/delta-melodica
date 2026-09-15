import unittest

from error_messages import redact_error, user_error


class ErrorMessagesTest(unittest.TestCase):
    def test_network_error_uses_generic_message(self):
        error = TimeoutError(
            "failed to connect to music.example.test/203.0.113.10 (port 443) "
            "from /192.0.2.10 (port 35066) after 8000ms"
        )
        self.assertEqual(user_error(error, "网络连接失败，请稍后重试"), "网络连接失败，请稍后重试")

    def test_redact_error_hides_network_identifiers(self):
        text = redact_error("访问 https://music.example.test:443/score/203.0.113.10 失败")
        self.assertNotIn("music.example.test", text)
        self.assertNotIn("203.0.113.10", text)
        self.assertNotIn("443", text)

    def test_local_error_keeps_actionable_message(self):
        self.assertEqual(user_error("第 3 行的音符格式不正确"), "第 3 行的音符格式不正确")
        self.assertEqual(user_error(OSError("本地曲库写入失败")), "本地曲库写入失败")


if __name__ == "__main__":
    unittest.main(verbosity=2)
