import unittest

from server.evaluate_knowledge_hybrid import run


class KnowledgeHybridEvaluationTests(unittest.TestCase):
    def test_fixed_baseline_and_targeted_hybrid_gates_pass(self):
        report = run()
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["baseline"]["recall_at_4"], 1.0)
        self.assertEqual(report["baseline"]["top1_accuracy"], 1.0)
        self.assertEqual(report["baseline"]["no_match_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
