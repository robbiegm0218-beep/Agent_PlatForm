"""Bounded HTTPS page reader with deterministic SSRF and content controls."""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urljoin, urlparse


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._blocked = 0
        self._in_title = False

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._blocked += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._blocked:
            self._blocked -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._blocked:
            return
        value = " ".join(data.split())
        if value:
            self.parts.append(value)
            if self._in_title:
                self.title_parts.append(value)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SafeWebPageReader:
    def __init__(
        self,
        *,
        resolver: Callable[[str], list[str]] | None = None,
        requester: Callable[[str, float, int], tuple[int, dict, bytes]] | None = None,
        timeout_seconds: float = 6,
        max_bytes: int = 524_288,
        max_redirects: int = 3,
    ) -> None:
        self.resolver = resolver or self._resolve
        self.requester = requester or self._request
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects

    def read(self, url: str, max_chars: int = 16000) -> dict:
        current = str(url).strip()
        redirects = 0
        while True:
            self._validate_url(current)
            status, headers, body = self.requester(current, self.timeout_seconds, self.max_bytes)
            if status in {301, 302, 303, 307, 308}:
                location = headers.get("location", "")
                if not location or redirects >= self.max_redirects:
                    raise ValueError("网页重定向无效或次数过多")
                current = urljoin(current, location)
                redirects += 1
                continue
            if status < 200 or status >= 300:
                raise ValueError(f"网页读取失败：HTTP {status}")
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
                raise ValueError("网页响应类型不允许读取")
            charset = "utf-8"
            if "charset=" in headers.get("content-type", "").lower():
                charset = headers["content-type"].lower().split("charset=", 1)[1].split(";", 1)[0].strip()
            decoded = body.decode(charset, errors="replace")
            if content_type == "text/plain":
                title, text = "网页正文", " ".join(decoded.split())
            else:
                parser = _TextExtractor()
                parser.feed(decoded)
                title = " ".join(parser.title_parts)[:240] or "网页正文"
                text = "\n".join(parser.parts)
            limit = min(max(int(max_chars), 1), 20000)
            return {"url": current, "title": title, "content": text[:limit], "truncated": len(text) > limit}

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("只允许读取无凭据的 HTTPS 网页")
        if parsed.port not in {None, 443}:
            raise ValueError("网页端口不允许访问")
        hostname = parsed.hostname.lower().rstrip(".")
        if hostname == "localhost" or hostname.endswith((".local", ".internal")):
            raise ValueError("网页主机属于本地或内部网络")
        addresses = self.resolver(hostname)
        if not addresses:
            raise ValueError("网页主机无法解析")
        for address in addresses:
            try:
                if not ipaddress.ip_address(address).is_global:
                    raise ValueError("网页地址属于本地、私有或保留网络")
            except ValueError as exc:
                if "属于" in str(exc):
                    raise
                raise ValueError("网页主机解析结果无效") from exc

    @staticmethod
    def _resolve(hostname: str) -> list[str]:
        return sorted({item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)})

    @staticmethod
    def _request(url: str, timeout: float, max_bytes: int) -> tuple[int, dict, bytes]:
        request = urllib.request.Request(url, headers={"User-Agent": "Agent-Platform/1.0", "Accept": "text/html,text/plain"})
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            declared = int(headers.get("content-length", "0") or 0)
            if declared > max_bytes:
                raise ValueError("网页响应超过允许大小")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError("网页响应超过允许大小")
            return response.status, headers, body
