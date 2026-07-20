#!/usr/bin/env python3
"""P45 fixed evaluation, Shadow comparison and rollout recommendation."""
from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path
from server.decision_quality import evaluate_suite, load_suite
from server.evaluate_evidence_sufficiency import DEFAULT_SUITE as EVIDENCE_SUITE, evaluate as evaluate_evidence
from server.evaluate_task_verification import DEFAULT as VERIFICATION_SUITE, evaluate as evaluate_verification

MIN_SHADOW_RUNS = 30

def fixed_report() -> dict:
    # Keep this import local so the report module can also be used by the HTTP
    # adapter without creating an application-import cycle.
    from server.app import infer_task_profile, plan_intent
    decision = evaluate_suite(load_suite(), plan_intent, infer_task_profile)
    evidence = evaluate_evidence(json.loads(EVIDENCE_SUITE.read_text(encoding="utf-8")))
    verification = evaluate_verification(json.loads(VERIFICATION_SUITE.read_text(encoding="utf-8")))
    passed = decision["summary"]["failed"] == 0 and evidence["summary"]["failed"] == 0 and verification["summary"]["failed"] == 0
    return {"passed": passed, "decision": decision["summary"], "evidence": evidence["summary"], "verification": verification["summary"]}

def _cohort_metrics(rows: list[dict], event_index: dict[str, list[tuple[str, str]]]) -> dict:
    total = len(rows)
    completed = sum(item["status"] == "completed" for item in rows)
    ratings = [item["rating"] for item in rows if item["rating"] in (0, 1)]
    helpful = sum(rating == 1 for rating in ratings)
    tool_calls = sum(int(item["tool_call_count"] or 0) for item in rows)
    durations = sorted(max(0, (item["completed_at"] - item["started_at"]) / 1_000_000_000) for item in rows if item["completed_at"] and item["started_at"])
    verification_failures = 0
    model_calls = 0
    for item in rows:
        events = event_index.get(item["id"], [])
        model_calls += sum(event_type in {"model_request", "model_call"} for event_type, _payload in events)
        for event_type, payload in events:
            if event_type != "task_verified":
                continue
            try:
                if not bool(json.loads(payload or "{}").get("passed", True)):
                    verification_failures += 1
                    break
            except json.JSONDecodeError:
                verification_failures += 1
                break
    p95 = durations[min(len(durations) - 1, int(len(durations) * .95))] if durations else None
    return {
        "runs": total,
        "completion_rate": round(completed / total, 4) if total else None,
        "ratings": len(ratings),
        "helpful_rate": round(helpful / len(ratings), 4) if ratings else None,
        "tool_calls": tool_calls,
        "tool_calls_per_run": round(tool_calls / total, 3) if total else None,
        "model_calls": model_calls,
        "model_calls_per_run": round(model_calls / total, 3) if total else None,
        "verification_failures": verification_failures,
        "verification_failure_rate": round(verification_failures / total, 4) if total else None,
        "p95_seconds": round(p95, 3) if p95 is not None else None,
    }


def shadow_report(database: Path, user_id: str | None = None) -> dict:
    if not database.exists(): return {"sample_size": 0, "v1_runs": 0, "v2_shadow_runs": 0, "status": "no_database"}
    with sqlite3.connect(database) as conn:
        predicate, parameters = ("WHERE threads.user_id = ?", (user_id,)) if user_id else ("", ())
        rows = conn.execute(f"SELECT runs.id, runs.status, runs.execution_context, runs.started_at, runs.completed_at, runs.tool_call_count, run_feedback.rating FROM runs JOIN threads ON threads.id = runs.thread_id LEFT JOIN run_feedback ON run_feedback.run_id = runs.id {predicate} ORDER BY runs.started_at DESC LIMIT 500", parameters).fetchall()
        event_rows = conn.execute(f"SELECT run_events.run_id, run_events.type, run_events.payload FROM run_events JOIN runs ON runs.id = run_events.run_id JOIN threads ON threads.id = runs.thread_id {predicate} AND run_events.type IN ('model_request', 'model_call', 'task_verified')" if predicate else "SELECT run_id, type, payload FROM run_events WHERE type IN ('model_request', 'model_call', 'task_verified')", parameters).fetchall()
    event_index: dict[str, list[tuple[str, str]]] = {}
    for run_id, event_type, payload in event_rows:
        event_index.setdefault(run_id, []).append((event_type, payload))
    v1_rows: list[dict] = []; v2_rows: list[dict] = []
    for run_id, status, raw, started, ended, tool_count, rating in rows:
        try: context = json.loads(raw or "{}")
        except json.JSONDecodeError: context = {}
        is_v2 = bool(context.get("task_frame") or context.get("evidence_ledger") or context.get("orchestrator_trace"))
        item = {"id": run_id, "status": status, "started_at": started, "completed_at": ended, "tool_call_count": tool_count, "rating": rating}
        (v2_rows if is_v2 else v1_rows).append(item)
    v1 = _cohort_metrics(v1_rows, event_index)
    v2 = _cohort_metrics(v2_rows, event_index)
    return {
        "sample_size": len(rows), "v1_runs": len(v1_rows), "v2_shadow_runs": len(v2_rows),
        "v1": v1, "v2": v2,
        # Retain the original top-level fields for existing consumers.
        "v2_completion_rate": v2["completion_rate"], "v2_helpful_rate": v2["helpful_rate"],
        "v2_tool_calls": v2["tool_calls"], "v2_p95_seconds": v2["p95_seconds"],
        "status": "sufficient" if len(v2_rows) >= MIN_SHADOW_RUNS else "insufficient",
    }

def recommend(fixed: dict, shadow: dict) -> str:
    if not fixed["passed"]: return "rollback"
    if shadow["status"] != "sufficient": return "shadow"
    if (shadow.get("v2_completion_rate") or 0) < 0.9: return "rollback"
    baseline, candidate = shadow.get("v1", {}), shadow.get("v2", {})
    if baseline.get("completion_rate") is not None and (candidate.get("completion_rate") or 0) < baseline["completion_rate"]:
        return "rollback"
    if (candidate.get("verification_failure_rate") or 0) > 0.1:
        return "rollback"
    if baseline.get("p95_seconds") and candidate.get("p95_seconds") and candidate["p95_seconds"] > baseline["p95_seconds"] * 2:
        return "shadow"
    if baseline.get("ratings", 0) >= 20 and candidate.get("ratings", 0) >= 20 and (candidate.get("helpful_rate") or 0) < (baseline.get("helpful_rate") or 0):
        return "shadow"
    return "administrator_canary"

def main() -> int:
    parser=argparse.ArgumentParser(description="运行 P45 发布门槛评测")
    parser.add_argument("--database", type=Path, default=Path("agent_platform.db")); parser.add_argument("--output", type=Path)
    args=parser.parse_args(); fixed=fixed_report(); shadow=shadow_report(args.database); report={"fixed":fixed,"shadow":shadow,"recommendation":recommend(fixed,shadow),"rollback":"设置 AGENT_INTELLIGENCE_V2=false 即可恢复 V1；历史 Run 保留原上下文。"}
    text=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output: args.output.write_text(text+"\n",encoding="utf-8")
    print(text); return 0 if report["recommendation"] != "rollback" else 1
if __name__=="__main__": raise SystemExit(main())
