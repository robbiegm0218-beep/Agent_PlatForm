import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from server.web_search import WebSearchClient, WebSearchConfig


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size):
        return self.payload


class WebSearchTests(unittest.TestCase):
    def config(self, enabled=True):
        return WebSearchConfig(enabled, "https://search.example.test/api", "SEARCH_API_KEY", timeout_seconds=3, max_results=3)

    def test_disabled_or_missing_key_never_calls_network(self):
        with patch("server.web_search.urllib.request.urlopen") as open_url:
            with self.assertRaisesRegex(ValueError, "未启用"):
                WebSearchClient(self.config(False)).search("agent platform")
            with patch.dict(os.environ, {"SEARCH_API_KEY": ""}, clear=False):
                with self.assertRaisesRegex(ValueError, "未配置"):
                    WebSearchClient(self.config()).search("agent platform")
        open_url.assert_not_called()

    def test_returns_only_safe_http_sources_and_bounds_results(self):
        payload = json.dumps({"results": [
            {"title": "可信来源", "url": "https://example.test/a", "content": "摘要"},
            {"title": "无效", "url": "file:///private/data", "content": "不应展示"},
        ]}).encode()
        with patch.dict(os.environ, {"SEARCH_API_KEY": "key"}, clear=False), patch(
            "server.web_search.urllib.request.urlopen", return_value=FakeResponse(payload)
        ) as open_url:
            result = WebSearchClient(self.config()).search("agent platform", 10)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["sources"][0]["url"], "https://example.test/a")
        request = open_url.call_args.args[0]
        self.assertNotIn("key", request.full_url)

    def test_http_error_is_sanitized(self):
        error = urllib.error.HTTPError("https://search.example.test", 429, "rate", {}, io.BytesIO(b"secret"))
        with patch.dict(os.environ, {"SEARCH_API_KEY": "key"}, clear=False), patch(
            "server.web_search.urllib.request.urlopen", side_effect=error
        ):
            with self.assertRaisesRegex(ValueError, "返回 429"):
                WebSearchClient(self.config()).search("agent platform")

    def test_environment_rejects_non_https_endpoint_and_secret_like_env_name(self):
        with patch.dict(os.environ, {"WEB_SEARCH_ENDPOINT": "http://example.test", "WEB_SEARCH_API_KEY_ENV": "SEARCH_API_KEY"}, clear=False):
            with self.assertRaises(ValueError):
                WebSearchConfig.from_environment()
        with patch.dict(os.environ, {"WEB_SEARCH_ENDPOINT": "https://example.test", "WEB_SEARCH_API_KEY_ENV": "sk-secret"}, clear=False):
            with self.assertRaises(ValueError):
                WebSearchConfig.from_environment()


if __name__ == "__main__":
    unittest.main()
