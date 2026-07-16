import unittest

from server.evaluate_skill_contracts import evaluate


class SkillContractEvaluationTests(unittest.TestCase):
    def test_all_builtin_skills_have_complete_passing_contracts(self):
        report = evaluate()
        self.assertEqual(report["skill_count"], 5)
        self.assertGreaterEqual(report["case_count"], 9)
        self.assertEqual(report["trigger_accuracy"], 1.0)
        self.assertTrue(report["all_contracts_complete"])
        compared = evaluate(baseline={"skills": [{
            "skill_id": "research_brief", "version": "0.9.0", "trigger_accuracy": 0.5,
        }]})
        research = next(item for item in compared["skills"] if item["skill_id"] == "research_brief")
        self.assertEqual(research["comparison"]["previous_version"], "0.9.0")
        self.assertEqual(research["comparison"]["trigger_accuracy_delta"], 0.5)


if __name__ == "__main__":
    unittest.main()
