import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.model_provider import DeepSeekConfig
from server.recovery_drill import run_drill
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
        self.assertEqual(result["fingerprint"]["integrity"], "ok")
        self.assertEqual(result["fingerprint"]["counts"]["users"], 1)
