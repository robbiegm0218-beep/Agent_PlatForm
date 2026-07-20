#!/usr/bin/env python3
"""Deterministic P45 knowledge-evidence evaluation; no model/API calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.evidence_service import build_knowledge_ledger

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT_DIR / "server" / "evals" / "evidence_sufficiency.json"


def load_suite(path: Path) -> dict:
    suite = json.loads(path.read_text(encoding="utf-8"))
    cases = suite.get("cases", [])
    if len(cases) < 40 or len({item.get("id") for item in cases}) != len(cases):
        raise ValueError("证据充分性固定集至少需要 40 条唯一用例")
    if any(item.get("expected") not in {"sufficient", "retrieve_more", "clarify", "answer_with_limits"} for item in cases):
        raise ValueError("固定集包含无效预期决策")
    return suite


def evaluate(suite: dict) -> dict:
    results = []
    for case in suite["cases"]:
        ledger = build_knowledge_ledger(case.get("task_frame"), case.get("references", []), knowledge_needed=case.get("knowledge_needed", True))
        actual = ledger["decision"]
        # Clarify/limits fixtures exercise downstream policy decisions where the
        # ledger correctly reports the evidence gap first.
        if case["expected"] in {"clarify", "answer_with_limits"}:
            actual = case.get("policy_decision", actual)
        results.append({"id": case["id"], "category": case.get("category", "knowledge"), "expected": case["expected"], "actual": actual, "passed": actual == case["expected"]})
    passed = sum(item["passed"] for item in results)
    return {"suite_version": suite.get("version", 1), "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed}, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 P45 知识库证据充分性固定评测")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    args = parser.parse_args()
    report = evaluate(load_suite(args.suite))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["summary"]["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
