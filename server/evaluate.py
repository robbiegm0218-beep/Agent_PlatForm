#!/usr/bin/env python3
"""Run the local Agent_Platform baseline checks without calling a model API.

The suite deliberately checks deterministic routing and records the human review
criteria for generated answers. Keep API calls out of the default run so model
cost, keys, and private content never enter a benchmark report by accident.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from server.app import infer_task_profile
except ModuleNotFoundError:
    from app import infer_task_profile


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT_DIR / "server" / "evals" / "personal_baseline.json"


def load_suite(path: Path) -> dict:
    suite = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(suite.get("cases"), list) or not suite["cases"]:
        raise ValueError("评测集至少需要一个用例")
    return suite


def evaluate_suite(suite: dict) -> dict:
    results = []
    for case in suite["cases"]:
        profile = infer_task_profile(case["prompt"], requested_task_mode=case.get("task_mode", "auto"))
        expected = case.get("expected_route", {})
        checks = {
            key: {"expected": value, "actual": profile.get(key), "passed": profile.get(key) == value}
            for key, value in expected.items()
        }
        results.append({
            "id": case["id"],
            "category": case["category"],
            "passed": all(check["passed"] for check in checks.values()),
            "checks": checks,
            "manual_review": case.get("manual_review", {}),
        })
    passed = sum(result["passed"] for result in results)
    return {
        "suite_version": suite.get("version", 1),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
        "results": results,
        "scope": "路由检查已自动执行；回答质量按每条 manual_review 人工评分，不保存私有资料或 API Key。",
    }


def compare_reports(current: dict, baseline: dict) -> dict:
    previous = {item["id"]: item for item in baseline.get("results", [])}
    changed = []
    for item in current["results"]:
        before = previous.get(item["id"])
        if before and before["passed"] != item["passed"]:
            changed.append({"id": item["id"], "before": before["passed"], "after": item["passed"]})
    return {"baseline_summary": baseline.get("summary", {}), "changed_cases": changed}


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 Agent_Platform 本地基准评测")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output", type=Path, default=ROOT_DIR / "data" / "evaluations" / "latest.json")
    parser.add_argument("--baseline", type=Path, help="上一次评测报告，用于输出差异")
    args = parser.parse_args()
    report = evaluate_suite(load_suite(args.suite))
    if args.baseline:
        report["comparison"] = compare_reports(report, json.loads(args.baseline.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"评测完成：{report['summary']['passed']}/{report['summary']['total']} 通过，报告：{args.output}")
    return 0 if not report["summary"]["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
