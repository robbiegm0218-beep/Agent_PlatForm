"""Minimal, bounded Streamable HTTP MCP client for remote read-only tools."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

try:
    import certifi
except ImportError:
    certifi = None


MCP_PROTOCOL_VERSION = "2025-06-18"
MAX_MCP_RESPONSE_BYTES = 512 * 1024


@dataclass(frozen=True)
class McpServerConfig:
    server_id: str
    url_env: str
    query_api_key_env: str = ""
    query_api_key_param: str = ""
    tool_allowlist: tuple[str, ...] = ()
    timeout_seconds: int = 10

    @classmethod
    def from_environment(cls) -> list["McpServerConfig"]:
        raw = os.environ.get("MCP_SERVERS", "").strip()
        if not raw:
            return []
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("MCP_SERVERS 必须为 JSON 数组") from exc
        if not isinstance(entries, list):
            raise ValueError("MCP_SERVERS 必须为 JSON 数组")
        configs = []
        seen = set()
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("MCP 服务配置必须为对象")
            server_id = str(item.get("id", "")).strip()
            url_env = str(item.get("url_env", "")).strip()
            if not server_id.replace("_", "").replace("-", "").isalnum() or not url_env.isupper():
                raise ValueError("MCP 服务 ID 或 URL 环境变量无效")
            if server_id in seen:
                raise ValueError("MCP 服务 ID 不可重复")
            allowlist = item.get("tool_allowlist", [])
            if not isinstance(allowlist, list) or not all(isinstance(name, str) and name for name in allowlist):
                raise ValueError("MCP 工具白名单无效")
            query_env = str(item.get("query_api_key_env", "")).strip()
            query_param = str(item.get("query_api_key_param", "")).strip()
            if bool(query_env) != bool(query_param) or (query_env and not query_env.isupper()):
                raise ValueError("MCP 查询参数密钥配置无效")
            timeout = min(max(int(item.get("timeout_seconds", 10)), 1), 20)
            configs.append(cls(server_id, url_env, query_env, query_param, tuple(allowlist), timeout))
            seen.add(server_id)
        return configs

    def endpoint(self) -> str:
        endpoint = os.environ.get(self.url_env, "").strip()
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"MCP 服务 {self.server_id} 未配置 HTTPS 地址")
        if self.query_api_key_env:
            key = os.environ.get(self.query_api_key_env, "")
            if not key:
                raise ValueError(f"MCP 服务 {self.server_id} 未配置凭据")
            query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            query.append((self.query_api_key_param, key))
            endpoint = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
        return endpoint


class StreamableHttpMcpClient:
    def __init__(self, config: McpServerConfig):
        self._config = config
        self._endpoint = config.endpoint()
        self._session_id = ""
        self._protocol_version = MCP_PROTOCOL_VERSION
        self._request_id = 0

    def initialize(self) -> dict:
        result, headers = self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "agent-platform", "version": "1.0"},
        }, include_protocol=False)
        version = str(result.get("protocolVersion", MCP_PROTOCOL_VERSION))
        if not version:
            raise ValueError("MCP 服务未返回协议版本")
        self._protocol_version = version
        self._session_id = headers.get("Mcp-Session-Id", "")
        self._notify("notifications/initialized", {})
        return result

    def list_tools(self) -> list[dict]:
        tools, cursor = [], None
        for _ in range(10):
            params = {"cursor": cursor} if cursor else {}
            result, _ = self._request("tools/list", params)
            page = result.get("tools", [])
            if not isinstance(page, list):
                raise ValueError("MCP tools/list 返回无效数据")
            tools.extend(tool for tool in page if isinstance(tool, dict))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools[:100]

    def call_tool(self, name: str, arguments: dict) -> dict:
        result, _ = self._request("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict):
            raise ValueError("MCP tools/call 返回无效数据")
        return result

    def close(self) -> None:
        if not self._session_id:
            return
        request = urllib.request.Request(self._endpoint, headers=self._headers(), method="DELETE")
        try:
            urllib.request.urlopen(request, timeout=self._config.timeout_seconds, context=_ssl_context()).read(1)
        except urllib.error.HTTPError:
            pass

    def _notify(self, method: str, params: dict) -> None:
        self._post({"jsonrpc": "2.0", "method": method, "params": params}, expect_response=False)

    def _request(self, method: str, params: dict, include_protocol: bool = True) -> tuple[dict, Any]:
        self._request_id += 1
        payload = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}
        response, headers = self._post(payload, include_protocol)
        if "error" in response:
            raise ValueError(f"MCP 服务返回错误：{response['error'].get('message', '未知错误')}")
        if not isinstance(response.get("result"), dict):
            raise ValueError("MCP 服务未返回有效结果")
        return response["result"], headers

    def _post(self, payload: dict, include_protocol: bool = True, expect_response: bool = True) -> tuple[dict, Any]:
        headers = self._headers(include_protocol)
        request = urllib.request.Request(self._endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds, context=_ssl_context()) as response:
                raw = response.read(MAX_MCP_RESPONSE_BYTES)
                content_type = response.headers.get("Content-Type", "")
                headers_out = response.headers
        except urllib.error.HTTPError as exc:
            raise ValueError(f"MCP 服务返回 HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ValueError("MCP 服务暂不可用") from exc
        if not expect_response:
            return {}, headers_out
        return _decode_mcp_response(raw, content_type, payload.get("id")), headers_out

    def _headers(self, include_protocol: bool = True) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if include_protocol:
            headers["MCP-Protocol-Version"] = self._protocol_version
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers


class McpToolManager:
    def __init__(self, configs: list[McpServerConfig]):
        self._configs = {config.server_id: config for config in configs}

    @property
    def available(self) -> bool:
        return bool(self._configs)

    def search(self, query: str) -> dict:
        config = self._configs.get("tavily")
        if not config:
            raise ValueError("未配置 Tavily MCP 服务")
        client = StreamableHttpMcpClient(config)
        try:
            client.initialize()
            tools = client.list_tools()
            tool = next((item for item in tools if item.get("name") in config.tool_allowlist), None)
            if not tool:
                raise ValueError("Tavily MCP 未发现获准的搜索工具")
            result = client.call_tool(str(tool["name"]), {"query": query})
            sources = _sources_from_mcp_result(result)
            return {"query": query, "sources": sources, "count": len(sources), "provider": "mcp:tavily"}
        finally:
            client.close()


def _decode_mcp_response(raw: bytes, content_type: str, request_id: int | None) -> dict:
    text = raw.decode("utf-8", errors="replace")
    if "text/event-stream" in content_type:
        candidates = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        for candidate in candidates:
            try:
                message = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if message.get("id") == request_id:
                return message
        raise ValueError("MCP SSE 响应未包含请求结果")
    try:
        message = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("MCP 服务返回无效 JSON") from exc
    if not isinstance(message, dict):
        raise ValueError("MCP 服务返回无效消息")
    return message


def _sources_from_mcp_result(result: dict) -> list[dict]:
    content = result.get("content", [])
    sources = []
    for item in content if isinstance(content, list) else []:
        text = item.get("text", "") if isinstance(item, dict) else ""
        try:
            decoded = json.loads(text) if isinstance(text, str) else {}
        except json.JSONDecodeError:
            decoded = {}
        rows = decoded.get("results", []) if isinstance(decoded, dict) else []
        for row in rows if isinstance(rows, list) else []:
            url = str(row.get("url", "")) if isinstance(row, dict) else ""
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                sources.append({"kind": "web", "title": str(row.get("title") or parsed.netloc)[:240], "url": url[:2048], "excerpt": str(row.get("content") or row.get("snippet") or "")[:700]})
    return sources[:10]


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()
