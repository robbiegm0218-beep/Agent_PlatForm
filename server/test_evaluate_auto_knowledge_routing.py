import json
import unittest

from server.evaluate_auto_knowledge_routing import (
    DEFAULT_FIXTURE,
    evaluate,
    validate_fixture,
)


class AutoKnowledgeRoutingEvaluationTests(unittest.TestCase):
    def setUp(self):
        payload = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
        self.fixture = validate_fixture(payload)

    def test_fixture_contract_and_required_categories(self):
        self.assertGreaterEqual(len(self.fixture["cases"]), 12)
        categories = {case["category"] for case in self.fixture["cases"]}
        self.assertEqual(
            categories,
            {"explicit", "implicit_anchor", "negative", "mode_control"},
        )
        negative_ids = {
            case["id"]
            for case in self.fixture["cases"]
            if case["category"] == "negative"
        }
        self.assertTrue({
            "negative-generic-project-plan",
            "negative-generate-html",
            "negative-generic-concept",
            "negative-code-change",
            "negative-translation",
            "negative-small-talk",
        } <= negative_ids)

    def test_current_baseline_reproduces_over_retrieval(self):
        report = evaluate(self.fixture)
        self.assertGreater(report["stages"]["automatic_probes"], 0)
        self.assertGreater(report["stages"]["candidates_returned"], 0)
        self.assertGreater(report["stages"]["selected"], 0)
        self.assertGreater(report["quality"]["false_positive"], 0)
        self.assertIn(
            "negative-generic-project-plan",
            report["false_positive_case_ids"],
        )
        rendered = json.dumps(report, ensure_ascii=False)
        for case in self.fixture["cases"]:
            self.assertNotIn(case["query"], rendered)
        for document in self.fixture["documents"]:
            self.assertNotIn(document["content"], rendered)

    def test_explicit_implicit_and_mode_controls_are_observable(self):
        report = evaluate(self.fixture)
        by_id = {item["id"]: item for item in report["results"]}
        self.assertTrue(by_id["explicit-uploaded-training"]["selected"])
        self.assertFalse(by_id["explicit-uploaded-training"]["automatic_probe"])
        self.assertTrue(by_id["implicit-training-name"]["selected"])
        self.assertTrue(by_id["implicit-training-name"]["automatic_probe"])
        self.assertFalse(by_id["control-off-explicit"]["selected"])
        self.assertTrue(by_id["control-required-training"]["selected"])

    def test_v2_intent_gate_meets_the_frozen_routing_boundary(self):
        report = evaluate(self.fixture, gate_v2=True)
        self.assertEqual(report["policy"], "intent-gate-v2")
        self.assertEqual(report["quality"]["false_positive"], 0)
        self.assertEqual(report["quality"]["false_negative"], 0)
        self.assertEqual(report["quality"]["precision"], 1.0)
        self.assertEqual(report["quality"]["recall"], 1.0)
        self.assertEqual(report["quality"]["negative_accuracy"], 1.0)

    def test_v2_strong_gate_preserves_the_frozen_positive_and_negative_cases(self):
        report = evaluate(self.fixture, gate_v2=True, strong_gate=True)
        self.assertEqual(report["policy"], "strong-relevance-gate-v2")
        self.assertEqual(report["quality"]["false_positive"], 0)
        self.assertEqual(report["quality"]["false_negative"], 0)
        self.assertEqual(report["quality"]["precision"], 1.0)
        self.assertEqual(report["quality"]["recall"], 1.0)

    def test_validation_rejects_duplicate_case_ids(self):
        duplicate = {
            "documents": self.fixture["documents"],
            "cases": self.fixture["cases"] + [dict(self.fixture["cases"][0])],
        }
        with self.assertRaisesRegex(ValueError, "重复"):
            validate_fixture(duplicate)


if __name__ == "__main__":
    unittest.main()
