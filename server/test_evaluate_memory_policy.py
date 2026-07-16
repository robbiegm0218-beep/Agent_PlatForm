import json
import unittest

from server.evaluate_memory_policy import DEFAULT_FIXTURE, evaluate


class MemoryPolicyEvaluationTests(unittest.TestCase):
    def test_fixture_is_unique_and_covers_security_boundaries(self):
        cases = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 10)
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        self.assertEqual({case["operation"] for case in cases}, {"candidate", "validate", "select"})

    def test_quality_gate(self):
        cases = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
        report = evaluate(cases)
        self.assertEqual(report["accuracy"], 1.0, report["failures"])


if __name__ == "__main__":
    unittest.main()
