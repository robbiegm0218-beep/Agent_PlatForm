from __future__ import annotations

"""Local-only extension points for models, tools, and simple workflows."""
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Callable, Protocol

try:
    from server.tool_risk import ToolRiskPolicy
except ModuleNotFoundError:
    from tool_risk import ToolRiskPolicy


class ModelAdapter(Protocol):
    name: str

    def stream(self, system_prompt: str, messages: list[dict]): ...


@dataclass
class CallableModelAdapter:
    name: str
    stream_fn: Callable

    def stream(self, system_prompt: str, messages: list[dict]):
        yield from self.stream_fn(system_prompt, messages)


@dataclass(frozen=True)
class LocalTool:
    id: str
    name: str
    description: str
    risk: str = "read_only"
    enabled: bool = True
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    timeout_seconds: int = 5
    execute_fn: Callable[[dict], dict] | None = None
    idempotent: bool = True
    effect_summary: str = ""
    rollback_summary: str = ""


class LocalToolRegistry:
    """Lists and executes bounded, opt-in local tools."""

    def __init__(self, tools: list[LocalTool]):
        risk_policy = ToolRiskPolicy()
        for tool in tools:
            risk_policy.validate_registration(tool.risk, tool.idempotent)
        self._tools = {tool.id: tool for tool in tools}

    def list(self) -> list[dict]:
        return [self.public_definition(tool) for tool in self._tools.values()]

    def public_definition(self, tool: LocalTool) -> dict:
        return {
            "id": tool.id,
            "name": tool.name,
            "description": tool.description,
            "risk": tool.risk,
            "enabled": tool.enabled,
            "input_schema": tool.input_schema or {"type": "object", "properties": {}},
            "output_schema": tool.output_schema or {"type": "object"},
            "timeout_seconds": tool.timeout_seconds,
            "requires_confirmation": ToolRiskPolicy().assess(tool.risk).requires_confirmation,
            "idempotent": tool.idempotent,
            "effect_summary": tool.effect_summary or tool.description,
            "rollback_summary": tool.rollback_summary,
        }

    def get(self, tool_id: str) -> LocalTool | None:
        return self._tools.get(tool_id)

    def callable_definitions(self, allowed_ids: set[str], confirmed_ids: set[str] | None = None) -> list[dict]:
        definitions = []
        for tool_id in allowed_ids:
            tool = self.get(tool_id)
            requires_confirmation = ToolRiskPolicy().assess(tool.risk).requires_confirmation if tool else True
            if tool and tool.enabled and tool.execute_fn and (
                not requires_confirmation or tool_id in (confirmed_ids or set())
            ):
                definitions.append({
                    "type": "function",
                    "function": {
                        "name": tool.id,
                        "description": tool.description,
                        "parameters": tool.input_schema or {"type": "object", "properties": {}},
                    },
                })
        return definitions

    def execute(self, tool_id: str, arguments: dict, allowed_ids: set[str], confirmed_ids: set[str] | None = None) -> dict:
        tool = self.get(tool_id)
        if tool_id not in allowed_ids or not tool or not tool.enabled or not tool.execute_fn:
            raise ValueError("工具未启用或未获授权")
        decision = ToolRiskPolicy().assess(tool.risk)
        if decision.requires_confirmation and tool_id not in (confirmed_ids or set()):
            raise ValueError("工具操作需要用户确认")
        if not isinstance(arguments, dict):
            raise ValueError("工具参数必须是对象")
        self._validate_arguments(arguments, tool.input_schema or {})
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(tool.execute_fn, arguments)
            try:
                result = future.result(timeout=tool.timeout_seconds)
            except TimeoutError as exc:
                raise ValueError("工具执行超时") from exc
        if not isinstance(result, dict):
            raise ValueError("工具返回结果无效")
        return result

    @staticmethod
    def _validate_arguments(arguments: dict, schema: dict) -> None:
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        missing = [key for key in required if key not in arguments]
        if missing:
            raise ValueError(f"工具缺少参数：{', '.join(missing)}")
        if schema.get("additionalProperties") is False:
            unexpected = set(arguments) - set(properties)
            if unexpected:
                raise ValueError("工具包含未声明参数")
        for key, value in arguments.items():
            expected_type = properties.get(key, {}).get("type")
            if expected_type == "string" and not isinstance(value, str):
                raise ValueError(f"工具参数 {key} 必须是文本")
            if expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"工具参数 {key} 必须是整数")


class LocalWorkflowRunner:
    """Runs a bounded sequence of in-memory steps without a queue service."""

    def run(self, value, steps: list[Callable]):
        for step in steps:
            value = step(value)
        return value
