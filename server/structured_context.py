"""Deterministic, source-linked conversation context for local agent runs."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable, Mapping


KINDS = ("goals", "constraints", "decisions", "entities", "open_questions", "todos")
_CONSTRAINT_MARKERS = ("约束：", "约束:", "必须", "不要", "不能", "不得", "限制", "格式", "只允许", "仅使用")
_DECISION_MARKERS = ("决定", "就用", "最终采用", "确定采用", "选择使用")
_TODO_MARKERS = ("待办", "下一步", "需要完成", "后续处理")
_QUESTION_MARKERS = ("问题：", "问题:", "待确认", "尚未确定", "需要确认", "开放问题")


def _clean(value: object, limit: int = 400) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _item(kind: str, text: str, source: Mapping, status: str = "active") -> dict:
    source_id = _clean(source.get("id"), 120)
    digest = hashlib.sha256(f"{kind}\0{source_id}\0{text}".encode("utf-8")).hexdigest()[:16]
    return {
        "id": f"ctx_{digest}",
        "kind": kind,
        "text": _clean(text),
        "source_message_id": source_id,
        "source_role": _clean(source.get("role"), 20),
        "updated_at": int(source.get("created_at") or 0),
        "status": status,
    }


def _sentences(content: str) -> list[str]:
    return [_clean(part) for part in re.split(r"(?<=[。！？!?；;，,])|\n+", content) if _clean(part)]


def _similar(left: str, right: str) -> bool:
    left = re.sub(r"\W+", "", left.lower())
    right = re.sub(r"\W+", "", right.lower())
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    left_pairs = {left[index:index + 2] for index in range(max(len(left) - 1, 0))}
    right_pairs = {right[index:index + 2] for index in range(max(len(right) - 1, 0))}
    return len(left_pairs & right_pairs) >= 2


class StructuredContextBuilder:
    schema_version = 1

    def build(self, rows: Iterable[Mapping], inherited: Mapping | None = None) -> dict:
        messages = [dict(row) for row in rows]
        local_source_ids = {_clean(row.get("id"), 120) for row in messages}
        context = {"schema_version": self.schema_version, **{kind: [] for kind in KINDS}}
        if inherited:
            for kind in KINDS:
                context[kind] = [
                    dict(item) for item in inherited.get(kind, [])
                    if isinstance(item, dict) and item.get("source_message_id") not in local_source_ids
                ]

        user_messages = [row for row in messages if row.get("role") == "user" and _clean(row.get("content"))]
        if user_messages:
            if not any(item.get("status") == "active" for item in context["goals"]):
                first_content = _clean(user_messages[0]["content"])
                explicit_goal = re.search(r"(?:^|[。；])\s*(?:目标|任务)[:：]\s*([^。；]+)", first_content)
                goal_text = _clean(explicit_goal.group(1)) if explicit_goal else first_content
                context["goals"].append(_item("goals", goal_text, user_messages[0]))
            for row in user_messages:
                match = re.search(r"(?:目标|任务)(?:改为|改成|调整为)[:：]?\s*(.+)", _clean(row["content"]))
                if match:
                    for item in context["goals"]:
                        if item.get("status") == "active":
                            item["status"] = "superseded"
                            item["superseded_by_message_id"] = _clean(row.get("id"), 120)
                    context["goals"].append(_item("goals", _clean(match.group(1)), row))

        for row in user_messages:
            content = _clean(row["content"])
            self._apply_corrections(context, content, row)
            for sentence in _sentences(content):
                if any(marker in sentence for marker in _CONSTRAINT_MARKERS):
                    context["constraints"].append(_item("constraints", sentence, row))
                if any(marker in sentence for marker in _DECISION_MARKERS):
                    context["decisions"].append(_item("decisions", sentence, row))
                if any(marker in sentence for marker in _TODO_MARKERS):
                    context["todos"].append(_item("todos", sentence, row))
                if any(marker in sentence for marker in _QUESTION_MARKERS):
                    context["open_questions"].append(_item("open_questions", sentence, row))
            for label, value in re.findall(r"(项目名|产品名|模型|负责人)[:：]\s*([^，。；\n]+)", content):
                context["entities"].append(_item("entities", f"{label}：{value}", row))

        for kind in KINDS:
            context[kind] = self._deduplicate(context[kind])[-8:]
        context["source_message_count"] = len(local_source_ids)
        return context

    def select(self, context: Mapping, query: str, max_chars: int = 1800) -> dict:
        selected = {"schema_version": self.schema_version, **{kind: [] for kind in KINDS}}
        query_compact = re.sub(r"\W+", "", query.lower())
        used = 0
        for kind in KINDS:
            active = [item for item in context.get(kind, []) if item.get("status") == "active"]
            if kind not in ("goals", "constraints", "decisions"):
                relevant = [item for item in active if _similar(item.get("text", ""), query_compact)]
                active = relevant or active[-2:]
            for item in active:
                cost = len(item.get("text", ""))
                if used + cost > max_chars:
                    break
                selected[kind].append(dict(item))
                used += cost
        selected["injected_chars"] = used
        return selected

    def render(self, context: Mapping, include_sources: bool = False) -> str:
        labels = {
            "goals": "目标", "constraints": "约束", "decisions": "决策", "entities": "实体",
            "open_questions": "开放问题", "todos": "待办",
        }
        lines = []
        for kind in KINDS:
            values = []
            for item in context.get(kind, []):
                if item.get("status") != "active":
                    continue
                suffix = f"（来源 {item.get('source_message_id')}）" if include_sources else ""
                values.append(f"{item.get('text', '')}{suffix}")
            if values:
                lines.append(f"{labels[kind]}：" + "；".join(values))
        return "\n".join(lines)

    def dumps(self, context: Mapping) -> str:
        return json.dumps(context, ensure_ascii=False, separators=(",", ":"))

    def loads(self, value: object) -> dict:
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def _apply_corrections(self, context: dict, content: str, source: Mapping) -> None:
        for match in re.finditer(r"([^，。；]{2,50}?)(?:改为|改成|调整为)([^，。；]{2,80})", content):
            old, new = _clean(match.group(1)), _clean(match.group(2))
            for kind in ("constraints", "decisions", "entities", "todos", "open_questions"):
                self._supersede(context, kind, old, source)
            target = "constraints" if any(marker in new for marker in _CONSTRAINT_MARKERS) else "decisions"
            context[target].append(_item(target, new, source))
        for match in re.finditer(r"(?:取消|不再)([^，。；]{2,80})", content):
            old = _clean(match.group(1))
            for kind in KINDS:
                self._supersede(context, kind, old, source)

    @staticmethod
    def _supersede(context: dict, kind: str, old: str, source: Mapping) -> None:
        for item in context.get(kind, []):
            if item.get("status") == "active" and _similar(item.get("text", ""), old):
                item["status"] = "superseded"
                item["superseded_by_message_id"] = _clean(source.get("id"), 120)

    @staticmethod
    def _deduplicate(items: list[dict]) -> list[dict]:
        result = []
        seen = set()
        for item in items:
            key = (item.get("kind"), item.get("text"), item.get("status"))
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result
