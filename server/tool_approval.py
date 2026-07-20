"""Safe, persistent approval payloads for non-read-only tool calls."""
from __future__ import annotations

import json
from typing import Any

from server.tool_risk import ToolRiskPolicy


def approval_preview(
    *,
    tool_id: str,
    tool_name: str,
    risk_level: str,
    arguments: dict[str, Any],
    visible_argument_keys: set[str] | frozenset[str] = frozenset(),
    effect_summary: str,
    rollback_summary: str,
    idempotency_key: str,
) -> dict[str, str]:
    """Build the only tool arguments safe to persist and send to the client.

    The caller must explicitly opt fields into ``visible_argument_keys``. All
    other values remain in the executor boundary and are never copied into an
    approval record, event, or browser response.
    """
    decision = ToolRiskPolicy().assess(risk_level)
    if not decision.requires_confirmation or not decision.allowed:
        raise ValueError("只有已授权的风险工具可以创建审批请求")
    if not isinstance(arguments, dict):
        raise ValueError("工具参数必须是对象")
    visible = {
        key: _safe_value(arguments[key])
        for key in sorted(visible_argument_keys)
        if key in arguments
    }
    request = f"确认执行“{tool_name or tool_id}”吗？{decision.reason}。"
    return {
        "request": request,
        "risk_level": risk_level,
        "tool_id": tool_id,
        "arguments_json": json.dumps(visible, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "effect_summary": str(effect_summary or tool_name or tool_id)[:500],
        "rollback_summary": str(rollback_summary)[:500],
        "idempotency_key": str(idempotency_key)[:255],
    }


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:160]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) or isinstance(value, float):
        return value
    if isinstance(value, list):
        return [_safe_value(item) for item in value[:10]]
    return "[结构化参数]"
