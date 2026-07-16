"""Validation, candidate extraction and deterministic selection for explicit memories."""

from __future__ import annotations

import re
from typing import Iterable, Mapping


MEMORY_KINDS = ("preference", "project_fact", "decision")
MEMORY_STATUSES = ("active", "disabled")
MEMORY_SCOPES = ("global", "project")

_SENSITIVE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I),
    re.compile(r"(?:password|passwd|secret|api[_ -]?key|access[_ -]?token)\s*[:=]\s*\S+", re.I),
    re.compile(r"(?:密码|密钥|令牌)\s*[:：=]\s*\S+"),
    re.compile(r"\b(?:sk|ghp|xox[baprs])[-_][A-Za-z0-9_-]{12,}\b"),
)


def validate_memory_content(value: object) -> str:
    content = re.sub(r"\s+", " ", str(value or "")).strip()
    if not content:
        raise ValueError("记忆内容不能为空")
    if len(content) > 500:
        raise ValueError("记忆内容不能超过 500 个字符")
    if any(pattern.search(content) for pattern in _SENSITIVE_PATTERNS):
        raise ValueError("记忆内容疑似包含密码、密钥或令牌，已拒绝保存")
    return content


def extract_candidates(content: object, source_message_id: str = "") -> list[dict]:
    text = re.sub(r"\s+", " ", str(content or "")).strip()
    candidates = []
    patterns = (
        ("preference", r"(?:请记住|我的偏好是|我偏好)[:：]?\s*([^。；\n]+)"),
        ("project_fact", r"(?:项目事实|事实记录)[:：]\s*([^。；\n]+)"),
        ("decision", r"(?:长期决定|决定记住)[:：]\s*([^。；\n]+)"),
    )
    for kind, pattern in patterns:
        for match in re.finditer(pattern, text):
            try:
                candidate = validate_memory_content(match.group(1))
            except ValueError:
                continue
            candidates.append({
                "kind": kind,
                "content": candidate,
                "source_message_id": source_message_id,
                "requires_confirmation": True,
            })
    return candidates[:5]


def _terms(value: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())
    english = set(re.findall(r"[a-z0-9_]{2,}", value.lower()))
    chinese = {normalized[index:index + 2] for index in range(max(0, len(normalized) - 1))}
    return english | chinese


def select_memories(
    records: Iterable[Mapping], query: str, project_id: str = "", limit: int = 6, max_chars: int = 1200,
    now_value: int = 0,
) -> list[dict]:
    query_terms = _terms(query)
    ranked = []
    for record in records:
        row = dict(record)
        if row.get("status") != "active":
            continue
        if now_value and int(row.get("expires_at") or 0) and int(row["expires_at"]) <= now_value:
            continue
        if row.get("scope_type") == "project" and row.get("scope_id") != project_id:
            continue
        content_terms = _terms(str(row.get("content", "")))
        overlap = len(query_terms & content_terms)
        preference_prior = 1 if row.get("kind") == "preference" and row.get("scope_type") == "global" else 0
        if overlap == 0 and not preference_prior:
            continue
        ranked.append((overlap, preference_prior, int(row.get("updated_at") or 0), str(row.get("id", "")), row))
    ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
    selected = []
    used = 0
    for _overlap, _prior, _updated, _identifier, row in ranked:
        content = str(row.get("content", ""))
        if len(selected) >= limit or used + len(content) > max_chars:
            break
        selected.append({
            "id": str(row.get("id", "")),
            "kind": str(row.get("kind", "")),
            "content": content,
            "scope_type": str(row.get("scope_type", "global")),
            "scope_id": str(row.get("scope_id", "")),
            "source_message_id": str(row.get("source_message_id", "")),
        })
        used += len(content)
    return selected
