import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.evaluate_personal_hosting import build_report


class PersonalHostingBaselineTests(unittest.TestCase):
    def test_report_uses_metadata_and_storage_sizes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "agent.db"
            knowledge = root / "knowledge"
            artifacts = root / "artifacts"
            knowledge.mkdir(); artifacts.mkdir()
            (knowledge / "source.bin").write_bytes(b"12345")
            (artifacts / "result.bin").write_bytes(b"123")
            with sqlite3.connect(database) as conn:
                conn.executescript("""
                    CREATE TABLE runs (
                        status TEXT, started_at INTEGER, completed_at INTEGER,
                        input_tokens_estimate INTEGER, output_tokens_estimate INTEGER,
                        tool_call_count INTEGER
                    );
                    CREATE TABLE run_events (type TEXT);
                    CREATE TABLE users (id TEXT);
                    CREATE TABLE messages (id TEXT, content TEXT);
                """)
                conn.executemany(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        ("completed", 10, 14, 100, 50, 1),
                        ("completed", 10**18, 10**18 + 2 * 10**9, 200, 150, 0),
                        ("failed", 20, None, 0, 0, 0),
                    ],
                )
                conn.executemany("INSERT INTO run_events VALUES (?)", [("model_request",), ("model_call",)])
                conn.execute("INSERT INTO users VALUES ('user-secret-id')")
                conn.execute("INSERT INTO messages VALUES ('m1', 'private message')")

            report = build_report(database, knowledge, artifacts, 1.0, 2.0)

            self.assertEqual(report["sample"]["runs"], 3)
            self.assertEqual(report["sample"]["status_counts"], {"completed": 2, "failed": 1})
            self.assertEqual(report["performance"]["duration_samples"], 2)
            self.assertEqual(report["performance"]["p50_seconds"], 2.0)
            self.assertEqual(report["performance"]["p95_seconds"], 4.0)
            self.assertEqual(report["usage"]["input_tokens_estimate"], 300)
            self.assertEqual(report["usage"]["output_tokens_estimate"], 200)
            self.assertEqual(report["usage"]["pricing"]["estimated_total"], 0.0007)
            self.assertEqual(report["storage"]["knowledge"]["bytes"], 5)
            self.assertEqual(report["storage"]["artifacts"]["bytes"], 3)
            self.assertEqual(report["storage"]["table_counts"]["messages"], 1)
            self.assertNotIn("private message", str(report))
            self.assertNotIn("user-secret-id", str(report))
            self.assertFalse(report["privacy"]["reads_message_content"])


if __name__ == "__main__":
    unittest.main()
