#!/usr/bin/env python3
"""Evaluate source-linked structured context extraction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.structured_context import KINDS, StructuredContextBuilder


DEFAULT_FIXTURE = Path(__file__).with_name("evals") / "structured_context.json"


def validate_cases(value: object) -> list[dict]:
    if not isinstance(value, list) or len(value) < 10:
        raise ValueError("结构化上下文评测集至少需要 10 条样例")
    ids = set()
    for case in value:
        if not isinstance(case, dict) or not {"id", "messages", "expected"} <= set(case):
            raise ValueError("评测样例缺少必需字段")
        if case["id"] in ids:
            raise ValueError(f"样例 ID 重复：{case['id']}")
        ids.add(case["id"])
    return value


def _contains(items: list[dict], fragment: str, status: str) -> bool:
    return any(item.get("status") == status and fragment in item.get("text", "") for item in items)


def evaluate(cases: list[dict], builder: StructuredContextBuilder | None = None) -> dict:
    builder = builder or StructuredContextBuilder()
    checks = 0
    passed = 0
    failures = []
    for case in cases:
        inherited = None
        if case.get("inherited_messages"):
            inherited = builder.build(case["inherited_messages"])
        context = builder.build(case["messages"], inherited)
        for kind, fragments in case["expected"].items():
            if kind not in KINDS:
                raise ValueError(f"未知上下文字段：{kind}")
            if fragments == []:
                checks += 1
                active = [item["text"] for item in context[kind] if item["status"] == "active"]
                if not active:
                    passed += 1
                else:
                    failures.append({"id": case["id"], "kind": kind, "expected": [], "actual": active})
            for fragment in fragments:
                checks += 1
                if _contains(context[kind], fragment, "active"):
                    passed += 1
                else:
                    failures.append({"id": case["id"], "kind": kind, "missing_active": fragment})
        for kind, fragments in case.get("expected_inactive", {}).items():
            for fragment in fragments:
                checks += 1
                if _contains(context[kind], fragment, "superseded"):
                    passed += 1
                else:
                    failures.append({"id": case["id"], "kind": kind, "missing_superseded": fragment})
        source_ids = {message["id"] for message in case.get("inherited_messages", []) + case["messages"]}
        for kind in KINDS:
            for item in context[kind]:
                checks += 1
                if item.get("source_message_id") in source_ids:
                    passed += 1
                else:
                    failures.append({"id": case["id"], "kind": kind, "invalid_source": item.get("source_message_id")})
    return {"cases": len(cases), "checks": checks, "accuracy": passed / checks if checks else 1.0, "failures": failures}


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
