"""P45 knowledge-only evidence ledger.

The ledger contains source metadata rather than copied document text.  It is a
decision aid; all access checks remain in the existing knowledge service.
"""
from __future__ import annotations

import json
from server.knowledge_retrieval import query_terms


EVIDENCE_VERSION = 1
ALLOWED_DECISIONS = {"sufficient", "retrieve_more", "clarify", "answer_with_limits"}


def _requirements(task_frame: dict | None, knowledge_needed: bool) -> list[dict]:
    frame_requirements = (task_frame or {}).get("evidence_requirements", [])
    requirements = [item for item in frame_requirements if isinstance(item, dict) and item.get("id")]
    if requirements:
        return requirements
    if knowledge_needed:
        return [{"id": "e_legacy_knowledge", "description": "核对与任务相关的本地资料依据", "preferred_sources": ["knowledge"]}]
    return []


def build_knowledge_ledger(task_frame: dict | None, references: list[dict], *, knowledge_needed: bool) -> dict:
    """Map permitted retrieval results to requirement coverage deterministically."""
    requirements = _requirements(task_frame, knowledge_needed)
    items = []
    requirement_rows = []
    for requirement in requirements:
        requirement_terms = query_terms(requirement["description"])
        meaningful_terms = [term for term in requirement_terms if term not in {"资料", "依据", "相关", "任务", "本地"}]
        supporting = []
        for reference in references:
            matched = set(reference.get("matched_terms", []))
            is_generic = requirement["id"] == "e_legacy_knowledge" or not meaningful_terms
            required_matches = min(2, len(meaningful_terms))
            supports = is_generic or len(matched.intersection(meaningful_terms)) >= required_matches
            if supports:
                source_id = f"{reference.get('document_id', '')}:{reference.get('position', 0)}"
                supporting.append(source_id)
                items.append({
                    "id": f"ev:{source_id}:{requirement['id']}", "source_type": "knowledge", "source_id": source_id,
                    "supports": [requirement["id"]],
                    "relevance": "high" if reference.get("score", 0) >= 2 else "medium",
                    "freshness": "unknown", "permission_checked": True,
                })
        requirement_rows.append({
            "id": requirement["id"],
            "status": "covered" if supporting else "missing",
            "source_ids": supporting,
            "preferred_sources": list(requirement.get("preferred_sources", ["knowledge"])),
        })
    missing = [item["id"] for item in requirement_rows if item["status"] == "missing"]
    if not requirements or not missing:
        decision = "sufficient"
    elif references:
        decision = "retrieve_more"
    else:
        decision = "retrieve_more" if knowledge_needed else "answer_with_limits"
    return {
        "version": EVIDENCE_VERSION,
        "requirements": requirement_rows,
        "items": items,
        "decision": decision,
        "missing_requirement_ids": missing,
    }


def rewrite_queries(task_frame: dict | None, ledger: dict, original_query: str) -> list[str]:
    """Bounded deterministic alternatives; never expands scope or permissions."""
    descriptions = {item["id"]: item.get("description", "") for item in (task_frame or {}).get("evidence_requirements", [])}
    queries = []
    for requirement_id in ledger.get("missing_requirement_ids", [])[:2]:
        candidate = " ".join(query_terms(descriptions.get(requirement_id, ""))[:8]).strip()
        if candidate and candidate != original_query:
            queries.append(candidate)
    return list(dict.fromkeys(queries))[:2]


def ledger_summary(ledger: dict) -> dict:
    return {
        "version": ledger["version"], "decision": ledger["decision"],
        "requirement_count": len(ledger["requirements"]), "item_count": len(ledger["items"]),
        "missing_requirement_ids": ledger["missing_requirement_ids"],
    }


