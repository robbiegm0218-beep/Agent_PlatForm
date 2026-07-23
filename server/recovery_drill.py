#!/usr/bin/env python3
"""Verify that a SQLite backup can be restored without mutating the source database."""
import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

if __package__ in {None, ""}:
    # Keep the documented file-path invocation working as well as ``-m``.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.backup import copy_database
from server.upgrade import prepare_snapshot, restore_snapshot_isolated


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


def run_full_drill(database: Path, data_dir: Path) -> dict:
    """Exercise a full isolated snapshot restore without changing the source instance."""
    if not database.is_file():
        raise ValueError(f"数据库不存在：{database}")
    source_fingerprint = database_fingerprint(database)
    with tempfile.TemporaryDirectory(prefix="agent-platform-full-recovery-") as directory:
        root = Path(directory)
        snapshot = prepare_snapshot(database, data_dir, root / "backups")
        restored = restore_snapshot_isolated(snapshot, root / "restores")
        restored_fingerprint = database_fingerprint(restored / "agent_platform.db")
        manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
        knowledge_files = sum(1 for item in (restored / "data" / "knowledge").rglob("*") if item.is_file())
        artifact_files = sum(1 for item in (restored / "data" / "artifacts").rglob("*") if item.is_file())
    if source_fingerprint != restored_fingerprint:
        raise RuntimeError("全量恢复后数据库指纹不一致")
    if knowledge_files != manifest["knowledge"]["files"] or artifact_files != manifest["artifacts"]["files"]:
        raise RuntimeError("全量恢复后文件清单不一致")
    return {"ok": True, "database": str(database), "fingerprint": source_fingerprint, "knowledge_files": knowledge_files, "artifact_files": artifact_files}


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent_Platform SQLite recovery drill")
    parser.add_argument("--database", type=Path, default=Path(__file__).resolve().parents[1] / "agent_platform.db")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    result = run_full_drill(args.database, args.data_dir) if args.data_dir else run_drill(args.database)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
