import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.upgrade import (
    prepare_automatic_upgrade,
    prepare_snapshot,
    record_automatic_upgrade,
    restore_snapshot,
    restore_snapshot_isolated,
)
from server.schema_migrations import LATEST_SCHEMA_VERSION


class UpgradeSnapshotTests(unittest.TestCase):
    def test_automatic_upgrade_snapshots_once_and_records_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "agent.db"
            data = root / "data"
            (data / "knowledge").mkdir(parents=True)
            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE marker (value TEXT)")
                conn.execute("INSERT INTO marker VALUES ('before')")

            attempt = prepare_automatic_upgrade(database, data, data / "upgrade-backups")
            self.assertTrue(attempt["required"])
            self.assertTrue(Path(attempt["snapshot"]).is_dir())
            event = record_automatic_upgrade(data, attempt, success=True, after_schema_version=LATEST_SCHEMA_VERSION)
            self.assertTrue(event["success"])

            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)")
                conn.execute("INSERT INTO schema_migrations VALUES (?)", (LATEST_SCHEMA_VERSION,))
            repeated = prepare_automatic_upgrade(database, data, data / "upgrade-backups")
            self.assertFalse(repeated["required"])
            self.assertEqual(repeated["reason"], "up_to_date")

    def test_snapshot_restores_database_knowledge_and_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "agent.db"
            data = root / "data"
            (data / "knowledge").mkdir(parents=True)
            (data / "artifacts").mkdir()
            (data / "knowledge" / "a.txt").write_text("knowledge", encoding="utf-8")
            (data / "artifacts" / "b.txt").write_text("artifact", encoding="utf-8")
            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE marker (value TEXT)")
                conn.execute("INSERT INTO marker VALUES ('before')")
            snapshot = prepare_snapshot(database, data, root / "backups")
            with sqlite3.connect(database) as conn:
                conn.execute("UPDATE marker SET value = 'after'")
            (data / "knowledge" / "a.txt").write_text("changed", encoding="utf-8")

            restore_snapshot(snapshot, database, data)

            with sqlite3.connect(database) as conn:
                self.assertEqual(conn.execute("SELECT value FROM marker").fetchone()[0], "before")
            self.assertEqual((data / "knowledge" / "a.txt").read_text(encoding="utf-8"), "knowledge")
            self.assertEqual((data / "artifacts" / "b.txt").read_text(encoding="utf-8"), "artifact")
            self.assertTrue((snapshot / "manifest.json").is_file())

    def test_isolated_restore_never_overwrites_production_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "agent.db"
            data = root / "data"
            (data / "knowledge").mkdir(parents=True)
            (data / "knowledge" / "note.md").write_text("original", encoding="utf-8")
            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE marker (value TEXT)")
                conn.execute("INSERT INTO marker VALUES ('before')")
            snapshot = prepare_snapshot(database, data, root / "backups")
            with sqlite3.connect(database) as conn:
                conn.execute("UPDATE marker SET value = 'production-changed'")
            restored = restore_snapshot_isolated(snapshot, root / "restore-previews")
            with sqlite3.connect(database) as conn:
                self.assertEqual(conn.execute("SELECT value FROM marker").fetchone()[0], "production-changed")
            with sqlite3.connect(restored / "agent_platform.db") as conn:
                self.assertEqual(conn.execute("SELECT value FROM marker").fetchone()[0], "before")
            self.assertEqual((restored / "data" / "knowledge" / "note.md").read_text(encoding="utf-8"), "original")
