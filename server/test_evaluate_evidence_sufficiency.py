import unittest
from pathlib import Path
from server.evaluate_evidence_sufficiency import evaluate, load_suite

class EvidenceEvaluationTests(unittest.TestCase):
    def test_fixed_suite_has_forty_passing_cases(self):
        suite = load_suite(Path(__file__).parent / "evals" / "evidence_sufficiency.json")
        report = evaluate(suite)
        self.assertEqual(report["summary"]["total"], 40)
        self.assertEqual(report["summary"]["failed"], 0)
