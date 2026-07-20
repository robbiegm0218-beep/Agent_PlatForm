"""Explicit, bounded P45 single-agent orchestration state machine.

It has no HTTP, database, prompt or tool implementation dependency.  The
runtime adapter records returned transitions as Run events.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OrchestratorState(str, Enum):
    PLAN = "PLAN"
    COLLECT_EVIDENCE = "COLLECT_EVIDENCE"
    ASSESS_EVIDENCE = "ASSESS_EVIDENCE"
    ACT = "ACT"
    OBSERVE = "OBSERVE"
    REPLAN = "REPLAN"
    DRAFT = "DRAFT"
    VERIFY = "VERIFY"
    REVISE = "REVISE"
    COMPLETE = "COMPLETE"
    CLARIFY = "CLARIFY"
    COMPLETE_WITH_LIMITS = "COMPLETE_WITH_LIMITS"


TERMINAL_STATES = {OrchestratorState.COMPLETE, OrchestratorState.CLARIFY, OrchestratorState.COMPLETE_WITH_LIMITS}
TRANSITIONS = {
    OrchestratorState.PLAN: {OrchestratorState.COLLECT_EVIDENCE, OrchestratorState.DRAFT, OrchestratorState.CLARIFY},
    OrchestratorState.COLLECT_EVIDENCE: {OrchestratorState.ASSESS_EVIDENCE},
    OrchestratorState.ASSESS_EVIDENCE: {OrchestratorState.ACT, OrchestratorState.DRAFT, OrchestratorState.CLARIFY, OrchestratorState.COMPLETE_WITH_LIMITS},
    OrchestratorState.ACT: {OrchestratorState.OBSERVE, OrchestratorState.COMPLETE_WITH_LIMITS},
    OrchestratorState.OBSERVE: {OrchestratorState.REPLAN, OrchestratorState.ASSESS_EVIDENCE, OrchestratorState.DRAFT, OrchestratorState.COMPLETE_WITH_LIMITS},
    OrchestratorState.REPLAN: {OrchestratorState.ASSESS_EVIDENCE, OrchestratorState.DRAFT, OrchestratorState.CLARIFY, OrchestratorState.COMPLETE_WITH_LIMITS},
    OrchestratorState.DRAFT: {OrchestratorState.VERIFY, OrchestratorState.COMPLETE_WITH_LIMITS},
    OrchestratorState.VERIFY: {OrchestratorState.REVISE, OrchestratorState.COMPLETE, OrchestratorState.CLARIFY, OrchestratorState.COMPLETE_WITH_LIMITS},
    OrchestratorState.REVISE: {OrchestratorState.VERIFY, OrchestratorState.COMPLETE_WITH_LIMITS},
}
BUDGETS = {"quick": {"model": 1, "tool": 1, "replan": 0, "revise": 0}, "standard": {"model": 4, "tool": 3, "replan": 1, "revise": 1}, "deep": {"model": 7, "tool": 5, "replan": 1, "revise": 1}}


class OrchestrationError(ValueError): pass

ALLOWED_NEXT_ACTIONS = {"use_tool", "retrieve_knowledge", "clarify_user", "draft_answer", "complete_with_limits"}

def validate_next_action(value: object, allowed_tool_ids: set[str]) -> dict:
    """Validate a model action suggestion; it never grants permissions."""
    if not isinstance(value, dict) or value.get("type") not in ALLOWED_NEXT_ACTIONS:
        raise OrchestrationError("next_action 无效")
    action = {"type": value["type"], "reason": str(value.get("reason", ""))[:240]}
    if action["type"] == "use_tool":
        tool_id = str(value.get("tool_id", ""))
        if tool_id not in allowed_tool_ids: raise OrchestrationError("next_action 请求了未授权工具")
        arguments = value.get("arguments", {})
        if not isinstance(arguments, dict): raise OrchestrationError("next_action 工具参数无效")
        action.update({"tool_id": tool_id, "arguments": arguments})
    return action


@dataclass
class OrchestrationSnapshot:
    state: OrchestratorState
    model_calls: int = 0
    tool_calls: int = 0
    replans: int = 0
    revisions: int = 0


class AgentOrchestrator:
    def __init__(self, tier: str):
        if tier not in BUDGETS: raise OrchestrationError("任务档位无效")
        self.tier, self.snapshot = tier, OrchestrationSnapshot(OrchestratorState.PLAN)

    def transition(self, target: OrchestratorState, *, reason: str) -> dict:
        current = self.snapshot.state
        if target not in TRANSITIONS.get(current, set()): raise OrchestrationError(f"非法状态转换：{current.value} → {target.value}")
        self._consume(target)
        self.snapshot.state = target
        return {"from": current.value, "to": target.value, "reason": reason, "budget": self.budget()}

    def _consume(self, target: OrchestratorState) -> None:
        mapping = {OrchestratorState.REPLAN: "replans", OrchestratorState.REVISE: "revisions"}
        field = mapping.get(target)
        if field:
            limit = BUDGETS[self.tier][{"tool_calls":"tool", "replans":"replan", "revisions":"revise"}[field]]
            if getattr(self.snapshot, field) >= limit: raise OrchestrationError(f"{field} 已达到预算上限")
            setattr(self.snapshot, field, getattr(self.snapshot, field) + 1)

    def record_model_call(self) -> None:
        if self.snapshot.model_calls >= BUDGETS[self.tier]["model"]: raise OrchestrationError("模型调用已达到预算上限")
        self.snapshot.model_calls += 1

    def record_tool_call(self) -> None:
        if self.snapshot.tool_calls >= BUDGETS[self.tier]["tool"]: raise OrchestrationError("工具调用已达到预算上限")
        self.snapshot.tool_calls += 1

    def budget(self) -> dict:
        return {"tier": self.tier, "model_calls": self.snapshot.model_calls, "tool_calls": self.snapshot.tool_calls, "replans": self.snapshot.replans, "revisions": self.snapshot.revisions, "limits": BUDGETS[self.tier]}
