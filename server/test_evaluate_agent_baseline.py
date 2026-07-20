import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.evaluate_agent_baseline import build_report


class AgentBaselineTests(unittest.TestCase):
    def test_uses_only_run_metadata_and_marks_small_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.db"
            with sqlite3.connect(path) as conn:
                conn.executescript("""
                    CREATE TABLE runs (id TEXT, status TEXT, execution_context TEXT, started_at INTEGER, completed_at INTEGER);
                    CREATE TABLE run_events (run_id TEXT, type TEXT);
                """)
                conn.execute("INSERT INTO runs VALUES ('r1', 'completed', '{\"intent_plan\": {\"knowledge_needed\": true}, \"retrieval_trace\": {\"sufficient\": true}}', 10, 20)")
                conn.executemany("INSERT INTO run_events VALUES ('r1', ?)", [("tool_call",), ("tool_result",)])
            report = build_report(path)
        self.assertEqual(report["sample"]["status"], "insufficient")
        self.assertEqual(report["metrics"]["tool_success_rate"], 1.0)
        self.assertIsNone(report["metrics"]["unsupported_claim_rate"])
