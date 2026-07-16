#!/usr/bin/env python3
"""Evaluate deterministic task routing without model or network calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from server.app import infer_task_profile
except ModuleNotFoundError:
    from app import infer_task_profile


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT_DIR / "server" / "evals" / "task_routing.json"
VALID_TASK_MODES = {"quick", "standard", "deep"}


def load_suite(path: Path) -> dict:
    suite = json.loads(path.read_text(encoding="utf-8"))
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("评测集至少需要一个用例")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("评测用例必须是对象")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise ValueError(f"用例 ID 无效或重复：{case_id}")
        seen.add(case_id)
        if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
            raise ValueError(f"用例 {case_id} 的 prompt 不能为空")
        if not isinstance(case.get("expected_route"), dict) or not case["expected_route"]:
            raise ValueError(f"用例 {case_id} 缺少 expected_route")
        if "task_mode" in case and case["task_mode"] not in VALID_TASK_MODES:
            raise ValueError(f"用例 {case_id} 的 task_mode 无效")
        if "model" in case and (not isinstance(case["model"], str) or not case["model"].strip()):
            raise ValueError(f"用例 {case_id} 的 model 无效")
    return suite


def evaluate_suite(suite: dict, route_fn=infer_task_profile) -> dict:
    mismatches = []
    results = []
    for case in suite["cases"]:
        profile = route_fn(
            case["prompt"],
            requested_model=case.get("model", "auto"),
            requested_task_mode=case.get("task_mode", "auto"),
        )
        case_mismatches = []
        for field, expected in case["expected_route"].items():
            actual = profile.get(field)
            if actual != expected:
                mismatch = {"id": case["id"], "field": field, "expected": expected, "actual": actual}
                mismatches.append(mismatch)
                case_mismatches.append(mismatch)
        results.append({"id": case["id"], "passed": not case_mismatches})
    passed = sum(result["passed"] for result in results)
    return {
        "suite": suite.get("name", ""),
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
        "mismatches": mismatches,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 Agent_Platform 任务路由评测")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    args = parser.parse_args()
    report = evaluate_suite(load_suite(args.suite))
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0 if not report["summary"]["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
