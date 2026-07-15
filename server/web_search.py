"""Bounded HTTPS web-search client for the read-only Agent tool surface."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse


_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


@dataclass(frozen=True)
class WebSearchConfig:
    enabled: bool
    endpoint: str
    api_key_env: str
    timeout_seconds: int = 8
    max_results: int = 5

    @classmethod
    def from_environment(cls) -> "WebSearchConfig":
        enabled = os.environ.get("WEB_SEARCH_ENABLED", "false").lower() in {"1", "true", "yes"}
        endpoint = os.environ.get("WEB_SEARCH_ENDPOINT", "https://api.tavily.com/search").rstrip("/")
        api_key_env = os.environ.get("WEB_SEARCH_API_KEY_ENV", "TAVILY_API_KEY")
        timeout_seconds = min(max(int(os.environ.get("WEB_SEARCH_TIMEOUT_SECONDS", "8")), 1), 20)
        max_results = min(max(int(os.environ.get("WEB_SEARCH_MAX_RESULTS", "5")), 1), 10)
        if not _ENV_NAME.fullmatch(api_key_env):
            raise ValueError("WEB_SEARCH_API_KEY_ENV 必须是大写环境变量名称")
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("WEB_SEARCH_ENDPOINT 必须为 HTTPS 地址")
        return cls(enabled, endpoint, api_key_env, timeout_seconds, max_results)


class WebSearchClient:
    def __init__(self, config: WebSearchConfig):
        self._config = config

    @property
    def available(self) -> bool:
        return self._config.enabled and bool(os.environ.get(self._config.api_key_env, ""))

    def search(self, query: str, limit: int | None = None) -> dict:
        query = query.strip()
        if len(query) < 2 or len(query) > 300:
            raise ValueError("网页检索关键词长度必须在 2 到 300 个字符之间")
        if not self._config.enabled:
            raise ValueError("网页检索未启用")
        api_key = os.environ.get(self._config.api_key_env, "")
        if not api_key:
            raise ValueError("网页检索未配置 API Key")
        result_limit = min(max(limit or self._config.max_results, 1), self._config.max_results)
        payload = json.dumps({
            "api_key": api_key,
            "query": query,
            "max_results": result_limit,
            "include_answer": False,
        }).encode("utf-8")
        request = urllib.request.Request(
            self._config.endpoint,
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                raw = response.read(512 * 1024)
        except urllib.error.HTTPError as exc:
            raise ValueError(f"网页检索服务返回 {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ValueError("网页检索服务暂不可用") from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("网页检索服务返回了无效数据") from exc
        results = decoded.get("results", []) if isinstance(decoded, dict) else []
        if not isinstance(results, list):
            raise ValueError("网页检索服务返回了无效结果")
        sources = [source for item in results[:result_limit] if (source := _public_source(item))]
        return {"query": query, "sources": sources, "count": len(sources)}


def _public_source(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None
    url = item.get("url")
    parsed = urlparse(url) if isinstance(url, str) else None
    if not parsed or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    title = str(item.get("title") or parsed.netloc).strip()[:240]
    excerpt = str(item.get("content") or item.get("snippet") or "").strip()[:700]
    return {"kind": "web", "title": title, "url": url[:2048], "excerpt": excerpt}
