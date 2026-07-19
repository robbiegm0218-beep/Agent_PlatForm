import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.decision_quality import (
    DEFAULT_SUITE, MIN_CITATION_SAMPLE, MIN_TASK_SAMPLE, anonymize_run,
    compare_experiment, evaluate_suite, load_feedback_rows, load_suite, policy_snapshot, summarize_feedback,
)
from server.app import infer_task_profile, plan_intent


class DecisionQualityTests(unittest.TestCase):
    def test_fixed_suite_meets_decision_baseline(self):
        report = evaluate_suite(load_suite(DEFAULT_SUITE), plan_intent, infer_task_profile)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["metrics"]["retrieval_omission_rate"], 0.0)
        self.assertEqual(report["metrics"]["over_retrieval_rate"], 0.0)
        self.assertEqual(report["metrics"]["clarification_miss_rate"], 0.0)
        self.assertEqual(report["metrics"]["task_success_rate"], 1.0)
        self.assertTrue(report["groups"])

    def test_anonymization_never_exports_prompt_or_user_id(self):
        result = anonymize_run({"id": "run-1", "thread_id": "thread-1", "user_id": "user-1", "content": "private", "execution_context": {"task_preview": "private", "task_tier": "quick"}})
        self.assertNotIn("user_id", result)
        self.assertNotIn("content", result)
        self.assertNotIn("private", json.dumps(result))
        self.assertEqual(len(result["run"]), 16)

    def test_feedback_requires_sufficient_sample_before_claim(self):
        report = summarize_feedback([{"status": "completed", "citation_correct": True}])
        self.assertFalse(report["sufficient_for_claim"])
        rows = [{"status": "completed", "citation_correct": True} for _ in range(max(MIN_CITATION_SAMPLE, MIN_TASK_SAMPLE))]
        self.assertTrue(summarize_feedback(rows)["sufficient_for_claim"])

    def test_experiment_rejects_multiple_variable_declaration_and_rolls_back_regression(self):
        baseline = {"metrics": {"retrieval_omission_rate": 0.0, "over_retrieval_rate": 0.0, "clarification_miss_rate": 0.0, "citation_accuracy": 1.0, "task_success_rate": 1.0}}
        candidate = {"metrics": {**baseline["metrics"], "task_success_rate": 0.5}}
        self.assertEqual(compare_experiment(baseline, candidate, changed_variable="planner_prompt")["decision"], "rollback")
        with self.assertRaises(ValueError):
            compare_experiment(baseline, candidate, changed_variable="planner,retrieval")

    def test_policy_snapshot_is_versioned(self):
        self.assertTrue(policy_snapshot()["version"])

    def test_feedback_loader_reads_no_prompt_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "runs.db"
            conn = sqlite3.connect(database)
            try:
                conn.execute("CREATE TABLE runs (id TEXT, status TEXT, content TEXT)")
                conn.execute("CREATE TABLE run_feedback (run_id TEXT, citation_correct INTEGER)")
                conn.execute("INSERT INTO runs VALUES ('r1', 'completed', 'private prompt')")
                conn.execute("INSERT INTO run_feedback VALUES ('r1', 1)")
                conn.commit()
            finally:
                conn.close()
            self.assertEqual(load_feedback_rows(database), [{"status": "completed", "citation_correct": 1}])


if __name__ == "__main__":
    unittest.main()
