import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.upgrade import prepare_snapshot, restore_snapshot, restore_snapshot_isolated


class UpgradeSnapshotTests(unittest.TestCase):
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
