#!/usr/bin/env python3
"""Privacy-safe local operational monitor for a personal hosted instance."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from server.evaluate_personal_hosting import build_report


def _latest_backup_age_seconds(backup_root: Path, current: float) -> float | None:
    snapshots = [item for item in backup_root.glob("agent-platform-*") if (item / "manifest.json").is_file()] if backup_root.exists() else []
    if not snapshots:
        return None
    return max(0.0, current - max(item.stat().st_mtime for item in snapshots))


def _runtime_signals(database: Path, current_ns: int) -> dict:
    """Read only aggregate operational metadata; no prompts, answers, or documents."""
    with sqlite3.connect(database) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        event_counts: dict[str, int] = {}
        if "run_events" in tables:
            for row in conn.execute(
                "SELECT type, COUNT(*) FROM run_events WHERE type IN ('model_request', 'model_error') GROUP BY type"
            ):
                event_counts[str(row[0])] = int(row[1])
        usage = {"daily_tokens": 0, "monthly_tokens": 0}
        if "runs" in tables:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
            if {"started_at", "input_tokens_estimate", "output_tokens_estimate"}.issubset(columns):
                for label, since in (
                    ("daily_tokens", current_ns - 24 * 60 * 60 * 1_000_000_000),
                    ("monthly_tokens", current_ns - 30 * 24 * 60 * 60 * 1_000_000_000),
                ):
                    row = conn.execute(
                        "SELECT COALESCE(SUM(input_tokens_estimate + output_tokens_estimate), 0) FROM runs WHERE started_at >= ?",
                        (since,),
                    ).fetchone()
                    usage[label] = int(row[0] or 0)
    requests = event_counts.get("model_request", 0)
    errors = event_counts.get("model_error", 0)
    return {
        "model_requests": requests,
        "model_errors": errors,
        "model_error_rate": round(errors / requests, 4) if requests else None,
        **usage,
    }


def build_operational_report(database: Path, data_dir: Path, backup_root: Path, *, minimum_free_disk_bytes: int = 1_073_741_824, maximum_backup_age_seconds: int = 86_400, maximum_p95_seconds: float = 60.0, maximum_model_error_rate: float = 0.2, daily_token_limit: int = 200_000, monthly_token_limit: int = 2_000_000, budget_warning_ratio: float = 0.8) -> dict:
    baseline = build_report(database, data_dir / "knowledge", data_dir / "artifacts")
    disk = shutil.disk_usage(data_dir if data_dir.exists() else database.parent)
    backup_age = _latest_backup_age_seconds(backup_root, time.time())
    runs = baseline["sample"]["runs"]
    failed = baseline["sample"]["status_counts"].get("failed", 0)
    failure_rate = round(failed / runs, 4) if runs else None
    signals = _runtime_signals(database, time.time_ns())
    alerts = []
    if disk.free < minimum_free_disk_bytes:
        alerts.append({"level": "critical", "code": "disk_low", "message": "剩余磁盘空间低于配置阈值"})
    if backup_age is None:
        alerts.append({"level": "warning", "code": "backup_missing", "message": "尚未发现升级快照备份"})
    elif backup_age > maximum_backup_age_seconds:
        alerts.append({"level": "warning", "code": "backup_stale", "message": "最新升级快照超过备份时效"})
    if runs >= 5 and failure_rate is not None and failure_rate >= 0.2:
        alerts.append({"level": "warning", "code": "run_failure_rate_high", "message": "近期 Run 失败率达到 20% 或以上"})
    p95 = baseline["performance"]["p95_seconds"]
    if p95 is not None and p95 > maximum_p95_seconds:
        alerts.append({"level": "warning", "code": "run_latency_high", "message": "Run P95 时延超过配置阈值"})
    if signals["model_requests"] >= 3 and signals["model_error_rate"] is not None and signals["model_error_rate"] >= maximum_model_error_rate:
        alerts.append({"level": "warning", "code": "model_error_rate_high", "message": "模型请求错误率达到配置阈值"})
    if daily_token_limit and signals["daily_tokens"] >= daily_token_limit * budget_warning_ratio:
        alerts.append({"level": "warning", "code": "daily_token_budget_high", "message": "每日 Token 使用量接近预算上限"})
    if monthly_token_limit and signals["monthly_tokens"] >= monthly_token_limit * budget_warning_ratio:
        alerts.append({"level": "warning", "code": "monthly_token_budget_high", "message": "每月 Token 使用量接近预算上限"})
    return {
        "report_version": 1,
        "scope": "personal_hosted_metadata_only",
        "status": "critical" if any(item["level"] == "critical" for item in alerts) else "warning" if alerts else "ok",
        "alerts": alerts,
        "metrics": {"runs": runs, "failure_rate": failure_rate, "p95_seconds": p95, "model_call_events": baseline["performance"]["model_call_events"], **signals},
        "storage": {"free_bytes": int(disk.free), "minimum_free_bytes": minimum_free_disk_bytes, "latest_backup_age_seconds": backup_age},
        "privacy": baseline["privacy"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="个人托管运行状态与本地告警检查")
    # Keep local-development defaults, while honoring the runtime locations
    # supplied by Docker Compose. This also makes `python -m ...` usable
    # directly inside the production container.
    data_dir = Path(os.environ.get("AGENT_DATA_DIR", "data"))
    parser.add_argument("--database", type=Path, default=Path(os.environ.get("AGENT_DATABASE_PATH", "agent_platform.db")))
    parser.add_argument("--data-dir", type=Path, default=data_dir)
    parser.add_argument("--backup-root", type=Path, default=Path(os.environ.get("AGENT_UPGRADE_BACKUP_ROOT", str(data_dir / "upgrade-backups"))))
    parser.add_argument("--minimum-free-disk-bytes", type=int, default=1_073_741_824)
    parser.add_argument("--maximum-backup-age-seconds", type=int, default=86_400)
    parser.add_argument("--maximum-p95-seconds", type=float, default=60.0)
    parser.add_argument("--maximum-model-error-rate", type=float, default=0.2)
    parser.add_argument("--daily-token-limit", type=int, default=200_000)
    parser.add_argument("--monthly-token-limit", type=int, default=2_000_000)
    parser.add_argument("--budget-warning-ratio", type=float, default=0.8)
    args = parser.parse_args()
    report = build_operational_report(args.database, args.data_dir, args.backup_root, minimum_free_disk_bytes=args.minimum_free_disk_bytes, maximum_backup_age_seconds=args.maximum_backup_age_seconds, maximum_p95_seconds=args.maximum_p95_seconds, maximum_model_error_rate=args.maximum_model_error_rate, daily_token_limit=args.daily_token_limit, monthly_token_limit=args.monthly_token_limit, budget_warning_ratio=args.budget_warning_ratio)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["status"] == "critical" else 1 if report["status"] == "warning" else 0


if __name__ == "__main__":
    raise SystemExit(main())
