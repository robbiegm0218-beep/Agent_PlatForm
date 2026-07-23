import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.model_provider import DeepSeekConfig
from server.recovery_drill import run_drill, run_full_drill
from server.smoke_deepseek import run_smoke


class OperationsTests(unittest.TestCase):
    def test_deepseek_smoke_dry_run_never_calls_the_network(self):
        result = run_smoke(
            DeepSeekConfig(api_key="test-key", base_url="https://example.invalid"),
            "test-model",
            dry_run=True,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["model"], "test-model")

    def test_recovery_drill_round_trips_a_sqlite_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "source.db"
            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
                conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY)")
                conn.execute("CREATE TABLE messages (id TEXT PRIMARY KEY)")
                conn.execute("CREATE TABLE runs (id TEXT PRIMARY KEY)")
                conn.execute("INSERT INTO users (id) VALUES ('user_1')")
            result = run_drill(database)

            self.assertTrue(result["ok"])

    def test_full_recovery_drill_includes_knowledge_and_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "agent.db"
            data = root / "data"
            (data / "knowledge").mkdir(parents=True)
            (data / "artifacts").mkdir()
            (data / "knowledge" / "note.md").write_text("note", encoding="utf-8")
            (data / "artifacts" / "answer.md").write_text("answer", encoding="utf-8")
            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE users (id TEXT)")
                conn.execute("INSERT INTO users VALUES ('u1')")
            result = run_full_drill(database, data)
            self.assertTrue(result["ok"])
            self.assertEqual(result["knowledge_files"], 1)
            self.assertEqual(result["artifact_files"], 1)
        self.assertEqual(result["fingerprint"]["integrity"], "ok")
        self.assertEqual(result["fingerprint"]["counts"]["users"], 1)
