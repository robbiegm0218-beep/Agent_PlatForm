import unittest
from unittest.mock import patch

from server.intent_planner import IntentPlanner
from server import app


class IntentPlannerTests(unittest.TestCase):
    def setUp(self):
        self.planner = IntentPlanner()

    def test_implicit_space_evidence_requests_knowledge(self):
        plan = self.planner.plan("总结当前空间里已有资料的风险", {"needs_knowledge": False})
        self.assertTrue(plan.knowledge_needed)
        self.assertEqual(plan.confidence, "medium")

    def test_explicit_route_remains_high_confidence(self):
        plan = self.planner.plan("根据知识库回答", {"needs_knowledge": True})
        self.assertTrue(plan.knowledge_needed)
        self.assertEqual(plan.confidence, "high")

    def test_general_question_does_not_force_knowledge(self):
        plan = self.planner.plan("解释什么是向量检索", {"needs_knowledge": False})
        self.assertFalse(plan.knowledge_needed)

    def test_synonymous_local_evidence_request_is_detected(self):
        plan = self.planner.plan("把项目里已有的材料归纳一下", {"needs_knowledge": False})
        self.assertTrue(plan.knowledge_needed)

    def test_empty_knowledge_base_keeps_insufficient_trace(self):
        with patch.object(app, "search_knowledge", return_value=[]):
            results, trace = app.retrieve_knowledge_with_fallback("user", "根据公司制度回答报销流程", {"knowledge_needed": True})
        self.assertEqual(results, [])
        self.assertFalse(trace["sufficient"])

    def test_no_knowledge_intent_never_retries(self):
        with patch.object(app, "search_knowledge", return_value=[]) as search:
            _, trace = app.retrieve_knowledge_with_fallback("user", "解释向量检索", {"knowledge_needed": False})
        self.assertEqual(search.call_count, 1)
        self.assertFalse(trace["retry_query"])

    def test_insufficient_first_retrieval_retries_once_with_terms(self):
        responses = [[], [{"document_id": "doc", "position": 0, "matched_terms": ["公司", "制度"], "score": 3.0}]]
        with patch.object(app, "search_knowledge", side_effect=responses) as search:
            results, trace = app.retrieve_knowledge_with_fallback("user", "总结公司制度的关键流程", {"knowledge_needed": True})
        self.assertEqual(len(results), 1)
        self.assertTrue(trace["retry_query"])
        self.assertEqual(search.call_count, 2)
