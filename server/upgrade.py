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


def current_schema_version(database: Path) -> int:
    """Read the recorded migration version without changing the source database."""
    if not database.is_file():
        return 0
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if not exists:
            return 0
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0] or 0)


def _upgrade_state_path(data_dir: Path) -> Path:
    return data_dir / "upgrade-state.json"


def _read_upgrade_state(data_dir: Path) -> dict:
    path = _upgrade_state_path(data_dir)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_upgrade_state(data_dir: Path, payload: dict) -> None:
    """Persist only operational metadata, atomically, never database contents."""
    path = _upgrade_state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def prepare_automatic_upgrade(database: Path, data_dir: Path, backup_root: Path) -> dict:
    """Create one pre-upgrade snapshot when app/schema state actually changes.

    This is deliberately called by the service entrypoint rather than ``init_db``:
    test setup and one-off maintenance commands must not create backups of arbitrary
    databases.  A new, empty instance needs no snapshot; an existing instance with
    no state file is protected once before its first managed startup.
    """
    if not database.is_file():
        return {"required": False, "reason": "new_database", "before_schema_version": 0}
    before_schema = current_schema_version(database)
    state = _read_upgrade_state(data_dir)
    previous = state.get("last_success") if isinstance(state.get("last_success"), dict) else {}
    version_changed = not previous or previous.get("app_version") != APP_VERSION
    migration_pending = before_schema < LATEST_SCHEMA_VERSION
    if not version_changed and not migration_pending:
        return {
            "required": False,
            "reason": "up_to_date",
            "before_schema_version": before_schema,
            "previous_app_version": previous.get("app_version", APP_VERSION),
        }
    snapshot = prepare_snapshot(database, data_dir, backup_root)
    return {
        "required": True,
        "reason": "app_version_changed" if version_changed else "migration_pending",
        "snapshot": str(snapshot),
        "before_schema_version": before_schema,
        "previous_app_version": previous.get("app_version", ""),
    }


def record_automatic_upgrade(data_dir: Path, attempt: dict, *, success: bool, after_schema_version: int | None = None, error: str = "") -> dict:
    """Record the outcome needed for recovery without recording user data or secrets."""
    previous = _read_upgrade_state(data_dir)
    event = {
        "at": datetime.now(timezone.utc).isoformat(),
        "success": bool(success),
        "app_version": APP_VERSION,
        "before_schema_version": int(attempt.get("before_schema_version", 0)),
        "after_schema_version": int(after_schema_version or 0),
        "reason": str(attempt.get("reason", "")),
        "snapshot": str(attempt.get("snapshot", "")),
        "error": str(error)[:300],
    }
    history = previous.get("history") if isinstance(previous.get("history"), list) else []
    payload = {"format": "agent-platform-upgrade-state/v1", "history": (history + [event])[-20:]}
    if success:
        payload["last_success"] = {
            "app_version": APP_VERSION,
            "schema_version": event["after_schema_version"],
            "at": event["at"],
            "snapshot": event["snapshot"],
        }
    elif isinstance(previous.get("last_success"), dict):
        payload["last_success"] = previous["last_success"]
    _write_upgrade_state(data_dir, payload)
    return event


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
        "source_schema_version": current_schema_version(database),
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
