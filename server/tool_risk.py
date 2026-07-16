"""Deterministic risk and confirmation policy for agent tool operations."""

from __future__ import annotations

from dataclasses import dataclass


RISK_LEVELS = ("read_only", "local_write", "external_write", "destructive", "privileged")


@dataclass(frozen=True)
class ToolRiskDecision:
    risk_level: str
    allowed: bool
    requires_confirmation: bool
    reason: str


class ToolRiskPolicy:
    def assess(self, risk_level: str, *, explicitly_requested: bool = False) -> ToolRiskDecision:
        if risk_level not in RISK_LEVELS:
            return ToolRiskDecision(risk_level, False, True, "未知工具风险等级")
        if risk_level == "read_only":
            return ToolRiskDecision(risk_level, True, False, "只读操作可在授权范围内直接执行")
        if risk_level == "privileged" and not explicitly_requested:
            return ToolRiskDecision(risk_level, False, True, "特权操作必须由用户明确发起")
        labels = {
            "local_write": "本地写入必须确认",
            "external_write": "外部写入必须确认",
            "destructive": "破坏性操作必须确认并展示不可逆影响",
            "privileged": "特权操作必须确认",
        }
        return ToolRiskDecision(risk_level, True, True, labels[risk_level])

    def validate_registration(self, risk_level: str, idempotent: bool) -> None:
        decision = self.assess(risk_level)
        if risk_level not in RISK_LEVELS:
            raise ValueError(decision.reason)
        if risk_level in {"local_write", "external_write"} and not idempotent:
            raise ValueError("写工具必须声明幂等能力")
