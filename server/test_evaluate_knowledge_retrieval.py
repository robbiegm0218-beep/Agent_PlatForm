import json
import unittest

from server.evaluate_knowledge_retrieval import DEFAULT_FIXTURE, evaluate, validate_cases


class KnowledgeRetrievalEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.cases = validate_cases(json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8")))

    def test_fixture_contract_and_coverage(self):
        self.assertGreaterEqual(len(self.cases), 20)
        self.assertGreaterEqual(sum(case["expect_empty"] for case in self.cases), 5)
        self.assertGreaterEqual(sum("expected_neighbor_positions" in case for case in self.cases), 3)

    def test_retriever_meets_quality_gate(self):
        report = evaluate(self.cases)
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["recall_at_4"], 1.0)
        self.assertEqual(report["top1_accuracy"], 1.0)
        self.assertEqual(report["no_match_accuracy"], 1.0)
        self.assertEqual(report["neighbor_accuracy"], 1.0)

    def test_validation_rejects_duplicate_ids(self):
        cases = self.cases + [dict(self.cases[0])]
        with self.assertRaisesRegex(ValueError, "重复"):
            validate_cases(cases)


if __name__ == "__main__":
    unittest.main()
