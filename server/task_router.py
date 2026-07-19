"""Deterministic, explainable task and model routing.

This module classifies task complexity and evidence needs. Tool authorization
remains owned by ToolPolicy; TaskRouter can observe that decision but can never
grant a tool by itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


TASK_TIERS = {"quick", "standard", "deep"}


def classify_knowledge_intent(content: str) -> dict:
    """Return whether local evidence should be retrieved for this request."""
    normalized = re.sub(r"\s+", "", content.lower())
    local_source_markers = ("知识库", "本地资料", "上传资料", "参考资料", "附件", "文档中", "材料中")
    if any(marker in normalized for marker in local_source_markers):
        return {"needed": True, "reason": "explicit_local_source"}
    if re.search(r"(?:根据|基于|查阅|引用|检索).{0,10}(?:资料|文档|材料|来源)", normalized):
        return {"needed": True, "reason": "explicit_local_source"}

    operational_markers = ("平台", "技能", "模型", "版本", "接口", "服务", "对话", "文件夹", "改动范围", "今天", "星期", "代码")
    # Broad suffixes such as “是什么” and “说明” often describe a general
    # explanation, not a request for private knowledge.  Keep local retrieval
    # for explicit definitions and factual comparisons, where evidence is more
    # likely to improve the answer.
    factual_markers = ("什么是", "定义", "含义", "介绍", "多少", "数据", "指标", "事实")
    factual_comparison = "说明" in normalized and "比较" in normalized
    if (
        len(normalized) >= 5
        and (any(marker in normalized for marker in factual_markers) or factual_comparison)
        and not any(marker in normalized for marker in operational_markers)
    ):
        return {"needed": True, "reason": "factual_query"}
    return {"needed": False, "reason": "not_recognized"}


@dataclass(frozen=True)
class TaskRoute:
    model: str
    task_tier: str
    model_route: str
    model_route_reason: str
    needs_tools: bool
    needs_knowledge: bool
    knowledge_intent: dict
    max_output_tokens: int
    quality_check: bool
    confidence: str
    reasons: tuple[str, ...]
    task_mode_source: str

    def as_profile(self) -> dict:
        return {
            "model": self.model,
            "task_tier": self.task_tier,
            "route": self.model_route,
            "reason": self.model_route_reason,
            "needs_tools": self.needs_tools,
            "needs_knowledge": self.needs_knowledge,
            "knowledge_intent": self.knowledge_intent,
            "max_output_tokens": self.max_output_tokens,
            "quality_check": self.quality_check,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "task_mode_source": self.task_mode_source,
        }


class TaskRouter:
    """Choose task tier and model while treating ToolPolicy as authoritative."""

    DEEP_MARKERS = ("调研", "方案", "报告", "深度", "全面", "竞品", "商业计划", "架构设计", "复盘", "证明", "取舍", "权衡", "可行性")
    STANDARD_MARKERS = ("改写", "撰写", "写一", "代码", "分析", "待办", "负责人", "设计")
    SIMPLE_TRANSFORM_MARKERS = ("翻译", "提取")

    def __init__(
        self,
        model_catalog: dict,
        default_model: str,
        deep_model: str,
        tool_decision: Callable[[str], object],
        knowledge_classifier: Callable[[str], dict] = classify_knowledge_intent,
    ) -> None:
        self._model_catalog = model_catalog
        self._default_model = default_model
        self._deep_model = deep_model
        self._tool_decision = tool_decision
        self._knowledge_classifier = knowledge_classifier

    def route(
        self,
        content: str,
        requested_model: str = "auto",
        requested_task_mode: str = "auto",
    ) -> TaskRoute:
        if requested_task_mode != "auto" and requested_task_mode not in TASK_TIERS:
            raise ValueError("task mode must be auto, quick, standard, or deep")

        tool_decision = self._tool_decision(content)
        needs_tools = bool(getattr(tool_decision, "tools", []))
        knowledge_intent = self._knowledge_classifier(content)
        needs_knowledge = bool(knowledge_intent["needed"])

        reasons: list[str] = []
        deep_matches = [marker for marker in self.DEEP_MARKERS if marker in content]
        standard_matches = [marker for marker in self.STANDARD_MARKERS if marker in content]
        simple_transform = next((marker for marker in self.SIMPLE_TRANSFORM_MARKERS if marker in content), "")
        if simple_transform and not deep_matches:
            task_tier = "quick"
            reasons.append(f"确定性转换任务：{simple_transform}")
        elif deep_matches:
            task_tier = "deep"
            reasons.append(f"复杂任务标记：{'、'.join(deep_matches[:3])}")
        elif standard_matches:
            task_tier = "standard"
            reasons.append(f"结构化任务标记：{'、'.join(standard_matches[:3])}")
        elif len(content) >= 80:
            task_tier = "deep"
            reasons.append("输入长度达到复杂任务阈值")
        elif len(content) < 32:
            task_tier = "quick"
            reasons.append("短输入且无复杂任务标记")
        else:
            task_tier = "standard"
            reasons.append("采用标准任务档位")

        task_mode_source = "automatic"
        if requested_task_mode != "auto":
            task_tier = requested_task_mode
            task_mode_source = "user_override"
            reasons.append(f"用户指定任务档位：{requested_task_mode}")

        if needs_tools:
            reasons.append(f"工具策略：{getattr(tool_decision, 'reason', '已授权只读工具')}")
        if needs_knowledge:
            reasons.append(f"知识路由：{knowledge_intent['reason']}")

        if requested_model != "auto":
            model = requested_model
            model_route = "manual"
            model_reason = "用户手动选择模型"
            reasons.append(model_reason)
        elif task_tier == "deep" and not needs_tools:
            model = self._deep_model
            model_route = "automatic"
            model_reason = "复杂任务使用高质量模型"
        else:
            model = self._default_model
            model_route = "automatic"
            model_reason = "普通或工具任务使用快速工具兼容模型"

        profile = self._model_catalog[model]
        if needs_tools and not profile["supports_tools"]:
            model = self._default_model
            profile = self._model_catalog[model]
            model_route = "fallback"
            model_reason = "任务需要工具调用，已切换到工具兼容模型"
            reasons.append(model_reason)

        if requested_task_mode != "auto" and model_route == "automatic":
            model_route = "manual_task_mode"

        confidence = "high" if requested_task_mode != "auto" or requested_model != "auto" or deep_matches or standard_matches else "medium"
        if needs_tools:
            confidence = getattr(tool_decision, "confidence", confidence)

        return TaskRoute(
            model=model,
            task_tier=task_tier,
            model_route=model_route,
            model_route_reason=model_reason,
            needs_tools=needs_tools,
            needs_knowledge=needs_knowledge,
            knowledge_intent=knowledge_intent,
            max_output_tokens=profile["max_output_tokens"][task_tier],
            quality_check=task_tier == "deep",
            confidence=confidence,
            reasons=tuple(reasons),
            task_mode_source=task_mode_source,
        )
