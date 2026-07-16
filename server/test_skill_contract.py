import unittest

from server import app
from server.skill_contract import loadable_resource_paths, normalize_skill_contract, restrict_tools, skill_matches


class SkillContractTests(unittest.TestCase):
    def test_legacy_skill_gets_safe_contract_defaults(self):
        skill = normalize_skill_contract({"id": "legacy"})
        self.assertEqual(skill["input_schema"], {"type": "object"})
        self.assertEqual(skill["acceptance_rules"], [])
        self.assertTrue(skill_matches(skill, "任意任务"))

    def test_trigger_limits_resource_loading_and_scripts_never_load(self):
        skill = normalize_skill_contract({
            "triggers": {"terms": ["调研"], "patterns": []},
            "resources": ["references/method.md", "assets/template.txt", "scripts/run.py"],
        })
        self.assertEqual(loadable_resource_paths(skill, "请写文章"), [])
        self.assertEqual(
            loadable_resource_paths(skill, "请调研市场"),
            ["references/method.md", "assets/template.txt"],
        )

    def test_tool_skill_can_only_reduce_policy_permissions(self):
        skills = [{"kind": "tool_skill", "scope_policy_tools": True, "tool_ids": ["web_search", "unregistered_write"]}]
        self.assertEqual(restrict_tools(skills, {"web_search", "read_web_page"}), {"web_search"})
        self.assertEqual(restrict_tools([{"kind": "prompt_skill", "tool_ids": []}], {"web_search"}), {"web_search"})
        self.assertEqual(
            restrict_tools([{"kind": "tool_skill", "tool_ids": ["artifact_tool"]}], {"web_search"}),
            {"web_search"},
        )

    def test_invalid_schema_regex_and_resource_path_are_rejected(self):
        for skill in (
            {"input_schema": {"type": "string"}},
            {"triggers": {"terms": [], "patterns": ["["]}},
            {"resources": ["../secret.txt"]},
        ):
            with self.assertRaises(ValueError):
                normalize_skill_contract(skill)

    def test_research_brief_contract_and_builtin_resource_are_task_scoped(self):
        skill = next(item for item in app.SKILLS if item["id"] == "research_brief")
        self.assertTrue(skill_matches(skill, "请调研 Agent 平台并形成研究简报"))
        self.assertFalse(skill_matches(skill, "帮我润色这段文字"))
        self.assertEqual(app.load_skill_resources(skill, "帮我润色这段文字"), [])
        resources = app.load_skill_resources(skill, "请调研 Agent 平台")
        self.assertEqual(resources[0]["path"], "references/method.md")
        self.assertIn("已验证事实", resources[0]["content"])

        content = "请调研并读取 https://example.com 后总结这个网页"
        context = app.build_execution_context(
            "user_test", app.infer_task_profile(content), [skill], [skill["id"]], content, [],
        )
        self.assertEqual(context["allowed_tool_ids"], ["read_web_page"])
        self.assertEqual(context["skill_resources"][0]["path"], "references/method.md")
        prompt = app.build_system_prompt(context)
        self.assertIn("按任务加载的技能资源", prompt)
        self.assertIn("输出至少覆盖", prompt)


if __name__ == "__main__":
    unittest.main()
