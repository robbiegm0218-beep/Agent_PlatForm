"""Safe, structured task framing for the P45 shadow planner.

This module deliberately does not make permission decisions.  It turns either a
model response or a deterministic fallback into a small, auditable TaskFrame
that later orchestration stages may consume.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


TASK_FRAME_VERSION = 1
MAX_TEXT_LENGTH = 360
MAX_ITEMS = 8
ALLOWED_ACTIONS = {"retrieve", "tool", "clarify", "draft"}
ALLOWED_SOURCES = {"knowledge", "workspace", "web", "user", "memory", "tool"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}


class TaskFrameValidationError(ValueError):
    """Raised when an untrusted model response does not meet the contract."""


@dataclass(frozen=True)
class PlanningResult:
    frame: dict
    status: str
    fallback_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "frame": self.frame,
            "status": self.status,
            "fallback_reason": self.fallback_reason,
        }


def _text(value: Any, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise TaskFrameValidationError(f"{field} 必须是文本")
    normalized = re.sub(r"\s+", " ", value).strip()
    if required and not normalized:
        raise TaskFrameValidationError(f"{field} 不能为空")
    if len(normalized) > MAX_TEXT_LENGTH:
        raise TaskFrameValidationError(f"{field} 超出长度限制")
    return normalized


def _items(value: Any, field: str) -> list[dict]:
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise TaskFrameValidationError(f"{field} 必须是最多 {MAX_ITEMS} 项的列表")
    return value


def validate_task_frame(value: Any) -> dict:
    """Validate and normalize the only TaskFrame shape persisted by the app."""
    if not isinstance(value, dict):
        raise TaskFrameValidationError("TaskFrame 必须是对象")
    if value.get("version") != TASK_FRAME_VERSION:
        raise TaskFrameValidationError("TaskFrame 版本不支持")
    deliverables = []
    for index, item in enumerate(_items(value.get("deliverables"), "deliverables"), start=1):
        if not isinstance(item, dict):
            raise TaskFrameValidationError("deliverables 项必须是对象")
        deliverables.append({
            "id": _text(item.get("id"), f"deliverables[{index}].id"),
            "description": _text(item.get("description"), f"deliverables[{index}].description"),
            "required": bool(item.get("required", False)),
        })
    if not deliverables:
        raise TaskFrameValidationError("至少需要一个交付物")
    constraints = []
    for index, item in enumerate(_items(value.get("constraints", []), "constraints"), start=1):
        if not isinstance(item, dict) or item.get("source") not in {"user", "context", "policy"}:
            raise TaskFrameValidationError("constraints 项无效")
        constraints.append({
            "id": _text(item.get("id"), f"constraints[{index}].id"),
            "description": _text(item.get("description"), f"constraints[{index}].description"),
            "source": item["source"],
        })
    requirements = []
    for index, item in enumerate(_items(value.get("evidence_requirements", []), "evidence_requirements"), start=1):
        if not isinstance(item, dict):
            raise TaskFrameValidationError("evidence_requirements 项必须是对象")
        sources = item.get("preferred_sources", [])
        if not isinstance(sources, list) or any(source not in ALLOWED_SOURCES for source in sources):
            raise TaskFrameValidationError("evidence_requirements 来源无效")
        requirements.append({
            "id": _text(item.get("id"), f"evidence_requirements[{index}].id"),
            "description": _text(item.get("description"), f"evidence_requirements[{index}].description"),
            "preferred_sources": list(dict.fromkeys(sources)),
        })
    actions = []
    for index, item in enumerate(_items(value.get("proposed_actions", []), "proposed_actions"), start=1):
        if not isinstance(item, dict) or item.get("type") not in ALLOWED_ACTIONS:
            raise TaskFrameValidationError("proposed_actions 类型无效")
        actions.append({"type": item["type"], "reason": _text(item.get("reason"), f"proposed_actions[{index}].reason")})
    criteria = []
    for index, item in enumerate(_items(value.get("acceptance_criteria"), "acceptance_criteria"), start=1):
        if not isinstance(item, dict):
            raise TaskFrameValidationError("acceptance_criteria 项必须是对象")
        criteria.append({
            "id": _text(item.get("id"), f"acceptance_criteria[{index}].id"),
            "description": _text(item.get("description"), f"acceptance_criteria[{index}].description"),
        })
    if not criteria:
        raise TaskFrameValidationError("至少需要一个验收标准")
    ambiguities = [_text(item, "ambiguities 项") for item in _items(value.get("ambiguities", []), "ambiguities")]
    confidence = value.get("confidence")
    if confidence not in ALLOWED_CONFIDENCE:
        raise TaskFrameValidationError("confidence 无效")
    return {
        "version": TASK_FRAME_VERSION,
        "goal": _text(value.get("goal"), "goal"),
        "deliverables": deliverables,
        "constraints": constraints,
        "evidence_requirements": requirements,
        "proposed_actions": actions,
        "acceptance_criteria": criteria,
        "ambiguities": list(dict.fromkeys(ambiguities)),
        "confidence": confidence,
    }


def parse_task_frame(text: str) -> dict:
    """Parse a model response without accepting prose around the JSON object."""
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise TaskFrameValidationError("规划模型未返回合法 JSON") from exc
    return validate_task_frame(value)


def fallback_task_frame(content: str, *, intent_plan: dict, execution_modes: dict, task_confidence: str) -> dict:
    """Create a conservative frame when planning is disabled or unavailable."""
    normalized = _text(content, "goal")
    constraints = [
        {"id": "c_user_request", "description": "以用户本轮请求为准", "source": "user"},
        {"id": "c_policy", "description": "仅使用平台已授权的资料范围和工具", "source": "policy"},
    ]
    requirements = []
    actions = []
    if intent_plan.get("knowledge_needed") or execution_modes.get("knowledge") == "required":
        requirements.append({"id": "e_local", "description": "核对与任务相关的本地资料依据", "preferred_sources": ["knowledge"]})
        actions.append({"type": "retrieve", "reason": "任务需要或用户要求本地资料依据"})
    if intent_plan.get("clarification_needed"):
        actions.append({"type": "clarify", "reason": "任务范围或所需资料尚不明确"})
    actions.append({"type": "draft", "reason": "在已授权上下文内形成回答"})
    return validate_task_frame({
        "version": TASK_FRAME_VERSION,
        "goal": normalized,
        "deliverables": [{"id": "d_answer", "description": "直接回应用户目标的最终回答", "required": True}],
        "constraints": constraints,
        "evidence_requirements": requirements,
        "proposed_actions": actions,
        "acceptance_criteria": [{"id": "a_goal", "description": "回答覆盖用户目标并说明关键限制"}],
        "ambiguities": ["需要补充任务范围或资料时先明确缺口"] if intent_plan.get("clarification_needed") else [],
        "confidence": task_confidence if task_confidence in ALLOWED_CONFIDENCE else "medium",
    })


def planning_prompt() -> str:
    return (
        "你是 Agent_Platform 的任务规划器。只返回一个合法 JSON 对象，不得包含 Markdown、解释、"
        "系统提示、权限决定、工具参数或私有推理。JSON 必须符合 TaskFrame v1："
        "version、goal、deliverables、constraints、evidence_requirements、proposed_actions、"
        "acceptance_criteria、ambiguities、confidence。proposed_actions.type 仅可为 "
        "retrieve、tool、clarify、draft；它们只是建议，不能授予能力。"
    )


def task_frame_summary(frame: dict) -> dict:
    """A compact event payload: no prompt, user IDs, or unbounded text."""
    return {
        "version": frame["version"],
        "goal": frame["goal"][:160],
        "deliverable_count": len(frame["deliverables"]),
        "evidence_requirement_count": len(frame["evidence_requirements"]),
        "action_types": [item["type"] for item in frame["proposed_actions"]],
        "ambiguity_count": len(frame["ambiguities"]),
        "confidence": frame["confidence"],
    }
