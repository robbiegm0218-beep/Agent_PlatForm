import unittest
from server.task_verifier import verify

class TaskVerifierTests(unittest.TestCase):
    def test_missing_evidence_requires_more_work(self):
        result = verify({"deliverables":[{"id":"d"}], "evidence_requirements":[{"id":"e"}]}, {"decision":"retrieve_more", "missing_requirement_ids":["e"]}, "根据资料，结论已经确定")
        self.assertFalse(result["passed"]); self.assertEqual(result["action"], "revise")

    def test_complete_answer_with_sufficient_evidence_passes(self):
        result = verify({"deliverables":[{"id":"d"}]}, {"decision":"sufficient"}, "已完成方案")
        self.assertTrue(result["passed"]); self.assertEqual(result["action"], "complete")

    def test_tool_failure_requires_an_explicit_unverified_boundary(self):
        result = verify({"deliverables":[{"id":"d"}]}, {"decision":"sufficient"}, "已完成方案", tool_events=[{"type":"tool_error"}])
        self.assertFalse(result["passed"])
        self.assertIn("工具失败后未说明未验证项", result["unsupported_claims"])

    def test_code_requires_observed_change_and_test_or_an_explicit_boundary(self):
        frame = {"goal": "实现代码改动", "deliverables": [{"id": "d"}]}
        unverified = verify(frame, {"decision": "sufficient"}, "已完成变更和测试")
        self.assertFalse(unverified["passed"])
        verified = verify(frame, {"decision": "sufficient"}, "已完成变更和测试", tool_events=[
            {"type": "tool_result", "tool_id": "apply_patch"}, {"type": "tool_result", "tool_id": "run_tests"},
        ])
        self.assertTrue(verified["passed"])

    def test_file_requires_actual_artifact(self):
        frame = {"deliverables": [{"id": "d"}]}
        missing = verify(frame, {"decision": "sufficient"}, "文件已生成", artifact_request={"kind": "markdown"})
        self.assertFalse(missing["passed"])
        verified = verify(frame, {"decision": "sufficient"}, "文件已生成", artifact_request={"kind": "markdown"}, artifact_records=[{"id": "a", "kind": "markdown"}])
        self.assertTrue(verified["passed"])
