#!/usr/bin/env python3
"""Run the deterministic P43 decision-quality suite without model calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.decision_quality import DEFAULT_SUITE, evaluate_suite, load_feedback_rows, load_suite, summarize_feedback
from server.app import infer_task_profile, plan_intent


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 Agent_Platform 决策质量评测")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--database", type=Path, help="可选：仅汇总本地 Run 状态与引用反馈，不读取对话正文")
    args = parser.parse_args()
    report = evaluate_suite(load_suite(args.suite), plan_intent, infer_task_profile)
    if args.database:
        report["feedback"] = summarize_feedback(load_feedback_rows(args.database))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if not report["summary"]["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
