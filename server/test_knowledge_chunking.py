import hashlib
import unittest

from server.knowledge_chunking import (
    CHUNK_PRESETS,
    STRUCTURED_CHUNK_POLICY_VERSION,
    chunk_document_ir,
    estimate_tokens,
    persisted_chunk_rows,
    policy_for_preset,
)
from server.knowledge_pipeline_contracts import DocumentBlock, DocumentIR


def document_ir(blocks):
    return DocumentIR(
        document_id="doc-1",
        source_mime="text/markdown",
        source_sha256=hashlib.sha256(b"fixture").hexdigest(),
        parser_id="fixture",
        parser_version="fixture-v1",
        blocks=tuple(blocks),
    )


def block(ordinal, block_type, text, section=(), source=None):
    return DocumentBlock(
        block_id=f"block-{ordinal}",
        block_type=block_type,
        ordinal=ordinal,
        text=text,
        section_path=tuple(section),
        source_location=source or {},
    )


class KnowledgeChunkingTests(unittest.TestCase):
    def test_presets_are_bounded_and_versioned(self):
        self.assertEqual(set(CHUNK_PRESETS), {"standard", "long_document", "table_dense"})
        for preset, policy in CHUNK_PRESETS.items():
            self.assertEqual(policy.preset, preset)
            self.assertEqual(policy.version, STRUCTURED_CHUNK_POLICY_VERSION)
            self.assertLessEqual(policy.target_tokens, policy.max_tokens)
        with self.assertRaises(ValueError):
            policy_for_preset("unsafe")

    def test_chunks_do_not_cross_unrelated_sections(self):
        blocks = [
            block(0, "heading", "第一章", ("第一章",), {"line_start": 1, "line_end": 1}),
            block(1, "paragraph", "甲" * 300, ("第一章",), {"line_start": 2, "line_end": 2}),
            block(2, "heading", "第二章", ("第二章",), {"line_start": 4, "line_end": 4}),
            block(3, "paragraph", "乙" * 300, ("第二章",), {"line_start": 5, "line_end": 5}),
        ]
        chunks = chunk_document_ir(document_ir(blocks))
        self.assertEqual([chunk.section_path for chunk in chunks], [("第一章",), ("第二章",)])
        self.assertNotIn("第二章", chunks[0].content)
        self.assertNotIn("第一章", chunks[1].content)
        self.assertEqual(chunks[0].source_location["line_range"], [1, 2])

    def test_large_table_splits_only_at_row_boundaries(self):
        rows = [f"| row-{index} | {'数据' * 80} |" for index in range(12)]
        table = block(0, "table", "\n".join(rows), ("数据表",), {"table": 1})
        chunks = chunk_document_ir(document_ir([table]), "table_dense")
        self.assertGreater(len(chunks), 1)
        reconstructed_rows = [
            line
            for chunk in chunks
            for line in chunk.content.splitlines()
            if line.startswith("| row-")
        ]
        self.assertEqual(reconstructed_rows, rows)
        self.assertTrue(all(chunk.token_count <= CHUNK_PRESETS["table_dense"].max_tokens for chunk in chunks))
        self.assertTrue(all(chunk.source_location["tables"] == [1] for chunk in chunks))

    def test_deterministic_metadata_and_hashes(self):
        ir = document_ir([
            block(0, "heading", "说明", ("说明",)),
            block(1, "paragraph", "稳定内容。" * 120, ("说明",), {"page": 2}),
        ])
        first = chunk_document_ir(ir)
        second = chunk_document_ir(ir)
        self.assertEqual(first, second)
        rows = persisted_chunk_rows("doc-1", first, chunk_version=2, active=False, created_at=100)
        self.assertTrue(all(row["policy_version"] == STRUCTURED_CHUNK_POLICY_VERSION for row in rows))
        self.assertTrue(all(row["chunk_version"] == 2 and row["active"] == 0 for row in rows))
        self.assertEqual(len({row["id"] for row in rows}), len(rows))
        self.assertEqual(rows[0]["content_sha256"], hashlib.sha256(first[0].content.encode()).hexdigest())

    def test_token_estimate_supports_chinese_and_latin(self):
        self.assertEqual(estimate_tokens("中文"), 2)
        self.assertEqual(estimate_tokens("abcdefgh"), 2)
        self.assertGreater(estimate_tokens("中文 Agent 1234。"), 4)


if __name__ == "__main__":
    unittest.main()
