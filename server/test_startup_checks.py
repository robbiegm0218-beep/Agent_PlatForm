import tempfile
import unittest
from pathlib import Path

from server.startup_checks import build_startup_report


class StartupChecksTests(unittest.TestCase):
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
