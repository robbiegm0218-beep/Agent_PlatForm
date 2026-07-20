import json, unittest
from pathlib import Path
from server.evaluate_task_verification import evaluate
class VerificationEvaluationTests(unittest.TestCase):
 def test_fixed_suite(self):
  report=evaluate(json.loads((Path(__file__).parent/'evals'/'task_verification.json').read_text()))
  self.assertEqual(report['summary'],{'total':35,'passed':35,'failed':0})
