import unittest
from unittest.mock import patch
from server.agent_orchestrator import AgentOrchestrator, OrchestrationError, OrchestratorState, validate_next_action
from server import app

class AgentOrchestratorTests(unittest.TestCase):
    def test_valid_evidence_and_verify_path_reaches_complete(self):
        flow = AgentOrchestrator("standard")
        for target in (OrchestratorState.COLLECT_EVIDENCE, OrchestratorState.ASSESS_EVIDENCE, OrchestratorState.DRAFT, OrchestratorState.VERIFY, OrchestratorState.COMPLETE):
            flow.transition(target, reason="test")
        self.assertEqual(flow.snapshot.state, OrchestratorState.COMPLETE)

    def test_rejects_invalid_transition_and_tool_budget(self):
        flow = AgentOrchestrator("quick")
        with self.assertRaises(OrchestrationError): flow.transition(OrchestratorState.VERIFY, reason="invalid")
        flow.transition(OrchestratorState.COLLECT_EVIDENCE, reason="test")
        flow.transition(OrchestratorState.ASSESS_EVIDENCE, reason="test")
        flow.transition(OrchestratorState.ACT, reason="test"); flow.record_tool_call()
        flow.transition(OrchestratorState.OBSERVE, reason="test")
        flow.transition(OrchestratorState.ASSESS_EVIDENCE, reason="test")
        flow.transition(OrchestratorState.ACT, reason="again")
        with self.assertRaises(OrchestrationError): flow.record_tool_call()

    def test_model_budget_is_bounded(self):
        flow = AgentOrchestrator("quick")
        flow.record_model_call()
        with self.assertRaises(OrchestrationError): flow.record_model_call()

    def test_active_wrapper_records_read_only_tool_lifecycle(self):
        events = []
        def fake_loop(_thread, _prompt, _context, emit):
            emit("tool_call", {"tool_id": "web_search"}); emit("tool_result", {"tool_id": "web_search"})
            yield "完成"
        with patch.object(app, "run_deepseek_agent", fake_loop):
            output = "".join(app.run_orchestrated_agent("t", "s", {"task_tier":"standard", "allowed_tool_ids":["web_search"], "intent_plan":{"knowledge_needed":False}}, lambda kind, payload: events.append((kind, payload))))
        self.assertEqual(output, "完成")
        self.assertEqual([item[1]["to"] for item in events if item[0] == "orchestrator_transition"], ["COLLECT_EVIDENCE", "ASSESS_EVIDENCE", "ACT", "OBSERVE", "DRAFT", "VERIFY", "COMPLETE"])

    def test_tool_error_uses_one_replan_before_drafting(self):
        events = []
        def fake_loop(_thread, _prompt, _context, emit):
            emit("tool_call", {"tool_id": "web_search"}); emit("tool_error", {"tool_id": "web_search"})
            yield "完成"
        with patch.object(app, "run_deepseek_agent", fake_loop):
            list(app.run_orchestrated_agent("t", "s", {"task_tier":"standard", "allowed_tool_ids":["web_search"], "intent_plan":{"knowledge_needed":False}}, lambda kind, payload: events.append((kind, payload))))
        self.assertIn("REPLAN", [item[1]["to"] for item in events if item[0] == "orchestrator_transition"])

    def test_next_action_cannot_grant_a_tool(self):
        self.assertEqual(validate_next_action({"type":"use_tool","tool_id":"web","arguments":{},"reason":"需要查询"}, {"web"})["tool_id"], "web")
        with self.assertRaises(OrchestrationError): validate_next_action({"type":"use_tool","tool_id":"write","arguments":{}}, {"web"})

    def test_suggested_action_is_permission_checked(self):
        context = {"model":"deepseek-v4-flash", "allowed_tool_ids":["web"], "evidence_ledger":{}, "task_tier":"standard"}
        with patch.object(app, "model_is_configured", return_value=True), patch.object(app, "deepseek_chat", return_value={"content":"{\"type\":\"use_tool\",\"tool_id\":\"write\",\"arguments\":{}}"}):
            result = app.suggest_next_action(context)
        self.assertEqual(result["source"], "fallback")

    def test_model_requested_clarification_reaches_a_terminal_state(self):
        events = []
        context = {"task_tier": "standard", "allowed_tool_ids": [], "intent_plan": {"knowledge_needed": False}, "model": "deepseek-v4-flash"}
        with patch.object(app, "suggest_next_action", return_value={"type": "clarify_user", "reason": "目标范围不明确", "source": "model"}):
            output = "".join(app.run_orchestrated_agent("t", "s", context, lambda kind, payload: events.append((kind, payload))))
        self.assertIn("目标范围不明确", output)
        self.assertEqual([payload["to"] for kind, payload in events if kind == "orchestrator_transition"], ["CLARIFY"])

    def test_model_requested_limited_completion_is_explicit(self):
        events = []
        context = {"task_tier": "standard", "allowed_tool_ids": [], "intent_plan": {"knowledge_needed": False}, "model": "deepseek-v4-flash"}
        with patch.object(app, "suggest_next_action", return_value={"type": "complete_with_limits", "reason": "缺少当前数据", "source": "model"}):
            output = "".join(app.run_orchestrated_agent("t", "s", context, lambda kind, payload: events.append((kind, payload))))
        self.assertIn("缺少当前数据", output)
        self.assertEqual([payload["to"] for kind, payload in events if kind == "orchestrator_transition"], ["COLLECT_EVIDENCE", "ASSESS_EVIDENCE", "COMPLETE_WITH_LIMITS"])
