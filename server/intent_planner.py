"""Conservative, structured intent planning before execution.

This is deliberately separate from permission policy: it can recommend
evidence retrieval, but can never grant a tool or override a user choosing
``off``.  Its stable output is also a future seam for a model-assisted planner.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntentPlan:
    knowledge_needed: bool
    confidence: str
    reasons: tuple[str, ...]
    clarification_needed: bool = False

    def as_dict(self) -> dict:
        return {
            "knowledge_needed": self.knowledge_needed,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "clarification_needed": self.clarification_needed,
        }


class IntentPlanner:
    """Detect explicit and implicit evidence needs without authorizing tools."""

    _IMPLICIT_LOCAL_MARKERS = (
        "这份", "这套", "该项目", "当前项目", "当前空间", "空间里", "已有资料", "内部资料",
        "公司制度", "公司流程", "项目方案", "项目里", "已有材料", "已有文档", "之前的", "上述", "上面的", "刚才的文档",
    )
    _QUESTION_MARKERS = ("哪些", "什么", "如何", "怎么", "说明", "总结", "归纳", "分析", "风险", "差异", "是否")

    def plan(self, content: str, task_profile: dict) -> IntentPlan:
        normalized = "".join(content.lower().split())
        if task_profile.get("needs_knowledge"):
            return IntentPlan(True, "high", ("任务路由识别到明确资料需求",))
        implicit = [marker for marker in self._IMPLICIT_LOCAL_MARKERS if marker in normalized]
        asks_for_answer = any(marker in normalized for marker in self._QUESTION_MARKERS)
        if implicit and asks_for_answer:
            return IntentPlan(True, "medium", (f"隐式本地证据语义：{implicit[0]}",))
        if len(normalized) >= 18 and any(marker in normalized for marker in ("内容", "情况", "规范", "记录")):
            return IntentPlan(False, "low", ("任务可能依赖上下文，但缺少可确认的资料范围",), True)
        return IntentPlan(False, "high", ("未识别到本地证据需求",))
