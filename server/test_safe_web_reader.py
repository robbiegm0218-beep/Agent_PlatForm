import unittest

from server.safe_web_reader import SafeWebPageReader


class SafeWebPageReaderTests(unittest.TestCase):
    def test_extracts_html_and_follows_validated_redirect(self):
        responses = {
            "https://example.com/start": (302, {"location": "/page", "content-type": "text/plain"}, b""),
            "https://example.com/page": (200, {"content-type": "text/html; charset=utf-8"}, "<title>标题</title><script>secret</script><p>正文内容</p>".encode()),
        }
        reader = SafeWebPageReader(resolver=lambda _host: ["93.184.216.34"], requester=lambda url, _timeout, _max: responses[url])
        result = reader.read("https://example.com/start")
        self.assertEqual(result["title"], "标题")
        self.assertIn("正文内容", result["content"])
        self.assertNotIn("secret", result["content"])

    def test_rejects_http_credentials_ports_and_private_addresses(self):
        reader = SafeWebPageReader(resolver=lambda _host: ["127.0.0.1"], requester=lambda *_args: (200, {}, b""))
        for url in ("http://example.com", "https://user@example.com", "https://example.com:8443", "https://localhost"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                reader.read(url)
        with self.assertRaisesRegex(ValueError, "私有"):
            reader.read("https://example.com")

    def test_rejects_binary_and_oversized_responses(self):
        resolver = lambda _host: ["93.184.216.34"]
        binary = SafeWebPageReader(resolver=resolver, requester=lambda *_args: (200, {"content-type": "application/octet-stream"}, b"x"))
        with self.assertRaisesRegex(ValueError, "类型"):
            binary.read("https://example.com")
        oversized = SafeWebPageReader(resolver=resolver, requester=lambda *_args: (_ for _ in ()).throw(ValueError("网页响应超过允许大小")))
        with self.assertRaisesRegex(ValueError, "大小"):
            oversized.read("https://example.com")


if __name__ == "__main__":
    unittest.main()
