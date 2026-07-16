import unittest

from server.structured_context import StructuredContextBuilder


def message(identifier, content, created_at, role="user"):
    return {"id": identifier, "role": role, "content": content, "created_at": created_at}


class StructuredContextBuilderTests(unittest.TestCase):
    def setUp(self):
        self.builder = StructuredContextBuilder()

    def test_extracts_source_linked_fields(self):
        context = self.builder.build([
            message("m1", "为产品发布制定计划。项目名：星河", 1),
            message("m2", "必须使用中文，格式为表格。下一步需要完成风险清单。", 2),
            message("m3", "最终采用两阶段发布。待确认预算上限。", 3),
        ])
        self.assertEqual(context["goals"][0]["source_message_id"], "m1")
        self.assertTrue(any("中文" in item["text"] for item in context["constraints"]))
        self.assertTrue(any("两阶段" in item["text"] for item in context["decisions"]))
        self.assertTrue(any("星河" in item["text"] for item in context["entities"]))
        self.assertTrue(any("预算" in item["text"] for item in context["open_questions"]))
        self.assertTrue(any("风险清单" in item["text"] for item in context["todos"]))

    def test_goal_correction_replaces_active_goal(self):
        context = self.builder.build([
            message("m1", "先写一份市场报告", 1),
            message("m2", "目标改为制定产品发布计划", 2),
        ])
        active = [item for item in context["goals"] if item["status"] == "active"]
        self.assertEqual([item["text"] for item in active], ["制定产品发布计划"])
        self.assertEqual(active[0]["source_message_id"], "m2")

    def test_inherited_context_survives_new_thread_and_can_be_corrected(self):
        inherited = self.builder.build([
            message("old1", "制定迁移方案", 1),
            message("old2", "必须在周五完成。", 2),
        ])
        continued = self.builder.build([message("new1", "不再要求周五完成，最终采用分批迁移。", 3)], inherited)
        active_constraints = [item["text"] for item in continued["constraints"] if item["status"] == "active"]
        self.assertFalse(any("周五" in text for text in active_constraints))
        self.assertTrue(any("分批迁移" in item["text"] for item in continued["decisions"]))

    def test_selection_is_bounded_and_deterministic(self):
        context = self.builder.build([
            message(f"m{i}", f"必须记录约束编号{i}。", i) for i in range(12)
        ])
        first = self.builder.select(context, "约束", max_chars=80)
        second = self.builder.select(context, "约束", max_chars=80)
        self.assertEqual(first, second)
        self.assertLessEqual(first["injected_chars"], 80)


if __name__ == "__main__":
    unittest.main()
