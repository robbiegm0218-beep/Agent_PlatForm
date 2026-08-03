import sqlite3
import unittest

from server.knowledge_service import KnowledgeService
from server.schema_migrations import apply_migrations


class _SharedConnection:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, _exc, _traceback):
        self.conn.rollback() if exc_type else self.conn.commit()
        return False


class KnowledgeReprocessingTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE users (id TEXT PRIMARY KEY);
            CREATE TABLE artifacts (id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at INTEGER NOT NULL);
            CREATE TABLE knowledge_documents (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, filename TEXT NOT NULL DEFAULT '',
                storage_path TEXT NOT NULL DEFAULT '', mime_type TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '', size_bytes INTEGER NOT NULL DEFAULT 0,
                chunk_count INTEGER NOT NULL DEFAULT 0, scope TEXT NOT NULL DEFAULT 'general',
                project_space_id TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL
            );
            CREATE TABLE thread_folders (id TEXT PRIMARY KEY, user_id TEXT NOT NULL);
            CREATE TABLE space_members (
                space_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member',
                created_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (space_id, user_id)
            );
        """)
        apply_migrations(self.conn, lambda: 10)
        self.service = KnowledgeService(lambda: _SharedConnection(self.conn))
        self.conn.execute(
            """INSERT INTO knowledge_documents
               (id, user_id, filename, mime_type, content_hash, size_bytes, chunk_count,
                scope, project_space_id, created_at, processing_status, updated_at,
                document_ir_version, parser_version, parsed_block_count,
                normalized_text_sha256, active_chunk_version, chunk_policy_version, chunk_preset)
               VALUES ('doc-1', 'owner', 'guide.md', 'text/markdown', 'raw', 20, 1,
                       'general', '', 10, 'ready', 10, 1, 'parser-v1', 1,
                       'old-normalized', 1, 'policy-v1', 'standard')"""
        )
        self.conn.execute(
            """INSERT INTO knowledge_chunks
               (id, document_id, position, content, chunk_version, active,
                block_ids_json, section_path_json, source_location_json, token_count,
                overlap_tokens, policy_version, preset, content_sha256, created_at)
               VALUES ('old', 'doc-1', 0, 'old content', 1, 1, '["old-block"]', '[]', '{}',
                       2, 0, 'policy-v1', 'standard', 'old-hash', 10)"""
        )
        self.conn.execute(
            """INSERT INTO knowledge_chunk_versions
               (id, document_id, version, policy_version, preset, status, chunk_count,
                created_by_user_id, supersedes_version, created_at, activated_at)
               VALUES ('version-1', 'doc-1', 1, 'policy-v1', 'standard', 'active', 1,
                       'owner', 0, 10, 10)"""
        )
        self.conn.execute(
            """INSERT INTO knowledge_document_blocks
               (id, document_id, ingestion_run_id, ordinal, block_type, text,
                section_path_json, source_location_json, metadata_json, char_count,
                content_sha256, parser_version, created_at)
               VALUES ('old-block', 'doc-1', 'old-run', 0, 'paragraph', 'old content',
                       '[]', '{}', '{}', 11, 'old-hash', 'parser-v1', 10)"""
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    @staticmethod
    def chunk():
        return {
            "id": "new", "document_id": "doc-1", "position": 0, "content": "new content",
            "chunk_version": 1, "active": False, "block_ids_json": '["new-block"]',
            "section_path_json": "[]", "source_location_json": "{}", "token_count": 2,
            "overlap_tokens": 0, "policy_version": "policy-v2", "preset": "long_document",
            "content_sha256": "new-hash", "created_at": 20,
        }

    @staticmethod
    def block():
        return {
            "block_id": "new-block", "document_id": "doc-1", "ingestion_run_id": "new-run",
            "ordinal": 0, "block_type": "paragraph", "text": "new content",
            "section_path_json": "[]", "source_location_json": "{}", "metadata_json": "{}",
            "char_count": 11, "content_sha256": "new-hash", "parser_version": "parser-v2",
            "created_at": 20,
        }

    def test_complete_reparse_switches_structure_and_version_atomically(self):
        version = self.service.activate_reprocessed_document(
            "doc-1", "owner", [self.chunk()], [self.block()], ingestion_run_id="new-run",
            document_ir_version=1, parser_version="parser-v2", normalized_sha256="new-normalized",
            created_at=20,
        )
        self.assertEqual(version, 2)
        document = self.conn.execute("SELECT * FROM knowledge_documents WHERE id = 'doc-1'").fetchone()
        self.assertEqual((document["active_chunk_version"], document["chunk_preset"], document["parser_version"]), (2, "long_document", "parser-v2"))
        self.assertEqual(self.conn.execute("SELECT content FROM knowledge_chunks WHERE active = 1").fetchone()[0], "new content")
        self.assertEqual(self.conn.execute("SELECT text FROM knowledge_document_blocks").fetchone()[0], "new content")
        self.assertEqual(self.conn.execute("SELECT status FROM knowledge_chunk_versions WHERE version = 1").fetchone()[0], "archived")

    def test_invalid_candidate_preserves_old_active_version(self):
        with self.assertRaisesRegex(ValueError, "未生成"):
            self.service.activate_reprocessed_document(
                "doc-1", "owner", [], [self.block()], ingestion_run_id="new-run",
                document_ir_version=1, parser_version="parser-v2", normalized_sha256="new",
                created_at=20,
            )
        self.assertEqual(self.conn.execute("SELECT active_chunk_version FROM knowledge_documents").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT content FROM knowledge_chunks WHERE active = 1").fetchone()[0], "old content")
        self.assertEqual(self.conn.execute("SELECT text FROM knowledge_document_blocks").fetchone()[0], "old content")

    def test_historical_reference_resolves_primary_chunk_not_active_neighbor_context(self):
        self.conn.execute("UPDATE knowledge_chunks SET active = 0 WHERE id = 'old'")
        self.conn.execute(
            """INSERT INTO knowledge_chunks
               (id, document_id, position, content, chunk_version, active,
                block_ids_json, section_path_json, source_location_json, token_count,
                overlap_tokens, policy_version, preset, content_sha256, created_at)
               VALUES ('new-active', 'doc-1', 0, 'new content', 2, 1, '[]', '[]', '{}',
                       2, 0, 'policy-v2', 'standard', 'new-hash', 20)"""
        )
        self.conn.commit()

        historical = self.service.resolve_visible_reference_chunk(
            "doc-1", "owner", 0, "old content\n\nneighbor context"
        )
        current = self.service.resolve_visible_reference_chunk(
            "doc-1", "owner", 0, "", chunk_version=2
        )

        self.assertEqual((historical["chunk_version"], historical["content"]), (1, "old content"))
        self.assertEqual((current["chunk_version"], current["content"]), (2, "new content"))

    def test_project_member_cannot_manage_owner_document(self):
        self.conn.execute("UPDATE knowledge_documents SET scope = 'project', project_space_id = 'space-1' WHERE id = 'doc-1'")
        self.conn.execute("INSERT INTO thread_folders VALUES ('space-1', 'owner')")
        self.assertIsNone(self.service.get_manageable("doc-1", "member"))


if __name__ == "__main__":
    unittest.main()
