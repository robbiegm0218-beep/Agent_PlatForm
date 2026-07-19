"""Reproducible, privacy-safe decision quality evaluation utilities.

This module deliberately evaluates deterministic decision signals only.  It
does not send prompts, Run content, credentials, or personal identifiers to a
model provider.  Generated reports contain aggregate metrics and salted IDs.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT_DIR / "server" / "evals" / "decision_quality.json"
POLICY_VERSION = "decision-quality-v1"
MIN_CITATION_SAMPLE = 20
MIN_TASK_SAMPLE = 30
QUALITY_GATES = {
    "retrieval_omission_rate": 0.05,
    "over_retrieval_rate": 0.10,
    "clarification_miss_rate": 0.10,
    "citation_accuracy": 0.90,
    "task_success_rate": 0.90,
}


def policy_snapshot() -> dict:
    return {"version": POLICY_VERSION, "quality_gates": dict(QUALITY_GATES)}


def anonymize_run(run: dict, salt: str = "decision-quality") -> dict:
    """Export only decision metadata; never include user text or source text."""
    digest = lambda value: hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()[:16]
    context = run.get("execution_context") or {}
    if isinstance(context, str):
        try:
            context = json.loads(context)
        except json.JSONDecodeError:
            context = {}
    return {
        "run": digest(str(run.get("id", ""))),
        "thread": digest(str(run.get("thread_id", ""))),
        "model": str(run.get("model", "")),
        "status": str(run.get("status", "")),
        "task_tier": context.get("task_tier", "standard"),
        "knowledge_route": context.get("knowledge_route", "not_needed"),
        "knowledge_match_count": int(context.get("knowledge_match_count", 0) or 0),
        "space_scope": "project" if context.get("space_context") else "general",
        "policy_version": (context.get("decision_policy") or {}).get("version", "unknown"),
    }


def load_suite(path: Path = DEFAULT_SUITE) -> dict:
    suite = json.loads(path.read_text(encoding="utf-8"))
    cases = suite.get("cases")
    if not isinstance(cases, list) or len(cases) < 12:
        raise ValueError("决策质量评测集至少需要 12 条用例")
    ids = set()
    for case in cases:
        expected = case.get("expected", {}) if isinstance(case, dict) else {}
        if not isinstance(case.get("id"), str) or not case["id"] or case["id"] in ids:
            raise ValueError("评测用例 ID 无效或重复")
        ids.add(case["id"])
        if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
            raise ValueError(f"用例 {case['id']} 缺少 prompt")
        if not {"retrieve", "clarify", "scope", "task_tier"} <= set(expected):
            raise ValueError(f"用例 {case['id']} 缺少 expected 决策标签")
        if not isinstance(expected["retrieve"], bool) or not isinstance(expected["clarify"], bool):
            raise ValueError(f"用例 {case['id']} 的布尔标签无效")
        if expected["scope"] not in {"general", "project"}:
            raise ValueError(f"用例 {case['id']} 的 scope 无效")
    return suite


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def evaluate_suite(
    suite: dict,
    plan_fn: Callable[[str, dict], dict],
    route_fn: Callable[[str], dict],
) -> dict:
    """Score planner and route decisions against immutable labelled cases."""
    results = []
    groups: dict[str, Counter] = defaultdict(Counter)
    retrieval_expected = retrieval_omitted = retrieval_unexpected = 0
    clarify_expected = clarify_missed = 0
    task_total = task_passed = 0
    for case in suite["cases"]:
        expected = case["expected"]
        profile = route_fn(case["prompt"])
        intent = plan_fn(case["prompt"], profile)
        actual_retrieve = bool(intent.get("knowledge_needed"))
        actual_clarify = bool(intent.get("clarification_needed"))
        actual_scope = "project" if case.get("project_space_id") else "general"
        checks = {
            "retrieve": actual_retrieve == expected["retrieve"],
            "clarify": actual_clarify == expected["clarify"],
            "scope": actual_scope == expected["scope"],
            "task_tier": profile.get("task_tier") == expected["task_tier"],
        }
        if expected["retrieve"]:
            retrieval_expected += 1
            retrieval_omitted += not actual_retrieve
        else:
            retrieval_unexpected += actual_retrieve
        if expected["clarify"]:
            clarify_expected += 1
            clarify_missed += not actual_clarify
        task_total += 1
        task_passed += all(checks.values())
        group = groups[f"{profile.get('model', 'auto')}|{profile.get('task_tier', 'standard')}|{expected['scope']}"]
        group["total"] += 1
        group["passed"] += all(checks.values())
        results.append({"id": case["id"], "passed": all(checks.values()), "checks": checks,
                        "actual": {"retrieve": actual_retrieve, "clarify": actual_clarify,
                                   "scope": actual_scope, "task_tier": profile.get("task_tier")}})
    metrics = {
        "retrieval_omission_rate": _rate(retrieval_omitted, retrieval_expected),
        "over_retrieval_rate": _rate(retrieval_unexpected, task_total - retrieval_expected),
        "clarification_miss_rate": _rate(clarify_missed, clarify_expected),
        "task_success_rate": _rate(task_passed, task_total),
    }
    return {"suite": suite.get("name", ""), "suite_version": suite.get("version", 1),
            "policy": policy_snapshot(), "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {"total": task_total, "passed": task_passed, "failed": task_total - task_passed},
            "metrics": metrics,
            "groups": {key: {"total": value["total"], "task_success_rate": _rate(value["passed"], value["total"])} for key, value in groups.items()},
            "results": results}


def summarize_feedback(rows: list[dict], *, minimum_citations: int = MIN_CITATION_SAMPLE, minimum_tasks: int = MIN_TASK_SAMPLE) -> dict:
    citations = [row for row in rows if row.get("citation_correct") is not None]
    completed = [row for row in rows if row.get("status") == "completed"]
    citation_accuracy = _rate(sum(bool(row["citation_correct"]) for row in citations), len(citations)) if citations else None
    task_success = _rate(len(completed), len(rows)) if rows else None
    sufficient = len(citations) >= minimum_citations and len(rows) >= minimum_tasks
    return {"sample_size": len(rows), "citation_assessed": len(citations), "citation_accuracy": citation_accuracy,
            "task_success_rate": task_success, "minimums": {"citations": minimum_citations, "tasks": minimum_tasks},
            "sufficient_for_claim": sufficient,
            "claim": "样本不足，不得宣称策略提升" if not sufficient else "样本量达到比较门槛"}


def load_feedback_rows(database: Path) -> list[dict]:
    """Read aggregate-safe feedback columns only; prompt/message text is never queried."""
    if not database.exists():
        return []
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT runs.status, run_feedback.citation_correct
               FROM runs LEFT JOIN run_feedback ON run_feedback.run_id = runs.id"""
        ).fetchall()
    return [dict(row) for row in rows]


def compare_experiment(baseline: dict, candidate: dict, *, changed_variable: str) -> dict:
    if not isinstance(changed_variable, str) or not changed_variable.strip() or "," in changed_variable:
        raise ValueError("每次实验必须且只能声明一个变更变量")
    baseline_metrics, candidate_metrics = baseline.get("metrics", {}), candidate.get("metrics", {})
    regressions = []
    for metric, threshold in QUALITY_GATES.items():
        before, after = baseline_metrics.get(metric), candidate_metrics.get(metric)
        if before is None or after is None:
            continue
        lower_is_better = metric.endswith("_rate") and metric not in {"task_success_rate"}
        worsened = after > before if lower_is_better else after < before
        if worsened or (lower_is_better and after > threshold) or (not lower_is_better and after < threshold):
            regressions.append({"metric": metric, "baseline": before, "candidate": after})
    return {"changed_variable": changed_variable, "decision": "promote" if not regressions else "rollback",
            "regressions": regressions, "policy_version": POLICY_VERSION}
