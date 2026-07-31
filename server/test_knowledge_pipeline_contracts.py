import hashlib
import json
import unittest

from server.evaluate_knowledge_pipeline import BASELINE_REPORT, DEFAULT_FIXTURE, evaluate, validate_fixture
from server.knowledge_pipeline_contracts import (
    ChunkPolicy,
    DocumentBlock,
    DocumentIR,
    IndexPolicy,
    contract_snapshot,
)


class KnowledgePipelineContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = validate_fixture(json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8")))

    def test_document_ir_is_versioned_structured_and_serializable(self):
        block = DocumentBlock(
            block_id="block-1",
            block_type="paragraph",
            ordinal=0,
            text="匿名化测试正文",
            section_path=("第一章",),
            source_location={"page": 2},
        )
        document = DocumentIR(
            document_id="document-1",
            source_mime="application/pdf",
            source_sha256=hashlib.sha256(b"fixture").hexdigest(),
            parser_id="pypdf",
            parser_version="1",
            blocks=(block,),
        )
        serialized = document.as_dict()
        self.assertEqual(serialized["schema_version"], 1)
        self.assertEqual(serialized["blocks"][0]["source_location"], {"page": 2})

    def test_document_ir_rejects_unknown_blocks_and_unstable_order(self):
        with self.assertRaisesRegex(ValueError, "不支持"):
            DocumentBlock("block-1", "unknown", 0, "text")
        blocks = (
            DocumentBlock("block-2", "paragraph", 2, "two"),
            DocumentBlock("block-1", "heading", 1, "one"),
        )
        with self.assertRaisesRegex(ValueError, "递增"):
            DocumentIR(
                "document-1",
                "text/markdown",
                hashlib.sha256(b"fixture").hexdigest(),
                "markdown",
                "1",
                blocks,
            )

    def test_policy_contracts_enforce_hard_bounds(self):
        self.assertEqual(ChunkPolicy().preset, "standard")
        self.assertEqual(IndexPolicy().lexical_backend, "python_lexical_v1")
        with self.assertRaisesRegex(ValueError, "重叠"):
            ChunkPolicy(target_tokens=100, max_tokens=200, overlap_tokens=100)
        with self.assertRaisesRegex(ValueError, "模型"):
            IndexPolicy(
                embedding_enabled=True,
                hybrid_method="rrf",
                vector_weight=0.5,
            )
        weighted = IndexPolicy(
            lexical_backend="sqlite_fts5",
            embedding_enabled=True,
            embedding_model="fixture-embedding-v1",
            vector_dimensions=768,
            hybrid_method="weighted",
            lexical_weight=0.6,
            vector_weight=0.4,
            candidate_limit=20,
            rerank_limit=8,
        )
        self.assertEqual(weighted.vector_dimensions, 768)

    def test_fixture_covers_current_formats_without_local_paths(self):
        self.assertEqual(
            {item["format"] for item in self.fixture["format_capabilities"]},
            {"markdown", "docx", "pdf", "xlsx", "image"},
        )
        self.assertNotIn("/Users/", json.dumps(self.fixture))

    def test_baseline_is_deterministic_and_meets_existing_quality_gate(self):
        first = evaluate(self.fixture)
        second = evaluate(self.fixture)
        self.assertEqual(first, second)
        self.assertEqual(first, json.loads(BASELINE_REPORT.read_text(encoding="utf-8")))
        self.assertEqual(first["failures"], [])
        self.assertTrue(all(item["passed"] for item in first["chunk_baseline"]))
        self.assertEqual(first["retrieval_baseline"]["recall_at_4"], 1.0)
        self.assertEqual(first["retrieval_baseline"]["top1_accuracy"], 1.0)

    def test_contract_snapshot_is_content_free(self):
        snapshot = contract_snapshot()
        self.assertEqual(snapshot["document_ir_schema_version"], 1)
        self.assertNotIn("text", json.dumps(snapshot))


if __name__ == "__main__":
    unittest.main()
