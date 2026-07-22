#!/usr/bin/env python3
"""Build a privacy-safe readiness baseline for the personal hosted edition."""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


COUNTED_TABLES = (
    "users", "threads", "messages", "runs", "knowledge_documents",
    "knowledge_chunks", "artifacts", "memories", "run_feedback",
    "citation_feedback_items",
)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return round(ordered[index], 3)


def _duration_seconds(started_at: int | None, completed_at: int | None) -> float | None:
    if not started_at or not completed_at or completed_at < started_at:
        return None
    delta = completed_at - started_at
    # New records use nanoseconds; early databases may still contain seconds.
    seconds = delta / 1_000_000_000 if max(started_at, completed_at) >= 10**15 else float(delta)
    if seconds < 0 or seconds > 24 * 60 * 60:
        return None
    return seconds


def _directory_usage(path: Path) -> dict:
    if not path.exists():
        return {"files": 0, "bytes": 0, "status": "missing"}
    files = 0
    total = 0
    for item in path.rglob("*"):
        if not item.is_file() or item.is_symlink():
            continue
        files += 1
        total += item.stat().st_size
    return {"files": files, "bytes": total, "status": "available"}


def _safe_table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    available = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in COUNTED_TABLES if table in available
    }


def build_report(
    database: Path,
    knowledge_dir: Path,
    artifacts_dir: Path,
    input_price_per_million: float | None = None,
    output_price_per_million: float | None = None,
) -> dict:
    if not database.exists():
        raise FileNotFoundError(f"数据库不存在：{database}")

    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        runs = conn.execute(
            """SELECT status, started_at, completed_at, input_tokens_estimate,
                      output_tokens_estimate, tool_call_count FROM runs"""
        ).fetchall()
        event_types = [row[0] for row in conn.execute(
            "SELECT type FROM run_events WHERE type IN ('model_request', 'model_call')"
        ).fetchall()]
        table_counts = _safe_table_counts(conn)

    durations = [
        duration for row in runs
        if (duration := _duration_seconds(row["started_at"], row["completed_at"])) is not None
    ]
    status_counts: dict[str, int] = {}
    for row in runs:
        status = str(row["status"] or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    input_tokens = sum(int(row["input_tokens_estimate"] or 0) for row in runs)
    output_tokens = sum(int(row["output_tokens_estimate"] or 0) for row in runs)
    tool_calls = sum(int(row["tool_call_count"] or 0) for row in runs)
    estimated_cost = None
    if input_price_per_million is not None and output_price_per_million is not None:
        estimated_cost = round(
            input_tokens / 1_000_000 * input_price_per_million
            + output_tokens / 1_000_000 * output_price_per_million,
            6,
        )

    total = len(runs)
    completed = status_counts.get("completed", 0)
    return {
        "report_version": 1,
        "scope": "personal_hosted_metadata_only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample": {
            "runs": total,
            "status": "sufficient" if total >= 30 else "insufficient",
            "status_counts": dict(sorted(status_counts.items())),
        },
        "performance": {
            "completion_rate": round(completed / total, 4) if total else None,
            "duration_samples": len(durations),
            "duration_samples_excluded": total - len(durations),
            "average_seconds": round(sum(durations) / len(durations), 3) if durations else None,
            "p50_seconds": _percentile(durations, 0.50),
            "p95_seconds": _percentile(durations, 0.95),
            "model_call_events": len(event_types),
            "model_calls_per_run": round(len(event_types) / total, 3) if total else None,
            "tool_calls": tool_calls,
            "tool_calls_per_run": round(tool_calls / total, 3) if total else None,
        },
        "usage": {
            "input_tokens_estimate": input_tokens,
            "output_tokens_estimate": output_tokens,
            "tokens_per_run_estimate": round((input_tokens + output_tokens) / total, 3) if total else None,
            "pricing": {
                "currency": "caller_defined",
                "input_per_million": input_price_per_million,
                "output_per_million": output_price_per_million,
                "estimated_total": estimated_cost,
            },
        },
        "storage": {
            "database_bytes": database.stat().st_size,
            "knowledge": _directory_usage(knowledge_dir),
            "artifacts": _directory_usage(artifacts_dir),
            "table_counts": table_counts,
        },
        "privacy": {
            "reads_message_content": False,
            "reads_knowledge_content": False,
            "reads_artifact_content": False,
            "reads_credentials": False,
            "notes": [
                "报告只读取 Run 数值元数据、事件类型、表记录数和文件大小。",
                "Token 为平台估算值；未提供单价时不计算货币成本。",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成个人托管测试版的隐私安全基线")
    parser.add_argument("--database", type=Path, default=Path("agent_platform.db"))
    parser.add_argument("--knowledge-dir", type=Path, default=Path("data/knowledge"))
    parser.add_argument("--artifacts-dir", type=Path, default=Path("data/artifacts"))
    parser.add_argument("--input-price-per-million", type=float)
    parser.add_argument("--output-price-per-million", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if any(value is not None and value < 0 for value in (args.input_price_per_million, args.output_price_per_million)):
        parser.error("模型单价不能为负数")
    if (args.input_price_per_million is None) != (args.output_price_per_million is None):
        parser.error("输入与输出单价必须同时提供")
    report = build_report(
        args.database, args.knowledge_dir, args.artifacts_dir,
        args.input_price_per_million, args.output_price_per_million,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
