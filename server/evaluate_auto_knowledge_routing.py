#!/usr/bin/env python3
"""Measure the current automatic knowledge-routing behavior on synthetic cases.

This evaluator intentionally models the production P50 baseline without changing
the production route: explicit requests retrieve directly; otherwise auto mode
performs a lexical probe whenever the query has terms and selects any returned
candidate. Reports contain stable case IDs and aggregate counts, never prompts or
document content.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.knowledge_retrieval import (
    KnowledgeRetriever,
    assess_candidate_relevance,
    query_terms,
)
from server.task_router import classify_knowledge_intent


DEFAULT_FIXTURE = Path(__file__).with_name("evals") / "auto_knowledge_routing.json"

CASE_CATEGORIES = {"explicit", "implicit_anchor", "negative", "mode_control"}
KNOWLEDGE_MODES = {"off", "auto", "required"}


def validate_fixture(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("评测集必须是对象")
    documents = payload.get("documents")
    cases = payload.get("cases")
    if not isinstance(documents, list) or not documents:
        raise ValueError("评测集必须包含非空 documents")
    if not isinstance(cases, list) or len(cases) < 12:
        raise ValueError("评测集必须包含至少 12 条 cases")

    document_ids = set()
    for index, row in enumerate(documents):
        required = {"id", "document_id", "filename", "position", "content"}
        if not isinstance(row, dict) or not required <= set(row):
            raise ValueError(f"文档 {index} 字段不完整")
        if row["id"] in document_ids:
            raise ValueError(f"文档行 ID 重复：{row['id']}")
        document_ids.add(row["id"])

    case_ids = set()
    categories = set()
    for index, case in enumerate(cases):
        required = {"id", "category", "query", "knowledge_mode", "expected_selected"}
        if not isinstance(case, dict) or not required <= set(case):
            raise ValueError(f"样例 {index} 缺少必需字段")
        if case["id"] in case_ids:
            raise ValueError(f"样例 ID 重复：{case['id']}")
        case_ids.add(case["id"])
        if case["category"] not in CASE_CATEGORIES:
            raise ValueError(f"样例 {case['id']} 的 category 无效")
        categories.add(case["category"])
        if case["knowledge_mode"] not in KNOWLEDGE_MODES:
            raise ValueError(f"样例 {case['id']} 的 knowledge_mode 无效")
        if not isinstance(case["expected_selected"], bool):
            raise ValueError(f"样例 {case['id']} 的 expected_selected 必须是布尔值")
    if categories != CASE_CATEGORIES:
        raise ValueError("评测集必须覆盖 explicit、implicit_anchor、negative、mode_control")
    return {"documents": documents, "cases": cases}


def routing_decision(
    case: dict,
    documents: list[dict],
    retriever: KnowledgeRetriever,
    gate_v2: bool = False,
    strong_gate: bool = False,
) -> dict:
    mode = case["knowledge_mode"]
    intent = classify_knowledge_intent(case["query"], gate_v2=gate_v2)
    automatic_probe = False
    route = "probe_skipped"
    results: list[dict] = []

    if mode == "off":
        reason = "knowledge_mode_off"
    elif mode == "required":
        route = "required_retrieval"
        reason = "knowledge_mode_required"
        results = retriever.search(case["query"], documents, gate_v2=gate_v2)
    elif intent["route"] == "explicit":
        route = "explicit_retrieval"
        reason = str(intent["reason"])
        results = retriever.search(case["query"], documents, gate_v2=gate_v2)
    elif (not gate_v2 or intent["route"] == "implicit_candidate") and query_terms(case["query"], gate_v2=gate_v2):
        automatic_probe = True
        route = "automatic_probe"
        reason = "implicit_candidate_probe" if gate_v2 else "current_auto_probe"
        results = retriever.search(case["query"], documents, gate_v2=gate_v2)
    else:
        reason = "intent_not_knowledge" if gate_v2 else "no_query_terms"

    relevance = assess_candidate_relevance(
        case["query"], results, gate_v2=gate_v2,
    )
    selected = bool(results)
    if strong_gate and automatic_probe:
        selected = bool(
            results
            and relevance["sufficient"]
            and relevance["strong_anchor"]
            and relevance["rank_confident"]
        )
    return {
        "id": case["id"],
        "category": case["category"],
        "knowledge_mode": mode,
        "intent_reason": str(intent["reason"]),
        "route": route,
        "reason": reason,
        "automatic_probe": automatic_probe,
        "candidate_count": len(results),
        "candidate_returned": bool(results),
        "sufficient": relevance["sufficient"],
        "strong_anchor": relevance["strong_anchor"],
        "rank_confident": relevance["rank_confident"],
        "selected": selected,
        "expected_selected": case["expected_selected"],
        "outcome": "match" if selected == case["expected_selected"] else (
            "false_positive" if selected else "false_negative"
        ),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def evaluate(
    fixture: dict,
    retriever: KnowledgeRetriever | None = None,
    gate_v2: bool = False,
    strong_gate: bool = False,
) -> dict:
    retriever = retriever or KnowledgeRetriever()
    results = [
        routing_decision(
            case,
            fixture["documents"],
            retriever,
            gate_v2=gate_v2,
            strong_gate=strong_gate,
        )
        for case in fixture["cases"]
    ]
    expected_positive = sum(item["expected_selected"] for item in results)
    expected_negative = len(results) - expected_positive
    true_positive = sum(item["selected"] and item["expected_selected"] for item in results)
    true_negative = sum(not item["selected"] and not item["expected_selected"] for item in results)
    false_positive = sum(item["outcome"] == "false_positive" for item in results)
    false_negative = sum(item["outcome"] == "false_negative" for item in results)
    automatic_probes = sum(item["automatic_probe"] for item in results)
    candidates_returned = sum(item["candidate_returned"] for item in results)
    selected = sum(item["selected"] for item in results)

    return {
        "policy": (
            "strong-relevance-gate-v2"
            if strong_gate
            else ("intent-gate-v2" if gate_v2 else "current-auto-knowledge-baseline")
        ),
        "cases": len(results),
        "stages": {
            "automatic_probes": automatic_probes,
            "candidates_returned": candidates_returned,
            "selected": selected,
        },
        "quality": {
            "expected_positive": expected_positive,
            "expected_negative": expected_negative,
            "true_positive": true_positive,
            "true_negative": true_negative,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "precision": _rate(true_positive, true_positive + false_positive),
            "recall": _rate(true_positive, expected_positive),
            "negative_accuracy": _rate(true_negative, expected_negative),
        },
        "false_positive_case_ids": [
            item["id"] for item in results if item["outcome"] == "false_positive"
        ],
        "false_negative_case_ids": [
            item["id"] for item in results if item["outcome"] == "false_negative"
        ],
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--policy", choices=("current", "v2", "v2-strong"), default="current")
    args = parser.parse_args()
    fixture = validate_fixture(json.loads(args.fixture.read_text(encoding="utf-8")))
    report = evaluate(
        fixture,
        gate_v2=args.policy != "current",
        strong_gate=args.policy == "v2-strong",
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
