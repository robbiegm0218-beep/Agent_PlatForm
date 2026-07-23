import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.operational_monitor import build_operational_report


class OperationalMonitorTests(unittest.TestCase):
    def test_reports_missing_backup_without_reading_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "agent.db"
            data = root / "data"
            (data / "knowledge").mkdir(parents=True)
            (data / "artifacts").mkdir()
            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE runs (status TEXT, started_at INTEGER, completed_at INTEGER, input_tokens_estimate INTEGER, output_tokens_estimate INTEGER, tool_call_count INTEGER)")
                conn.execute("CREATE TABLE run_events (type TEXT)")
                conn.execute("CREATE TABLE users (id TEXT)")
                conn.execute("CREATE TABLE threads (id TEXT)")
                conn.execute("CREATE TABLE messages (id TEXT)")
                conn.execute("CREATE TABLE knowledge_documents (id TEXT)")
                conn.execute("CREATE TABLE knowledge_chunks (id TEXT)")
                conn.execute("CREATE TABLE artifacts (id TEXT)")
                conn.execute("CREATE TABLE memories (id TEXT)")
                conn.execute("CREATE TABLE run_feedback (id TEXT)")
                conn.execute("CREATE TABLE citation_feedback_items (id TEXT)")
            report = build_operational_report(database, data, root / "backups")
            self.assertEqual(report["status"], "warning")
            self.assertEqual(report["alerts"][0]["code"], "backup_missing")
            self.assertFalse(report["privacy"]["reads_message_content"])

    def test_reports_model_and_budget_anomalies_from_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "agent.db"
            data = root / "data"
            (data / "knowledge").mkdir(parents=True)
            (data / "artifacts").mkdir()
            current = __import__("time").time_ns()
            with sqlite3.connect(database) as conn:
                conn.execute("CREATE TABLE runs (status TEXT, started_at INTEGER, completed_at INTEGER, input_tokens_estimate INTEGER, output_tokens_estimate INTEGER, tool_call_count INTEGER)")
                conn.execute("CREATE TABLE run_events (type TEXT)")
                for _ in range(3):
                    conn.execute("INSERT INTO runs VALUES ('completed', ?, ?, 90, 0, 0)", (current, current + 1_000_000))
                    conn.execute("INSERT INTO run_events VALUES ('model_request')")
                conn.execute("INSERT INTO run_events VALUES ('model_error')")
                for table in ("users", "threads", "messages", "knowledge_documents", "knowledge_chunks", "artifacts", "memories", "run_feedback", "citation_feedback_items"):
                    conn.execute(f"CREATE TABLE {table} (id TEXT)")
            report = build_operational_report(database, data, root / "backups", daily_token_limit=300, monthly_token_limit=1_000, budget_warning_ratio=0.8)
            codes = {item["code"] for item in report["alerts"]}
            self.assertIn("model_error_rate_high", codes)
            self.assertIn("daily_token_budget_high", codes)
            self.assertNotIn("monthly_token_budget_high", codes)  # daily/monthly are separately configurable
