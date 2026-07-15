from __future__ import annotations

from typing import Protocol


class ToolCatalog(Protocol):
    def list(self) -> list[dict]: ...


class ToolPolicy:
    """Select the smallest authorized tool surface for a user request.

    The policy is intentionally deterministic. The model never decides its own
    privileges; it receives only definitions selected here, and execution is
    still validated by the tool registry.
    """

    def __init__(self, catalog: ToolCatalog):
        self._catalog = catalog

    def resolve(self, content: str) -> list[dict]:
        read_only_tools = [
            tool for tool in self._catalog.list()
            if tool["enabled"] and tool["risk"] == "read_only"
        ]
        if "平台状态" in content or "系统状态" in content:
            return self._by_id(read_only_tools, "platform_status")
        has_search_verb = any(marker in content for marker in ("检索", "查找", "搜索"))
        mentions_file_scope = any(marker in content for marker in ("文件", "工作区", "目录"))
        if has_search_verb and mentions_file_scope:
            return self._by_id(read_only_tools, "search_workspace_files")
        return []

    @staticmethod
    def _by_id(tools: list[dict], tool_id: str) -> list[dict]:
        return [tool for tool in tools if tool["id"] == tool_id]
