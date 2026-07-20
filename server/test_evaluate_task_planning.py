import unittest

from server.evaluate_task_planning import evaluate, load_suite


class TaskPlanningEvaluationTests(unittest.TestCase):
    def test_fixture_has_thirty_labeled_cases(self):
        suite = load_suite(__import__("pathlib").Path(__file__).parent / "evals" / "task_planning.json")
        self.assertGreaterEqual(len(suite["cases"]), 30)

    def test_invalid_or_missing_observations_do_not_pass(self):
        suite = {"cases": [{"id": "one", "expected": {"goal_keywords": ["目标"], "deliverable_keywords": ["交付"]}}]}
        result = evaluate(suite, {"one": {}})
        self.assertFalse(result["results"][0]["passed"])
        self.assertEqual(result["results"][0]["status"], "invalid_frame")
