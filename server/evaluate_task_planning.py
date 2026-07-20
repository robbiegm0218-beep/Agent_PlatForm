#!/usr/bin/env python3
"""Evaluate recorded P45 TaskFrame observations against a fixed label set.

The default command only validates the fixture.  Supplying observations lets
Shadow-mode exports be assessed without model calls or prompt/body logging.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.task_planning import TaskFrameValidationError, validate_task_frame


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT_DIR / "server" / "evals" / "task_planning.json"


def load_suite(path: Path) -> dict:
    suite = json.loads(path.read_text(encoding="utf-8"))
    cases = suite.get("cases")
    if not isinstance(cases, list) or len(cases) < 30:
        raise ValueError("TaskFrame 固定集至少需要 30 条用例")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or case["id"] in seen:
            raise ValueError("TaskFrame 用例 ID 必须唯一")
        seen.add(case["id"])
        expected = case.get("expected", {})
        if not isinstance(expected.get("goal_keywords"), list) or not isinstance(expected.get("deliverable_keywords"), list):
            raise ValueError(f"用例 {case['id']} 缺少目标或交付物标签")
    return suite


def evaluate(suite: dict, observations: dict[str, dict]) -> dict:
    results = []
    for case in suite["cases"]:
        observed = observations.get(case["id"])
        if observed is None:
            results.append({"id": case["id"], "status": "missing_observation", "passed": False})
            continue
        try:
            frame = validate_task_frame(observed)
        except TaskFrameValidationError as exc:
            results.append({"id": case["id"], "status": "invalid_frame", "passed": False, "reason": str(exc)})
            continue
        expected = case["expected"]
        text = frame["goal"].lower()
        deliverables = " ".join(item["description"] for item in frame["deliverables"]).lower()
        constraints = " ".join(item["description"] for item in frame["constraints"]).lower()
        goal_ok = all(keyword.lower() in text for keyword in expected["goal_keywords"])
        deliverable_ok = all(keyword.lower() in deliverables for keyword in expected["deliverable_keywords"])
        constraints_ok = all(keyword.lower() in constraints for keyword in expected.get("constraint_keywords", []))
        results.append({"id": case["id"], "status": "evaluated", "passed": goal_ok and deliverable_ok and constraints_ok,
                        "checks": {"goal": goal_ok, "deliverables": deliverable_ok, "constraints": constraints_ok}})
    passed = sum(item["passed"] for item in results)
    observed_count = sum(item["status"] != "missing_observation" for item in results)
    return {"suite_version": suite.get("version", 1), "summary": {"total": len(results), "observed": observed_count, "passed": passed, "failed": len(results) - passed}, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="评测 P45 TaskFrame Shadow 观察结果")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--observations", type=Path, help="仅含 case_id 到 TaskFrame 的本地 JSON 映射")
    args = parser.parse_args()
    suite = load_suite(args.suite)
    if not args.observations:
        print(json.dumps({"suite_version": suite.get("version", 1), "summary": {"total": len(suite["cases"]), "status": "ready_for_shadow_observations"}}, ensure_ascii=False))
        return 0
    observations = json.loads(args.observations.read_text(encoding="utf-8"))
    report = evaluate(suite, observations)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
