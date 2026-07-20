from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Protocol


class ToolRegistry(Protocol):
    def get(self, tool_id: str): ...
    def callable_definitions(self, allowed_ids: set[str]) -> list[dict]: ...
    def execute(self, tool_id: str, arguments: dict, allowed_ids: set[str]) -> dict: ...


@dataclass(frozen=True)
class AgentLoopDependencies:
    load_messages: Callable[[str], list[dict]]
    stream_model: Callable[[list[dict], list[dict], dict], Iterable[dict]]
    tools: ToolRegistry
    new_id: Callable[[str], str]
    summarize_tool_result: Callable[[dict], str]


class SingleAgentLoop:
    """Bounded, tool-calling loop for one agent run.

    The class owns no prompt, HTTP, database or SSE transport state. Those are
    injected by the platform so the behavior is testable and remains portable
    to a future worker process.
    """

    def __init__(self, dependencies: AgentLoopDependencies):
        self._dependencies = dependencies

    def stream(
        self,
        thread_id: str,
        system_prompt: str,
        execution_context: dict,
        on_event: Callable[[str, dict], None],
    ) -> Iterator[str]:
        messages = [{"role": "system", "content": system_prompt}] + self._dependencies.load_messages(thread_id)
        allowed_tool_ids = set(execution_context["allowed_tool_ids"])
        tool_definitions = self._dependencies.tools.callable_definitions(allowed_tool_ids)
        called_tool_ids: set[str] = set()
        called_action_fingerprints: set[str] = set()
        executed_tool_calls = 0
        strict_tool_budget = bool(execution_context.get("strict_tool_budget"))

        # P45: a planner may propose one first read action.  The platform still
        # runs it through the same registry, schema and allow-list enforcement
        # used for model-originated calls; this is not an extra permission path.
        initial_action = execution_context.get("initial_tool_action")
        if isinstance(initial_action, dict) and initial_action.get("type") == "use_tool":
            tool_id = initial_action.get("tool_id", "")
            arguments = initial_action.get("arguments", {})
            if executed_tool_calls < execution_context["max_tool_steps"]:
                call = {
                    "id": self._dependencies.new_id("toolcall"),
                    "function": {"name": tool_id, "arguments": json.dumps(arguments, ensure_ascii=False)},
                }
                messages.append({"role": "assistant", "content": "", "tool_calls": [call]})
                fingerprint = self._tool_fingerprint(call)
                if fingerprint:
                    called_action_fingerprints.add(fingerprint)
                result = self._execute_tool_call(call, allowed_tool_ids, on_event)
                executed_tool_calls += 1
                called_tool_ids.add(result["tool_id"])
                messages.append({
                    "role": "tool",
                    "tool_call_id": result["tool_call_id"],
                    "content": json.dumps(result["content"], ensure_ascii=False),
                })

        for _step in range(execution_context["max_tool_steps"]):
            on_event("model_call", {"phase": "execution"})
            message = yield from self._run_model(messages, tool_definitions, execution_context)
            reasoning_characters = int(message.get("provider_reasoning_characters") or 0)
            if reasoning_characters:
                on_event("provider_reasoning_available", {"characters": reasoning_characters})
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                for tool_id in sorted(allowed_tool_ids - called_tool_ids):
                    tool = self._dependencies.tools.get(tool_id)
                    on_event("tool_not_called", {
                        "tool_id": tool_id,
                        "tool_name": tool.name if tool else tool_id,
                        "reason": "自动模式下模型判断当前上下文无需调用",
                    })
                content = (message.get("content") or "").strip()
                if not content:
                    raise RuntimeError("模型返回为空")
                return

            messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls})
            for call in tool_calls:
                fingerprint = self._tool_fingerprint(call)
                if fingerprint and fingerprint in called_action_fingerprints:
                    function = call.get("function", {})
                    tool_id = function.get("name", "")
                    tool_call_id = call.get("id") or self._dependencies.new_id("toolcall")
                    error = "相同工具与参数已执行；请基于已有结果修正参数或选择替代动作"
                    on_event("tool_error", {"tool_call_id": tool_call_id, "tool_id": tool_id, "tool_name": tool_id, "error": error, "duplicate_action": True})
                    messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"error": error}, ensure_ascii=False)})
                    continue
                if strict_tool_budget and executed_tool_calls >= execution_context["max_tool_steps"]:
                    function = call.get("function", {})
                    tool_id = function.get("name", "")
                    tool_call_id = call.get("id") or self._dependencies.new_id("toolcall")
                    error = "工具调用已达到本轮预算上限"
                    on_event("tool_error", {"tool_call_id": tool_call_id, "tool_id": tool_id, "tool_name": tool_id, "error": error, "budget_exhausted": True})
                    messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps({"error": error}, ensure_ascii=False)})
                    continue
                if fingerprint:
                    called_action_fingerprints.add(fingerprint)
                result = self._execute_tool_call(call, allowed_tool_ids, on_event)
                executed_tool_calls += 1
                called_tool_ids.add(result["tool_id"])
                messages.append({
                    "role": "tool",
                    "tool_call_id": result["tool_call_id"],
                    "content": json.dumps(result["content"], ensure_ascii=False),
                })

        messages.append({"role": "system", "content": "工具调用已达到上限。请基于已获得的信息直接给出最终回答，不要再调用工具。"})
        on_event("model_call", {"phase": "execution_final"})
        message = yield from self._run_model(messages, [], execution_context)
        reasoning_characters = int(message.get("provider_reasoning_characters") or 0)
        if reasoning_characters:
            on_event("provider_reasoning_available", {"characters": reasoning_characters})
        content = (message.get("content") or "").strip()
        if not content:
            raise RuntimeError("工具调用达到上限且模型未返回最终回答")

    def _run_model(self, messages: list[dict], tools: list[dict], execution_context: dict) -> Iterator[str]:
        message = None
        for event in self._dependencies.stream_model(messages, tools, execution_context):
            if event["type"] == "content":
                yield event["text"]
            elif event["type"] == "done":
                message = event["message"]
        if not isinstance(message, dict):
            raise RuntimeError("模型流未返回完成消息")
        return message

    @staticmethod
    def _tool_fingerprint(call: dict) -> str:
        """Stable identity for a read action; malformed calls are handled normally."""
        function = call.get("function", {})
        tool_id = function.get("name", "")
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except (TypeError, json.JSONDecodeError):
            return ""
        if not tool_id or not isinstance(arguments, dict):
            return ""
        return f"{tool_id}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"

    def _execute_tool_call(self, call: dict, allowed_tool_ids: set[str], on_event: Callable[[str, dict], None]) -> dict:
        function = call.get("function", {})
        tool_id = function.get("name", "")
        tool_call_id = call.get("id") or self._dependencies.new_id("toolcall")
        tool = self._dependencies.tools.get(tool_id)
        tool_name = tool.name if tool else tool_id
        started = time.monotonic()
        try:
            arguments = json.loads(function.get("arguments") or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("工具参数必须是对象")
            on_event("tool_call", {
                "tool_call_id": tool_call_id,
                "tool_id": tool_id,
                "tool_name": tool_name,
                "arguments": arguments,
                "purpose": "在已授权范围内补充任务所需信息",
            })
            content = self._dependencies.tools.execute(tool_id, arguments, allowed_tool_ids)
            payload = {
                "tool_call_id": tool_call_id,
                "tool_id": tool_id,
                "tool_name": tool_name,
                "summary": self._dependencies.summarize_tool_result(content),
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
                "evidence_gap_status": "等待后续证据评估",
            }
            if tool_id == "web_search" and isinstance(content.get("sources"), list):
                payload["sources"] = content["sources"][:10]
            on_event("tool_result", payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            content = {"error": str(exc)}
            on_event("tool_error", {
                "tool_call_id": tool_call_id,
                "tool_id": tool_id,
                "tool_name": tool_name,
                "error": str(exc),
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
            })
        return {"tool_call_id": tool_call_id, "tool_id": tool_id, "content": content}
