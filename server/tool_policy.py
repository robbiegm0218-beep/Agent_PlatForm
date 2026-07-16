from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


class ToolCatalog(Protocol):
    def list(self) -> list[dict]: ...


@dataclass(frozen=True)
class ToolDecision:
    tools: list[dict]
    confidence: str
    reason: str


class ToolPolicy:
    """Select the smallest authorized tool surface for a user request.

    The policy is intentionally deterministic. The model never decides its own
    privileges; it receives only definitions selected here, and execution is
    still validated by the tool registry.
    """

    def __init__(self, catalog: ToolCatalog):
        self._catalog = catalog

    def resolve(self, content: str) -> list[dict]:
        return self.decide(content).tools

    def decide(self, content: str) -> ToolDecision:
        read_only_tools = [
            tool for tool in self._catalog.list()
            if tool["enabled"] and tool["risk"] == "read_only"
        ]
        if "平台状态" in content or "系统状态" in content:
            return ToolDecision(self._by_id(read_only_tools, "platform_status"), "high", "明确请求平台状态")

        normalized = content.lower()
        has_lookup_action = any(marker in normalized for marker in (
            "检索", "查找", "搜索", "查询", "查一下", "查一查", "帮我查", "看看", "看一下", "找一下", "找找", "找一些",
        ))
        mentions_file_scope = any(marker in content for marker in ("文件", "工作区", "目录"))
        has_read_action = any(marker in content for marker in ("读取", "打开", "查看内容", "读一下"))
        if has_read_action and mentions_file_scope:
            return ToolDecision(self._by_id(read_only_tools, "read_workspace_file"), "high", "明确请求读取工作区文件内容")
        if has_lookup_action and mentions_file_scope:
            return ToolDecision(self._by_id(read_only_tools, "search_workspace_files"), "high", "明确请求本地文件或工作区检索")

        reasons: list[str] = []
        score = 0
        contains_url = bool(re.search(r"https?://\S+|\bwww\.", content, re.IGNORECASE))
        if contains_url and any(marker in normalized for marker in ("读取", "打开", "查看内容", "总结这个网页", "总结网页")):
            return ToolDecision(self._by_id(read_only_tools, "read_web_page"), "high", "明确请求读取指定网页正文")
        if contains_url:
            score += 4
            reasons.append("包含 URL")
        mentions_web_scope = any(marker in normalized for marker in ("网页", "互联网", "网上", "在线", "联网", "web", "官网", "官方文档"))
        if mentions_web_scope and has_lookup_action:
            score += 4
            reasons.append("明确请求联网或网页查询")
        realtime_subject = any(marker in content for marker in ("天气", "新闻", "价格", "汇率", "比分", "航班", "股价", "票价"))
        temporal_marker = any(marker in content for marker in ("今天", "明天", "现在", "当前", "最新", "实时", "最近"))
        if realtime_subject and (has_lookup_action or temporal_marker):
            score += 3
            reasons.append("请求时效性公开信息")
        external_research = any(marker in content for marker in ("来源", "链接", "引用", "公开资料", "外部资料", "查资料", "找资料", "调研"))
        if external_research and has_lookup_action:
            score += 3
            reasons.append("明确需要外部资料或来源")
        if has_lookup_action and score == 0:
            reasons.append("仅有查询动作，范围不明确")

        if score >= 3:
            return ToolDecision(self._by_id(read_only_tools, "web_search"), "high" if score >= 4 else "medium", "；".join(reasons))
        return ToolDecision([], "none", "；".join(reasons) or "未识别到外部或本地工具意图")

    @staticmethod
    def _by_id(tools: list[dict], tool_id: str) -> list[dict]:
        return [tool for tool in tools if tool["id"] == tool_id]
