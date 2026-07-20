import json, sqlite3, tempfile, unittest
from pathlib import Path
from server.evaluate_p45_rollout import recommend, shadow_report
class P45RolloutTests(unittest.TestCase):
 def test_requires_fixed_gates_and_shadow_sample(self):
  self.assertEqual(recommend({"passed":False},{"status":"sufficient","v2_completion_rate":1}),"rollback")
  self.assertEqual(recommend({"passed":True},{"status":"insufficient"}),"shadow")
  self.assertEqual(recommend({"passed":True},{"status":"sufficient","v2_completion_rate":.95}),"administrator_canary")
  self.assertEqual(recommend({"passed":True},{"status":"sufficient","v2_completion_rate":.5}),"rollback")

 def test_rejects_quality_regression_and_holds_for_cost_or_feedback_review(self):
  fixed = {"passed": True}
  self.assertEqual(recommend(fixed, {"status":"sufficient", "v2_completion_rate":.95, "v1":{"completion_rate":.98}, "v2":{"completion_rate":.95}}), "rollback")
  self.assertEqual(recommend(fixed, {"status":"sufficient", "v2_completion_rate":.95, "v1":{"p95_seconds":2}, "v2":{"p95_seconds":5}}), "shadow")
  self.assertEqual(recommend(fixed, {"status":"sufficient", "v2_completion_rate":.95, "v1":{"ratings":20, "helpful_rate":.9}, "v2":{"ratings":20, "helpful_rate":.8}}), "shadow")

 def test_shadow_report_compares_metadata_without_reading_message_content(self):
  with tempfile.TemporaryDirectory() as directory:
   database = Path(directory) / "runs.db"
   with sqlite3.connect(database) as conn:
    conn.executescript("CREATE TABLE threads (id TEXT); CREATE TABLE runs (id TEXT, status TEXT, execution_context TEXT, started_at INTEGER, completed_at INTEGER, tool_call_count INTEGER, thread_id TEXT); CREATE TABLE run_feedback (run_id TEXT, rating INTEGER); CREATE TABLE run_events (run_id TEXT, type TEXT, payload TEXT);")
    conn.execute("INSERT INTO threads VALUES ('thread')")
    for index in range(30):
     context = {"task_frame": {"frame": {}}} if index >= 15 else {}
     conn.execute("INSERT INTO runs VALUES (?, 'completed', ?, 0, 1000000000, 1, 'thread')", (f"r{index}", json.dumps(context)))
     if index >= 15: conn.execute("INSERT INTO run_events VALUES (?, 'task_verified', ?)", (f"r{index}", '{"passed": true}'))
   report = shadow_report(database)
  self.assertEqual(report["v1_runs"], 15)
  self.assertEqual(report["v2_shadow_runs"], 15)
  self.assertEqual(report["v2"]["verification_failures"], 0)
