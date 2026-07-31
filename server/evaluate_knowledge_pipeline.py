#!/usr/bin/env python3
"""Produce the deterministic, content-safe P51 knowledge pipeline baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from server.app import chunk_knowledge_text
from server.evaluate_knowledge_retrieval import (
    DEFAULT_FIXTURE as RETRIEVAL_FIXTURE,
    evaluate as evaluate_retrieval,
    validate_cases as validate_retrieval_cases,
)
from server.knowledge_pipeline_contracts import contract_snapshot
from server.knowledge_retrieval import RETRIEVAL_POLICY_VERSION


DEFAULT_FIXTURE = Path(__file__).with_name("evals") / "knowledge_pipeline_baseline.json"
BASELINE_REPORT = Path(__file__).with_name("evals") / "p51_knowledge_pipeline_report.json"
SUPPORTED_FORMATS = {"markdown", "docx", "pdf", "xlsx", "image"}


def validate_fixture(value: object) -> dict:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("知识处理基线必须使用 schema version 1")
    capabilities = value.get("format_capabilities")
    chunk_cases = value.get("chunk_cases")
    if not isinstance(capabilities, list) or {item.get("format") for item in capabilities if isinstance(item, dict)} != SUPPORTED_FORMATS:
        raise ValueError("知识处理基线必须覆盖 Markdown、DOCX、PDF、XLSX 和图片")
    if not isinstance(chunk_cases, list) or len(chunk_cases) < 4:
        raise ValueError("知识处理基线至少需要 4 条切分样例")
    case_ids: set[str] = set()
    for case in chunk_cases:
        if not isinstance(case, dict) or not {"id", "text", "size", "overlap", "expected_sha256"} <= set(case):
            raise ValueError("切分样例字段不完整")
        if case["id"] in case_ids:
            raise ValueError(f"切分样例 ID 重复：{case['id']}")
        case_ids.add(case["id"])
        if not isinstance(case["text"], str) or not case["text"].strip():
            raise ValueError(f"切分样例 {case['id']} 缺少文本")
        if not isinstance(case["size"], int) or not isinstance(case["overlap"], int):
            raise ValueError(f"切分样例 {case['id']} 参数必须为整数")
        if case["size"] <= 0 or case["overlap"] < 0 or case["overlap"] >= case["size"]:
            raise ValueError(f"切分样例 {case['id']} 参数越界")
        if not isinstance(case["expected_sha256"], list) or not case["expected_sha256"]:
            raise ValueError(f"切分样例 {case['id']} 缺少预期哈希")
    return value


def evaluate(fixture: dict) -> dict:
    chunk_results = []
    failures = []
    for case in fixture["chunk_cases"]:
        chunks = chunk_knowledge_text(case["text"], size=case["size"], overlap=case["overlap"])
        hashes = [hashlib.sha256(chunk.encode("utf-8")).hexdigest() for chunk in chunks]
        passed = hashes == case["expected_sha256"]
        if not passed:
            failures.append({"id": case["id"], "kind": "chunk_hash_mismatch"})
        chunk_results.append({
            "id": case["id"],
            "chunk_count": len(chunks),
            "chunk_sha256": hashes,
            "passed": passed,
        })

    retrieval_cases = validate_retrieval_cases(json.loads(RETRIEVAL_FIXTURE.read_text(encoding="utf-8")))
    retrieval = evaluate_retrieval(retrieval_cases, gate_v2=True)
    if retrieval["failures"]:
        failures.append({"id": "knowledge-retrieval-v1", "kind": "retrieval_regression"})

    return {
        "schema_version": 1,
        "pipeline_behavior": "fixed-character-chunking-v1",
        "retrieval_policy_version": RETRIEVAL_POLICY_VERSION,
        "format_capabilities": [
            {
                "format": item["format"],
                "parser": item["parser"],
                "current_structure": item["current_structure"],
                "coverage_test": item["coverage_test"],
            }
            for item in fixture["format_capabilities"]
        ],
        "contract": contract_snapshot(),
        "chunk_baseline": chunk_results,
        "retrieval_baseline": {
            key: retrieval[key]
            for key in (
                "cases",
                "recall_at_4",
                "top1_accuracy",
                "no_match_accuracy",
                "neighbor_accuracy",
            )
        },
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args()
    fixture = validate_fixture(json.loads(args.fixture.read_text(encoding="utf-8")))
    report = evaluate(fixture)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
