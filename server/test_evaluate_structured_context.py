import json
import unittest

from server.evaluate_structured_context import DEFAULT_FIXTURE, evaluate, validate_cases


class StructuredContextEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.cases = validate_cases(json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8")))

    def test_fixture_covers_required_boundaries(self):
        ids = {case["id"] for case in self.cases}
        self.assertGreaterEqual(len(ids), 10)
        self.assertIn("goal-correction", ids)
        self.assertIn("long-retention", ids)
        self.assertIn("continuation-inheritance", ids)

    def test_quality_gate(self):
        report = evaluate(self.cases)
        self.assertEqual(report["accuracy"], 1.0, report["failures"])
        self.assertEqual(report["failures"], [])

    def test_rejects_duplicate_ids(self):
        with self.assertRaisesRegex(ValueError, "重复"):
            validate_cases(self.cases + [dict(self.cases[0])])


if __name__ == "__main__":
    unittest.main()
