import unittest

from server.knowledge_hybrid import bounded_query_rewrite, reciprocal_rank_fusion
from server.knowledge_retrieval import KnowledgeRetriever


class KnowledgeHybridTests(unittest.TestCase):
    def test_rrf_promotes_candidates_present_in_both_routes(self):
        lexical = [
            {"id": "l1", "document_id": "lexical", "position": 0, "content": "a"},
            {"id": "shared", "document_id": "shared", "position": 0, "content": "b"},
        ]
        vector = [
            {"id": "shared", "document_id": "shared", "position": 0, "content": "b", "vector_score": 0.82},
            {"id": "v1", "document_id": "vector", "position": 0, "content": "c", "vector_score": 0.91},
        ]
        fused = reciprocal_rank_fusion(lexical, vector)
        self.assertEqual(fused[0]["document_id"], "shared")
        self.assertEqual(fused[0]["lexical_rank"], 2)
        self.assertEqual(fused[0]["vector_rank"], 1)

    def test_rewrite_preserves_product_id_and_filename_anchor(self):
        rewritten = bounded_query_rewrite("请根据知识库说明 Atlas-42 在 roadmap.md 中的上线要求")
        self.assertIn("atlas-42", rewritten)
        self.assertIn("roadmap.md", rewritten)
        self.assertNotIn("请根据", rewritten)

    def test_semantic_candidate_uses_neighbors_and_rejects_low_score(self):
        rows = [
            {
                "id": "primary", "document_id": "doc", "filename": "guide.md",
                "position": 1, "content": "批准条件是负责人完成风险签字。",
                "vector_score": 0.9, "semantic_candidate": True,
                "hybrid_rrf_score": 1 / 61,
            },
            {
                "id": "neighbor", "document_id": "doc", "filename": "guide.md",
                "position": 2, "content": "签字后进入发布窗口。",
            },
            {
                "id": "low", "document_id": "low", "filename": "other.md",
                "position": 0, "content": "完全无关正文。",
                "vector_score": 0.4, "semantic_candidate": True,
            },
        ]
        results = KnowledgeRetriever().search("部署审批规则", rows)
        self.assertEqual(results[0]["document_id"], "doc")
        self.assertEqual(results[0]["neighbor_positions"], [2])
        self.assertTrue(results[0]["match_signals"]["semantic_candidate"])
        self.assertNotIn("low", [item["document_id"] for item in results])

    def test_near_duplicate_chunks_are_suppressed(self):
        repeated = "产品发布前必须完成安全审查和负责人签字。" * 8
        rows = [
            {"id": "a", "document_id": "a", "filename": "a.md", "position": 0, "content": repeated},
            {"id": "b", "document_id": "b", "filename": "b.md", "position": 0, "content": repeated + "补充"},
        ]
        results = KnowledgeRetriever().search("安全审查负责人签字", rows)
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
