from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str
    base_url: str
    ssl_verify: bool = True
    ca_file: str = ""
    timeout_seconds: int = 300
    provider_name: str = "DeepSeek"


class DeepSeekProvider:
    """Minimal OpenAI-compatible DeepSeek Chat Completions provider.

    The provider owns HTTP/SSE parsing only. Agent orchestration, prompt
    construction and persistence remain in the application runtime.
    """

    def __init__(self, config: DeepSeekConfig, certifi_module=None):
        self._config = config
        self._certifi = certifi_module

    def complete(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str,
        max_output_tokens: int,
    ) -> dict:
        with self._open_stream(messages, tools, model, max_output_tokens) as response:
            return _read_sse_message(response)

    def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str,
        max_output_tokens: int,
    ) -> Iterator[dict]:
        with self._open_stream(messages, tools, model, max_output_tokens) as response:
            content_parts: list[str] = []
            tool_calls = _ToolCallAccumulator()
            for delta in _iter_sse_deltas(response):
                content = delta.get("content")
                if content:
                    content_parts.append(content)
                    yield {"type": "content", "text": content}
                tool_calls.add(delta.get("tool_calls") or [])
            yield {
                "type": "done",
                "message": {
                    "role": "assistant",
                    "content": "".join(content_parts),
                    "tool_calls": tool_calls.value(),
                },
            }

    def _open_stream(self, messages: list[dict], tools: list[dict], model: str, max_output_tokens: int):
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": 0.4,
            "max_tokens": max_output_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        request = urllib.request.Request(
            f"{self._config.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            return urllib.request.urlopen(
                request,
                timeout=self._config.timeout_seconds,
                context=self._ssl_context(),
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"{self._config.provider_name} 请求失败：{exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            if "CERTIFICATE_VERIFY_FAILED" in reason:
                raise RuntimeError(
                    f"{self._config.provider_name} 请求失败：本机 HTTPS 证书校验失败。"
                    "本地开发可在 .env 中设置 DEEPSEEK_SSL_VERIFY=false；"
                    "生产环境建议安装正确 CA 证书后保持校验开启。"
                ) from exc
            raise RuntimeError(f"{self._config.provider_name} 请求失败：{reason}") from exc

    def _ssl_context(self):
        if not self._config.ssl_verify:
            return ssl._create_unverified_context()
        if self._config.ca_file:
            return ssl.create_default_context(cafile=self._config.ca_file)
        if self._certifi:
            return ssl.create_default_context(cafile=self._certifi.where())
        return ssl.create_default_context()


class _ToolCallAccumulator:
    def __init__(self):
        self._calls: dict[int, dict] = {}

    def add(self, chunks: list[dict]) -> None:
        for tool_call in chunks:
            index = tool_call.get("index", 0)
            entry = self._calls.setdefault(index, {
                "id": tool_call.get("id") or "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            })
            if tool_call.get("id"):
                entry["id"] = tool_call["id"]
            function = tool_call.get("function", {})
            if function.get("name"):
                entry["function"]["name"] += function["name"]
            if function.get("arguments"):
                entry["function"]["arguments"] += function["arguments"]

    def value(self) -> list[dict] | None:
        return [self._calls[index] for index in sorted(self._calls)] or None


def _iter_sse_deltas(response) -> Iterator[dict]:
    for raw_line in response:
        line = raw_line.decode("utf-8").strip()
        if not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        yield payload.get("choices", [{}])[0].get("delta", {})


def _read_sse_message(response) -> dict:
    content_parts: list[str] = []
    tool_calls = _ToolCallAccumulator()
    for delta in _iter_sse_deltas(response):
        if delta.get("content"):
            content_parts.append(delta["content"])
        tool_calls.add(delta.get("tool_calls") or [])
    return {
        "role": "assistant",
        "content": "".join(content_parts),
        "tool_calls": tool_calls.value(),
    }
