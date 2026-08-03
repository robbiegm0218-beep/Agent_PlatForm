import unittest

from server.knowledge_retrieval import (
    KnowledgeRetriever,
    RetrievalConfig,
    assess_candidate_relevance,
    retrieval_policy_snapshot,
)
from server.retrieval_governance import suggestions_for_feedback


def row(identifier, document, filename, position, content):
    return {"id": identifier, "document_id": document, "filename": filename, "position": position, "content": content}


class KnowledgeRetrieverTests(unittest.TestCase):
    def test_phrase_and_title_signals_produce_stable_ranking(self):
        rows = [
            row("a", "d1", "碳足迹核算指南.md", 0, "本章介绍组织边界。"),
            row("b", "d2", "普通材料.md", 0, "产品碳足迹核算需要明确功能单位和系统边界。"),
            row("c", "d3", "噪声.md", 0, "今天讨论产品设计和团队协作。"),
        ]
        retriever = KnowledgeRetriever(RetrievalConfig(neighbor_radius=0))
        first = retriever.search("产品碳足迹核算", rows)
        second = retriever.search("产品碳足迹核算", rows)
        self.assertEqual([item["document_id"] for item in first], ["d2", "d1"])
        self.assertEqual(first, second)
        self.assertGreater(first[0]["score_breakdown"]["phrase"], 0)

    def test_adjacent_chunks_are_expanded_within_same_document(self):
        rows = [
            row("a", "d1", "指南.md", 0, "系统边界定义。"),
            row("b", "d1", "指南.md", 1, "碳排放因子选择需要匹配地区和年份。"),
            row("c", "d1", "指南.md", 2, "数据质量应记录来源。"),
            row("d", "d2", "其他.md", 0, "无关内容。"),
        ]
        result = KnowledgeRetriever().search("碳排放因子选择", rows)[0]
        self.assertEqual(result["position"], 1)
        self.assertEqual(result["neighbor_positions"], [0, 2])
        self.assertIn("数据质量", result["excerpt"])
        self.assertEqual(result["primary_excerpt"], "碳排放因子选择需要匹配地区和年份。")
        self.assertNotIn("数据质量", result["primary_excerpt"])

    def test_duplicate_content_and_total_budget_are_bounded(self):
        rows = [
            row("a", "d1", "甲.md", 0, "供应链排放数据" * 30),
            row("b", "d2", "乙.md", 0, "供应链排放数据" * 30),
            row("c", "d3", "丙.md", 0, "供应链排放核算" * 30),
        ]
        retriever = KnowledgeRetriever(RetrievalConfig(max_excerpt_chars=120, max_total_chars=180, neighbor_radius=0))
        results = retriever.search("供应链排放", rows)
        self.assertEqual(len(results), 2)
        self.assertLessEqual(sum(len(item["excerpt"]) for item in results), 180)

    def test_unrelated_query_returns_no_results(self):
        rows = [row("a", "d1", "材料.md", 0, "产品碳足迹与功能单位。")]
        self.assertEqual(KnowledgeRetriever().search("员工考勤制度", rows), [])

    def test_v2_returns_explainable_match_and_ranking_signals(self):
        rows = [
            row("a", "d1", "Acme新人培训手册.md", 0, "Acme 新人培训包含账号准备和结业复盘两个阶段。"),
            row("b", "d2", "通用培训.md", 0, "新人培训需要安排导师。"),
        ]
        results = KnowledgeRetriever().search(
            "Acme 新人培训包含哪些阶段",
            rows,
            gate_v2=True,
        )
        self.assertTrue(results)
        self.assertIn("match_signals", results[0])
        self.assertIn("ranking_signals", results[0])
        assessment = assess_candidate_relevance(
            "Acme 新人培训包含哪些阶段",
            results,
            gate_v2=True,
        )
        self.assertTrue(assessment["sufficient"])
        self.assertTrue(assessment["strong_anchor"])
        self.assertTrue(assessment["rank_confident"])
        self.assertEqual(assessment["unmatched_named_anchor_count"], 0)

    def test_v2_rejects_candidate_when_named_anchor_is_missing(self):
        rows = [
            row("a", "d1", "客户培训资料.md", 0, "客户培训包含产品介绍和结业复盘两个阶段。"),
        ]
        results = KnowledgeRetriever().search(
            "Beta 客户培训方案包含哪些阶段",
            rows,
            gate_v2=True,
        )
        self.assertTrue(results)
        assessment = assess_candidate_relevance(
            "Beta 客户培训方案包含哪些阶段",
            results,
            gate_v2=True,
        )
        self.assertTrue(assessment["sufficient"])
        self.assertFalse(assessment["strong_anchor"])
        self.assertEqual(assessment["unmatched_named_anchor_count"], 1)

    def test_policy_snapshot_records_active_retrieval_settings(self):
        snapshot = retrieval_policy_snapshot(RetrievalConfig(limit=2, neighbor_radius=0))
        self.assertEqual(snapshot["version"], "lexical-retrieval-v1")
        self.assertEqual(snapshot["config"]["limit"], 2)
        self.assertEqual(snapshot["config"]["neighbor_radius"], 0)

    def test_pilot_feedback_threshold_creates_only_an_offline_hypothesis(self):
        config = RetrievalConfig(limit=4)
        self.assertEqual(suggestions_for_feedback(11, {"wrong_document": 1}, config), [])
        suggestions = suggestions_for_feedback(12, {"wrong_document": 1}, config)
        self.assertEqual(suggestions[0]["changed_variable"], "limit")
        self.assertEqual(suggestions[0]["target_value"], 3)


if __name__ == "__main__":
    unittest.main()
