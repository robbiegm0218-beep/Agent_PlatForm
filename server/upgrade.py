#!/usr/bin/env python3
"""Prepare and restore bounded upgrade snapshots for personal hosting."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from server.schema_migrations import LATEST_SCHEMA_VERSION
from server.version import APP_VERSION


def _copy_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_db, sqlite3.connect(target) as target_db:
        source_db.backup(target_db)


def _tree_stats(path: Path) -> dict:
    files = [item for item in path.rglob("*") if item.is_file() and not item.is_symlink()] if path.exists() else []
    return {"files": len(files), "bytes": sum(item.stat().st_size for item in files)}


def prepare_snapshot(database: Path, data_dir: Path, backup_root: Path) -> Path:
    if not database.is_file():
        raise FileNotFoundError(f"数据库不存在：{database}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = backup_root / f"agent-platform-{stamp}"
    if snapshot.exists():
        raise FileExistsError(f"备份目录已存在：{snapshot}")
    snapshot.mkdir(parents=True)
    _copy_database(database, snapshot / "agent_platform.db")
    for name in ("knowledge", "artifacts"):
        source = data_dir / name
        if source.exists():
            shutil.copytree(source, snapshot / name)
    manifest = {
        "app_version": APP_VERSION,
        "target_schema_version": LATEST_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_bytes": (snapshot / "agent_platform.db").stat().st_size,
        "knowledge": _tree_stats(snapshot / "knowledge"),
        "artifacts": _tree_stats(snapshot / "artifacts"),
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return snapshot


def restore_snapshot(snapshot: Path, database: Path, data_dir: Path) -> None:
    manifest = snapshot / "manifest.json"
    source_database = snapshot / "agent_platform.db"
    if not manifest.is_file() or not source_database.is_file():
        raise ValueError("升级备份缺少 manifest.json 或数据库文件")
    json.loads(manifest.read_text(encoding="utf-8"))
    _copy_database(source_database, database)
    for name in ("knowledge", "artifacts"):
        source = snapshot / name
        destination = data_dir / name
        if destination.exists():
            shutil.rmtree(destination)
        if source.exists():
            shutil.copytree(source, destination)
        else:
            destination.mkdir(parents=True, exist_ok=True)


def restore_snapshot_isolated(snapshot: Path, restore_root: Path) -> Path:
    """Restore into a fresh directory without changing the active instance."""
    manifest = snapshot / "manifest.json"
    source_database = snapshot / "agent_platform.db"
    if not manifest.is_file() or not source_database.is_file():
        raise ValueError("升级备份缺少 manifest.json 或数据库文件")
    json.loads(manifest.read_text(encoding="utf-8"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = restore_root / f"agent-platform-restore-{stamp}"
    if destination.exists():
        raise FileExistsError(f"隔离恢复目录已存在：{destination}")
    destination.mkdir(parents=True)
    _copy_database(source_database, destination / "agent_platform.db")
    for name in ("knowledge", "artifacts"):
        source = snapshot / name
        if source.exists():
            shutil.copytree(source, destination / "data" / name)
        else:
            (destination / "data" / name).mkdir(parents=True, exist_ok=True)
    return destination


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="个人托管版升级前备份与恢复")
    parser.add_argument("action", choices=("prepare", "restore"))
    parser.add_argument("--database", type=Path, default=root / "agent_platform.db")
    parser.add_argument("--data-dir", type=Path, default=root / "data")
    parser.add_argument("--backup-root", type=Path, default=root / "data" / "upgrade-backups")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--restore-root", type=Path, default=root / "data" / "restore-previews")
    parser.add_argument("--replace", action="store_true", help="恢复时覆盖指定数据库与数据目录（默认仅隔离恢复）")
    args = parser.parse_args()
    if args.action == "prepare":
        print(prepare_snapshot(args.database, args.data_dir, args.backup_root))
    else:
        if not args.snapshot:
            parser.error("restore 必须提供 --snapshot")
        if args.replace:
            restore_snapshot(args.snapshot, args.database, args.data_dir)
            print("已覆盖恢复；请重新启动服务并检查健康状态。")
        else:
            print(restore_snapshot_isolated(args.snapshot, args.restore_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
