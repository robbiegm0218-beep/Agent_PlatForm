#!/usr/bin/env python3
"""Evaluate explicit memory candidate, safety and selection policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.memory_policy import extract_candidates, select_memories, validate_memory_content


DEFAULT_FIXTURE = Path(__file__).with_name("evals") / "memory_policy.json"


def evaluate(cases: list[dict]) -> dict:
    failures = []
    for case in cases:
        operation = case["operation"]
        if operation == "candidate":
            actual = [item["kind"] for item in extract_candidates(case["content"])]
            expected = case["expected_kinds"]
        elif operation == "validate":
            try:
                validate_memory_content(case["content"])
                actual = True
            except ValueError:
                actual = False
            expected = case["expected_valid"]
        elif operation == "select":
            actual = [item["id"] for item in select_memories(
                case["records"], case["query"], case.get("project_id", ""),
                max_chars=case.get("max_chars", 1200), now_value=case.get("now_value", 0),
            )]
            expected = case["expected_ids"]
        else:
            raise ValueError(f"未知评测操作：{operation}")
        if actual != expected:
            failures.append({"id": case["id"], "expected": expected, "actual": actual})
    return {"cases": len(cases), "accuracy": (len(cases) - len(failures)) / len(cases), "failures": failures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args()
    cases = json.loads(args.fixture.read_text(encoding="utf-8"))
    report = evaluate(cases)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
