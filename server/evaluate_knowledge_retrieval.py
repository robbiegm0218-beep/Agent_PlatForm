#!/usr/bin/env python3
"""Evaluate deterministic knowledge retrieval against synthetic fixtures."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from server.knowledge_retrieval import KnowledgeRetriever


DEFAULT_FIXTURE = Path(__file__).with_name("evals") / "knowledge_retrieval.json"


def legacy_document_ids(query: str, rows: list[dict], limit: int = 4) -> list[str]:
    compact = re.sub(r"\s+", "", query.lower())
    english = re.findall(r"[a-z0-9_]{2,}", compact)
    chinese = [
        compact[index:index + 2]
        for index in range(max(0, len(compact) - 1))
        if re.search(r"[\u4e00-\u9fff]", compact[index:index + 2])
    ]
    terms = list(dict.fromkeys(english + chinese))[:20]
    minimum_score = 1 if len(terms) == 1 else 2
    scored = []
    for row in rows:
        score = sum(str(row["content"]).lower().count(term) for term in terms)
        if score >= minimum_score:
            scored.append((score, int(row["position"]), str(row["id"]), str(row["document_id"])))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return _unique([item[3] for item in scored])[:limit]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def validate_cases(cases: object) -> list[dict]:
    if not isinstance(cases, list) or len(cases) < 20:
        raise ValueError("评测集必须是至少 20 条样例的数组")
    required = {"id", "query", "documents", "expected_document_ids", "expect_empty"}
    ids = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or not required <= set(case):
            raise ValueError(f"样例 {index} 缺少必需字段")
        if case["id"] in ids:
            raise ValueError(f"样例 ID 重复：{case['id']}")
        ids.add(case["id"])
        if bool(case["expect_empty"]) != (case["expected_document_ids"] == []):
            raise ValueError(f"样例 {case['id']} 的空结果声明不一致")
        for row in case["documents"]:
            if not {"id", "document_id", "filename", "position", "content"} <= set(row):
                raise ValueError(f"样例 {case['id']} 的文档字段不完整")
    return cases


def evaluate(cases: list[dict], retriever: KnowledgeRetriever | None = None) -> dict:
    retriever = retriever or KnowledgeRetriever()
    failures = []
    relevant_total = 0
    recalled_total = 0
    top1_hits = 0
    non_empty_total = 0
    empty_total = 0
    empty_correct = 0
    neighbor_total = 0
    neighbor_correct = 0
    legacy_recalled = 0
    legacy_top1 = 0

    for case in cases:
        results = retriever.search(case["query"], case["documents"])
        actual_ids = _unique([item["document_id"] for item in results])[:4]
        expected_ids = case["expected_document_ids"]
        legacy_ids = legacy_document_ids(case["query"], case["documents"])
        if case["expect_empty"]:
            empty_total += 1
            if not actual_ids:
                empty_correct += 1
            else:
                failures.append({"id": case["id"], "kind": "unexpected_result", "actual": actual_ids})
            continue

        non_empty_total += 1
        relevant_total += len(expected_ids)
        recalled_total += len(set(expected_ids) & set(actual_ids))
        legacy_recalled += len(set(expected_ids) & set(legacy_ids))
        if actual_ids and actual_ids[0] == expected_ids[0]:
            top1_hits += 1
        else:
            failures.append({"id": case["id"], "kind": "top1", "expected": expected_ids[0], "actual": actual_ids[:1]})
        if legacy_ids and legacy_ids[0] == expected_ids[0]:
            legacy_top1 += 1
        missing = [document_id for document_id in expected_ids if document_id not in actual_ids]
        if missing:
            failures.append({"id": case["id"], "kind": "recall", "missing": missing, "actual": actual_ids})

        if "expected_neighbor_positions" in case:
            neighbor_total += 1
            primary = next((item for item in results if item["document_id"] == expected_ids[0]), None)
            actual_neighbors = primary["neighbor_positions"] if primary else []
            if actual_neighbors == case["expected_neighbor_positions"]:
                neighbor_correct += 1
            else:
                failures.append({
                    "id": case["id"], "kind": "neighbors",
                    "expected": case["expected_neighbor_positions"], "actual": actual_neighbors,
                })

    return {
        "cases": len(cases),
        "recall_at_4": recalled_total / relevant_total if relevant_total else 1.0,
        "top1_accuracy": top1_hits / non_empty_total if non_empty_total else 1.0,
        "no_match_accuracy": empty_correct / empty_total if empty_total else 1.0,
        "neighbor_accuracy": neighbor_correct / neighbor_total if neighbor_total else 1.0,
        "legacy_recall_at_4": legacy_recalled / relevant_total if relevant_total else 1.0,
        "legacy_top1_accuracy": legacy_top1 / non_empty_total if non_empty_total else 1.0,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args()
    cases = validate_cases(json.loads(args.fixture.read_text(encoding="utf-8")))
    report = evaluate(cases)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