def source_item(source_type: str, source_id: str, supports: list[str], *, relevance: str = "medium", freshness: str = "unknown") -> dict:
    """Normalize one already-authorized source without retaining its body."""
    if source_type not in {"knowledge", "workspace", "web", "user", "memory", "tool"}:
        raise ValueError("证据来源类型无效")
    if not source_id or not isinstance(supports, list):
        raise ValueError("证据来源标识或需求映射无效")
    return {"id": f"ev:{source_type}:{source_id}", "source_type": source_type, "source_id": source_id[:240], "supports": list(dict.fromkeys(str(item) for item in supports if item)), "relevance": relevance if relevance in {"high", "medium", "low"} else "medium", "freshness": freshness if freshness in {"current", "unknown", "stale"} else "unknown", "permission_checked": True}


def append_authorized_observations(ledger: dict, observations: list[dict]) -> dict:
    """Append metadata from authorized tools or sources; never accepts source text."""
    merged = {**ledger, "items": list(ledger.get("items", []))}
    seen = {item["id"] for item in merged["items"]}
    for observation in observations:
        item = source_item(observation.get("source_type", ""), str(observation.get("source_id", "")), observation.get("supports", []), relevance=observation.get("relevance", "medium"), freshness=observation.get("freshness", "unknown"))
        if item["id"] not in seen:
            merged["items"].append(item); seen.add(item["id"])
    return reassess_ledger(merged)


def reassess_ledger(ledger: dict) -> dict:
    """Recompute coverage after new authorized evidence without model self-approval."""
    merged = {**ledger, "requirements": [dict(item) for item in ledger.get("requirements", [])]}
    items = merged.get("items", [])
    missing: list[str] = []
    for requirement in merged["requirements"]:
        allowed_sources = set(requirement.get("preferred_sources", ["knowledge"]))
        supporting = [item["source_id"] for item in items if requirement["id"] in item.get("supports", []) and item.get("source_type") in allowed_sources]
        requirement["source_ids"] = list(dict.fromkeys(supporting))
        requirement["status"] = "covered" if supporting else "missing"
        if not supporting:
            missing.append(requirement["id"])
    merged["missing_requirement_ids"] = missing
    merged["decision"] = "sufficient" if not missing else ("retrieve_more" if items else "answer_with_limits")
    return merged


def append_context_sources(ledger: dict, *, has_user_input: bool, memory_ids: list[str]) -> dict:
    """Record user input and selected memories as metadata-only evidence.

    These sources are intentionally not allowed to promote a missing knowledge
    requirement to covered. They let later assessment and audit distinguish
    "no context" from "context was available but insufficient".
    """
    observations: list[dict] = []
    requirements = ledger.get("requirements", [])
    user_supports = [item["id"] for item in requirements if "user" in item.get("preferred_sources", [])]
    memory_supports = [item["id"] for item in requirements if "memory" in item.get("preferred_sources", [])]
    if has_user_input:
        observations.append({"source_type": "user", "source_id": "current_message", "supports": user_supports, "relevance": "high"})
    for memory_id in memory_ids:
        if memory_id:
            observations.append({"source_type": "memory", "source_id": str(memory_id), "supports": memory_supports, "relevance": "medium"})
    return append_authorized_observations(ledger, observations)


def parse_model_assessment(text: str, ledger: dict) -> dict:
    """Validate an advisory model decision against deterministic evidence facts."""
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("证据判断未返回合法 JSON") from exc
    if not isinstance(value, dict) or value.get("decision") not in ALLOWED_DECISIONS:
        raise ValueError("证据判断决策无效")
    missing = value.get("missing_requirement_ids", [])
    if not isinstance(missing, list) or any(item not in ledger["missing_requirement_ids"] for item in missing):
        raise ValueError("证据判断包含未知缺口")
    # A model cannot promote known missing evidence to sufficient.
    if ledger["missing_requirement_ids"] and value["decision"] == "sufficient":
        raise ValueError("不能将确定性证据缺口判为充分")
    return {"decision": value["decision"], "missing_requirement_ids": missing or ledger["missing_requirement_ids"]}
