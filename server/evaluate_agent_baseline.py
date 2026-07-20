#!/usr/bin/env python3
"""Create a privacy-safe P45 V1 baseline from Run metadata and events."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def build_report(database: Path) -> dict:
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        runs = conn.execute("SELECT id, status, execution_context, started_at, completed_at FROM runs").fetchall()
        events = conn.execute("SELECT run_id, type FROM run_events").fetchall()
    by_run: dict[str, set[str]] = {}
    for event in events:
        by_run.setdefault(event["run_id"], set()).add(event["type"])
    total = len(runs)
    durations = []
    tool_runs = tool_success = retrieval_runs = retrieval_sufficient = 0
    for run in runs:
        kinds = by_run.get(run["id"], set())
        context = json.loads(run["execution_context"] or "{}")
        if "tool_call" in kinds:
            tool_runs += 1
            tool_success += int("tool_result" in kinds and "tool_error" not in kinds)
        if context.get("intent_plan", {}).get("knowledge_needed"):
            retrieval_runs += 1
            retrieval_sufficient += int(bool(context.get("retrieval_trace", {}).get("sufficient")))
        if run["completed_at"] and run["started_at"]:
            durations.append(max(0, run["completed_at"] - run["started_at"]))
    def rate(numerator: int, denominator: int):
        return round(numerator / denominator, 4) if denominator else None
    return {
        "version": 1,
        "sample": {"runs": total, "status": "sufficient" if total >= 30 else "insufficient"},
        "metrics": {
            "completed_run_rate": rate(sum(run["status"] == "completed" for run in runs), total),
            "knowledge_retrieval_sufficient_rate_v1": rate(retrieval_sufficient, retrieval_runs),
            "tool_call_rate": rate(tool_runs, total),
            "tool_success_rate": rate(tool_success, tool_runs),
            "average_duration_seconds": round(sum(durations) / len(durations) / 1e9, 3) if durations else None,
            "unsupported_claim_rate": None,
            "task_acceptance_pass_rate": None,
            "model_call_average": None,
            "token_estimate_average": None,
        },
        "limitations": [
            "V1 未保存证据账本和任务验收结论，因此无依据结论率与任务验收通过率暂不可计算。",
            "报告不导出对话正文、资料正文、用户标识或模型密钥。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 P45 V1 基线报告")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(args.database)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
