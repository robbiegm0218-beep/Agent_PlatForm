from __future__ import annotations

"""Validation and task-scoped loading rules for reusable skill packages."""

import re
from pathlib import PurePosixPath
from typing import Any


RESOURCE_PREFIXES = ("references/", "assets/")


def normalize_skill_contract(skill: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(skill, dict):
        raise ValueError("技能包 JSON 必须是对象")
    normalized = dict(skill)
    normalized.setdefault("kind", "prompt_skill")
    normalized.setdefault("tool_ids", [])
    normalized.setdefault("scope_policy_tools", False)
    normalized.setdefault("triggers", {"terms": [], "patterns": []})
    normalized.setdefault("input_schema", {"type": "object"})
    normalized.setdefault("output_schema", {"type": "object"})
    normalized.setdefault("steps", [])
    normalized.setdefault("acceptance_rules", [])
    normalized.setdefault("eval_cases", [])
    normalized.setdefault("resources", [])

    triggers = normalized["triggers"]
    if not isinstance(triggers, dict):
        raise ValueError("技能触发条件必须是对象")
    terms = triggers.get("terms", [])
    patterns = triggers.get("patterns", [])
    if not _string_list(terms) or not _string_list(patterns):
        raise ValueError("技能触发词和正则必须是文本列表")
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError("技能触发正则无效") from exc
    normalized["triggers"] = {"terms": terms, "patterns": patterns}

    for field in ("input_schema", "output_schema"):
        schema = normalized[field]
        if not isinstance(schema, dict) or schema.get("type", "object") != "object":
            raise ValueError(f"{field} 必须是对象 Schema")
    if not _string_list(normalized["steps"]):
        raise ValueError("技能步骤必须是文本列表")
    if not _string_list(normalized["acceptance_rules"]):
        raise ValueError("技能验收规则必须是文本列表")
    if not isinstance(normalized["eval_cases"], list) or not all(isinstance(case, dict) for case in normalized["eval_cases"]):
        raise ValueError("技能评测用例必须是对象列表")
    if not _string_list(normalized["resources"]):
        raise ValueError("技能资源清单必须是文本列表")
    if not isinstance(normalized["scope_policy_tools"], bool):
        raise ValueError("技能工具收窄开关必须是布尔值")
    for resource in normalized["resources"]:
        path = PurePosixPath(resource)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("技能资源路径无效")
    return normalized


def skill_matches(skill: dict[str, Any], content: str) -> bool:
    triggers = skill.get("triggers", {})
    terms = triggers.get("terms", [])
    patterns = triggers.get("patterns", [])
    if not terms and not patterns:
        return True
    lowered = content.lower()
    return any(term.lower() in lowered for term in terms) or any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)


def loadable_resource_paths(skill: dict[str, Any], content: str) -> list[str]:
    if not skill_matches(skill, content):
        return []
    return [path for path in skill.get("resources", []) if path.startswith(RESOURCE_PREFIXES)]


def restrict_tools(skills: list[dict[str, Any]], policy_tool_ids: set[str]) -> set[str]:
    tool_skills = [
        skill for skill in skills
        if skill.get("kind") == "tool_skill" and skill.get("scope_policy_tools", False)
    ]
    if not tool_skills:
        return set(policy_tool_ids)
    declared = {tool_id for skill in tool_skills for tool_id in skill.get("tool_ids", [])}
    return set(policy_tool_ids) & declared


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and bool(item.strip()) for item in value)
