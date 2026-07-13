#!/usr/bin/env python3
"""Create or restore a consistent local SQLite backup."""
import argparse
import sqlite3
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT_DIR / "agent_platform.db"


def copy_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_db, sqlite3.connect(target) as target_db:
        source_db.backup(target_db)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent_Platform SQLite backup utility")
    parser.add_argument("action", choices=("backup", "restore"))
    parser.add_argument("path", type=Path, help="Backup file path")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    if args.action == "backup":
        copy_database(args.database, args.path)
    else:
        copy_database(args.path, args.database)


if __name__ == "__main__":
    main()
