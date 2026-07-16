import unittest

from server.task_router import TaskRouter, classify_knowledge_intent


class Decision:
    def __init__(self, tools=None, confidence="none", reason="未识别工具意图"):
        self.tools = tools or []
        self.confidence = confidence
        self.reason = reason


class TaskRouterTests(unittest.TestCase):
    def setUp(self):
        catalog = {
            "fast": {"supports_tools": True, "max_output_tokens": {"quick": 10, "standard": 20, "deep": 30}},
            "deep": {"supports_tools": True, "max_output_tokens": {"quick": 20, "standard": 30, "deep": 40}},
            "external": {"supports_tools": False, "max_output_tokens": {"quick": 10, "standard": 20, "deep": 30}},
        }

        def tool_decision(content):
            if "联网" in content:
                return Decision([{"id": "web_search"}], "high", "明确联网请求")
            return Decision()

        self.router = TaskRouter(catalog, "fast", "deep", tool_decision)

    def test_returns_explainable_structured_route(self):
        route = self.router.route("请制定产品竞品调研方案")
        profile = route.as_profile()
        self.assertEqual(profile["task_tier"], "deep")
        self.assertEqual(profile["model"], "deep")
        self.assertEqual(profile["confidence"], "high")
        self.assertTrue(profile["reasons"])
        self.assertEqual(profile["task_mode_source"], "automatic")

    def test_user_override_is_explicit_and_controls_quality_check(self):
        profile = self.router.route("请制定完整方案", requested_task_mode="quick").as_profile()
        self.assertEqual(profile["task_tier"], "quick")
        self.assertFalse(profile["quality_check"])
        self.assertEqual(profile["route"], "manual_task_mode")
        self.assertEqual(profile["task_mode_source"], "user_override")

    def test_tool_policy_is_authoritative_and_forces_compatible_model(self):
        profile = self.router.route("请联网查询", requested_model="external").as_profile()
        self.assertTrue(profile["needs_tools"])
        self.assertEqual(profile["model"], "fast")
        self.assertEqual(profile["route"], "fallback")

    def test_local_knowledge_intent_is_separate_from_tools(self):
        profile = self.router.route("请基于本地资料总结结论").as_profile()
        self.assertTrue(profile["needs_knowledge"])
        self.assertFalse(profile["needs_tools"])
        self.assertEqual(profile["knowledge_intent"]["reason"], "explicit_local_source")

    def test_invalid_task_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            self.router.route("你好", requested_task_mode="ultra")

    def test_knowledge_classifier_keeps_operational_question_offline(self):
        self.assertFalse(classify_knowledge_intent("这个平台有哪些模型")['needed'])


if __name__ == "__main__":
    unittest.main()
