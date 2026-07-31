import json
import unittest

from server.evaluate_knowledge_fts import evaluate
from server.evaluate_knowledge_retrieval import DEFAULT_FIXTURE, validate_cases
from server.knowledge_fts import (
    FTS_POLICY_VERSION,
    build_fts_query,
    candidate_trace_summary,
    fts_query_tokens,
    query_sha256,
)


class KnowledgeFtsTests(unittest.TestCase):
    def test_chinese_and_english_queries_build_deterministic_trigrams(self):
        self.assertEqual(
            fts_query_tokens("Agent 北极星指标"),
            ["agent", "北极星", "极星指", "星指标"],
        )
        self.assertEqual(
            build_fts_query("Agent 北极星指标"),
            '"agent" OR "北极星" OR "极星指" OR "星指标"',
        )
        self.assertEqual(fts_query_tokens("指标"), [])
        self.assertEqual(FTS_POLICY_VERSION, "fts5-bm25-v1")

    def test_query_trace_hash_does_not_expose_query(self):
        digest = query_sha256("内部机密查询")
        self.assertEqual(len(digest), 64)
        self.assertNotIn("内部", digest)
        self.assertEqual(digest, query_sha256("  内部机密查询  "))

    def test_candidate_summary_contains_metadata_only(self):
        candidates = [{
            "id": "chunk-1",
            "document_id": "doc-1",
            "position": 2,
            "content": "不得出现在追踪中的正文",
            "bm25_score": 1.25,
        }]
        summary = candidate_trace_summary(candidates, [{
            "document_id": "doc-1",
            "position": 2,
        }])
        decoded = json.loads(summary)
        self.assertTrue(decoded[0]["selected"])
        self.assertEqual(decoded[0]["reason"], "selected")
        self.assertNotIn("正文", summary)
        self.assertNotIn("content", decoded[0])

    def test_fixed_retrieval_set_preserves_recall_and_reduces_scaled_scan(self):
        cases = validate_cases(json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8")))
        report = evaluate(cases)
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["recall_at_4"], 1.0)
        self.assertEqual(report["top1_accuracy"], 1.0)
        self.assertEqual(report["no_match_accuracy"], 1.0)
        self.assertGreater(report["full_scan_avoided_cases"], 0)
        self.assertLess(report["scale_benchmark"]["candidate_row_ratio"], 0.01)
        self.assertGreater(report["scale_benchmark"]["p95_speedup"], 2)


if __name__ == "__main__":
    unittest.main()
