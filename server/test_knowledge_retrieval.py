import unittest

from server.knowledge_retrieval import KnowledgeRetriever, RetrievalConfig


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


if __name__ == "__main__":
    unittest.main()
