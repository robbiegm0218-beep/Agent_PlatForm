import unittest

from server.memory_policy import extract_candidates, select_memories, validate_memory_content


class MemoryPolicyTests(unittest.TestCase):
    def test_candidates_require_explicit_language_and_confirmation(self):
        candidates = extract_candidates("我的偏好是使用中文。项目事实：代号为星河。", "m1")
        self.assertEqual([item["kind"] for item in candidates], ["preference", "project_fact"])
        self.assertTrue(all(item["requires_confirmation"] for item in candidates))
        self.assertEqual(extract_candidates("今天使用中文回答"), [])

    def test_sensitive_values_are_rejected(self):
        for content in ("password=abc123", "API_KEY: secret-value", "密码：123456"):
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, "拒绝"):
                validate_memory_content(content)

    def test_selection_respects_scope_status_relevance_and_budget(self):
        rows = [
            {"id": "a", "kind": "preference", "content": "使用中文回答", "scope_type": "global", "scope_id": "", "status": "active", "updated_at": 3},
            {"id": "b", "kind": "project_fact", "content": "星河项目使用SQLite", "scope_type": "project", "scope_id": "p1", "status": "active", "updated_at": 2},
            {"id": "c", "kind": "decision", "content": "星河项目使用Postgres", "scope_type": "project", "scope_id": "p2", "status": "active", "updated_at": 4},
            {"id": "d", "kind": "decision", "content": "星河项目停止开发", "scope_type": "global", "scope_id": "", "status": "disabled", "updated_at": 5},
            {"id": "e", "kind": "decision", "content": "回答时适度使用二次元用语", "scope_type": "project", "scope_id": "p1", "status": "active", "updated_at": 6},
        ]
        selected = select_memories(rows, "星河项目数据库", "p1")
        self.assertEqual([item["id"] for item in selected], ["b", "e", "a"])

    def test_scoped_decision_persists_without_lexical_overlap_and_memory_inquiry_is_auditable(self):
        rows = [
            {"id": "decision", "kind": "decision", "content": "对话中适度使用二次元用语", "scope_type": "project", "scope_id": "p1", "status": "active", "updated_at": 2},
            {"id": "fact", "kind": "project_fact", "content": "项目使用 SQLite", "scope_type": "project", "scope_id": "p1", "status": "active", "updated_at": 1},
        ]
        self.assertEqual(
            [item["id"] for item in select_memories(rows, "吃饭了吗", "p1")], ["decision"],
        )
        self.assertEqual(
            [item["id"] for item in select_memories(rows, "本轮使用长期记忆了吗", "p1")], ["decision", "fact"],
        )


if __name__ == "__main__":
    unittest.main()
