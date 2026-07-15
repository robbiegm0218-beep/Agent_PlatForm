#!/usr/bin/env python3
"""Verify that a SQLite backup can be restored without mutating the source database."""
import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

try:
    from server.backup import copy_database
except ModuleNotFoundError:
    from backup import copy_database


def database_fingerprint(path: Path) -> dict:
    with sqlite3.connect(path) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("users", "threads", "messages", "runs")
            if table in tables
        }
    if integrity != "ok":
        raise RuntimeError(f"SQLite 完整性检查失败：{integrity}")
    return {"integrity": integrity, "counts": counts}


def run_drill(source: Path) -> dict:
    if not source.is_file():
        raise ValueError(f"数据库不存在：{source}")
    source_fingerprint = database_fingerprint(source)
    with tempfile.TemporaryDirectory(prefix="agent-platform-recovery-") as directory:
        backup = Path(directory) / "backup.db"
        restored = Path(directory) / "restored.db"
        copy_database(source, backup)
        copy_database(backup, restored)
        restored_fingerprint = database_fingerprint(restored)
    if source_fingerprint != restored_fingerprint:
        raise RuntimeError("恢复后数据库指纹不一致")
    return {"ok": True, "database": str(source), "fingerprint": source_fingerprint}


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent_Platform SQLite recovery drill")
    parser.add_argument("--database", type=Path, default=Path(__file__).resolve().parents[1] / "agent_platform.db")
    args = parser.parse_args()
    print(json.dumps(run_drill(args.database), ensure_ascii=False))


if __name__ == "__main__":
    main()
