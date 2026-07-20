import json
import unittest
from unittest.mock import patch

from server.task_planning import (
    TaskFrameValidationError, fallback_task_frame, parse_task_frame, task_frame_summary, validate_task_frame,
)
from server import app


class TaskPlanningTests(unittest.TestCase):
    def valid_frame(self):
        return {
            "version": 1,
            "goal": "梳理项目发布风险",
            "deliverables": [{"id": "d1", "description": "风险清单", "required": True}],
            "constraints": [{"id": "c1", "description": "仅使用已授权资料", "source": "policy"}],
            "evidence_requirements": [{"id": "e1", "description": "项目资料", "preferred_sources": ["knowledge"]}],
            "proposed_actions": [{"type": "retrieve", "reason": "需要核对资料"}, {"type": "draft", "reason": "整理结论"}],
            "acceptance_criteria": [{"id": "a1", "description": "覆盖主要风险并说明边界"}],
            "ambiguities": [],
            "confidence": "medium",
        }

    def test_validates_and_deduplicates_safe_fields(self):
        frame = self.valid_frame()
        frame["ambiguities"] = ["范围待确认", "范围待确认"]
        validated = validate_task_frame(frame)
        self.assertEqual(validated["ambiguities"], ["范围待确认"])
        self.assertEqual(task_frame_summary(validated)["action_types"], ["retrieve", "draft"])

    def test_rejects_unknown_action_and_source(self):
        frame = self.valid_frame()
        frame["proposed_actions"][0]["type"] = "grant_permission"
        with self.assertRaises(TaskFrameValidationError):
            validate_task_frame(frame)
        frame = self.valid_frame()
        frame["evidence_requirements"][0]["preferred_sources"] = ["secret"]
        with self.assertRaises(TaskFrameValidationError):
            validate_task_frame(frame)

    def test_parser_rejects_prose_wrapped_json(self):
        with self.assertRaises(TaskFrameValidationError):
            parse_task_frame("结果如下：" + json.dumps(self.valid_frame(), ensure_ascii=False))

    def test_fallback_respects_intent_without_granting_tools(self):
        frame = fallback_task_frame("根据资料分析风险", intent_plan={"knowledge_needed": True}, execution_modes={"knowledge": "auto"}, task_confidence="medium")
        self.assertEqual(frame["evidence_requirements"][0]["preferred_sources"], ["knowledge"])
        self.assertNotIn("grant_permission", [item["type"] for item in frame["proposed_actions"]])

    def test_planner_is_off_unless_both_feature_flags_are_enabled(self):
        with patch.object(app, "AGENT_INTELLIGENCE_V2", False), patch.object(app, "AGENT_PLANNER_MODE", "shadow"):
            result = app.plan_task_frame("请分析发布风险", {"task_tier": "deep", "confidence": "high", "model": "deepseek-v4-flash", "max_output_tokens": 100}, {"knowledge_needed": False}, {"knowledge": "auto"}, {})
        self.assertIsNone(result)

    def test_shadow_planner_parses_model_frame_without_changing_permissions(self):
        frame = self.valid_frame()
        profile = {"task_tier": "deep", "confidence": "high", "model": "deepseek-v4-flash", "max_output_tokens": 100}
        with patch.object(app, "AGENT_INTELLIGENCE_V2", True), patch.object(app, "AGENT_PLANNER_MODE", "shadow"), \
             patch.object(app, "model_is_configured", return_value=True), \
             patch.object(app, "deepseek_chat", return_value={"content": json.dumps(frame, ensure_ascii=False)}):
            result = app.plan_task_frame("请分析发布风险", profile, {"knowledge_needed": False}, {"knowledge": "auto", "web": "auto", "file": "auto"}, {})
        self.assertEqual(result["mode"], "shadow")
        self.assertEqual(result["status"], "model")
        self.assertNotIn("allowed_tool_ids", result["frame"])
