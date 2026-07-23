import tempfile
import unittest
import json
import logging
from pathlib import Path

from server.app import JsonLogFormatter
from server.startup_checks import build_startup_report


class StartupChecksTests(unittest.TestCase):
    def test_json_log_formatter_keeps_operational_fields_and_redacts_secrets(self):
        record = logging.LogRecord(
            "agent_platform", logging.WARNING, __file__, 1,
            "provider failed api_key=secret-value", (), None,
        )
        record.run_id = "run_123"
        payload = json.loads(JsonLogFormatter().format(record))
        self.assertEqual(payload["run_id"], "run_123")
        self.assertIn("[REDACTED]", payload["message"])

    def test_creates_required_directories_without_requiring_optional_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = build_startup_report(
                root / "db" / "agent.db", root / "knowledge", root / "artifacts",
                model_configured=False, create_directories=True,
            )
        self.assertTrue(report["required_ready"])
        self.assertFalse(report["optional_ready"])
        self.assertFalse(report["checks"]["model"]["required"])
        self.assertIn("free_bytes", report["checks"]["disk_space"])
