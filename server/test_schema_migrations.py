import sqlite3
import unittest

from server.schema_migrations import LATEST_SCHEMA_VERSION, Migration, MigrationError, apply_migrations, migration_status


class SchemaMigrationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
        self.conn.execute("""CREATE TABLE artifacts (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )""")
        self.conn.execute("""CREATE TABLE knowledge_documents (
            id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL
        )""")

    def tearDown(self):
        self.conn.close()

    def test_migrations_are_versioned_and_idempotent(self):
        first = apply_migrations(self.conn, lambda: 123)
        second = apply_migrations(self.conn, lambda: 456)
        self.assertEqual(first["current_version"], LATEST_SCHEMA_VERSION)
        self.assertTrue(second["ready"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], LATEST_SCHEMA_VERSION)
        self.assertIn("is_admin", {row[1] for row in self.conn.execute("PRAGMA table_info(users)")})
        self.assertIn("is_knowledge_admin", {row[1] for row in self.conn.execute("PRAGMA table_info(users)")})
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'security_events'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'account_deletion_requests'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'login_throttles'").fetchone())
        artifact_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(artifacts)")}
        self.assertTrue({
            "mime_type", "status", "revision", "size_bytes", "updated_at", "content_sha256",
        }.issubset(artifact_columns))
        knowledge_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(knowledge_documents)")}
        self.assertTrue({
            "processing_status", "active_ingestion_run_id", "updated_at",
            "document_ir_version", "parser_version", "parsed_block_count",
            "normalized_text_sha256", "active_chunk_version",
            "chunk_policy_version", "chunk_preset",
            "active_embedding_model_version", "embedding_status", "embedding_updated_at",
        }.issubset(knowledge_columns))
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_ingestion_runs'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_pipeline_events'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_document_blocks'").fetchone())
        chunk_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(knowledge_chunks)")}
        self.assertTrue({
            "chunk_version", "active", "block_ids_json", "section_path_json",
            "source_location_json", "token_count", "overlap_tokens",
            "policy_version", "preset", "content_sha256", "created_at",
        }.issubset(chunk_columns))
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_chunk_versions'").fetchone())
        fts = self.conn.execute("SELECT sql FROM sqlite_master WHERE name = 'knowledge_chunks_fts'").fetchone()
        self.assertIsNotNone(fts)
        self.assertIn("VIRTUAL TABLE", fts[0].upper())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_search_index_state'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_retrieval_traces'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_embedding_models'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_embedding_jobs'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_chunk_embeddings'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_processing_presets'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'retrieval_lab_experiments'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_migration_batches'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_migration_items'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_migration_shadow_diffs'").fetchone())
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM knowledge_processing_presets WHERE status = 'active'").fetchone()[0],
            3,
        )
        active_policy = self.conn.execute(
            "SELECT version FROM retrieval_policies WHERE status = 'active'"
        ).fetchone()
        self.assertEqual(active_policy, ("hybrid-rrf-v1",))
        index_state = self.conn.execute("SELECT backend, policy_version FROM knowledge_search_index_state WHERE id = 1").fetchone()
        self.assertEqual(index_state, ("fts5_trigram", "fts5-bm25-v1"))

    def test_artifact_contract_backfills_existing_rows(self):
        self.conn.execute(
            "INSERT INTO artifacts (id, kind, created_at) VALUES ('old_markdown', 'markdown', 42)"
        )
        apply_migrations(self.conn, lambda: 123)
        row = self.conn.execute(
            "SELECT mime_type, status, revision, size_bytes, updated_at, content_sha256 "
            "FROM artifacts WHERE id = 'old_markdown'"
        ).fetchone()
        self.assertEqual(row, ("text/markdown; charset=utf-8", "ready", 1, 0, 42, ""))

    def test_fts_migration_backfills_existing_active_chunks(self):
        self.conn.execute("ALTER TABLE knowledge_documents ADD COLUMN filename TEXT NOT NULL DEFAULT ''")
        self.conn.execute("ALTER TABLE knowledge_documents ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
        self.conn.execute("ALTER TABLE knowledge_documents ADD COLUMN scope TEXT NOT NULL DEFAULT 'general'")
        self.conn.execute("ALTER TABLE knowledge_documents ADD COLUMN chunk_count INTEGER NOT NULL DEFAULT 0")
        self.conn.execute(
            "INSERT INTO knowledge_documents (id, filename, user_id, scope, chunk_count, created_at) VALUES ('doc-1', '指标.md', 'user-1', 'general', 1, 42)"
        )
        self.conn.execute("""CREATE TABLE knowledge_chunks (
            id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
            position INTEGER NOT NULL, content TEXT NOT NULL
        )""")
        self.conn.execute(
            "INSERT INTO knowledge_chunks VALUES ('chunk-1', 'doc-1', 0, '北极星指标用于衡量产品价值')"
        )
        apply_migrations(self.conn, lambda: 123)
        matched = self.conn.execute(
            "SELECT chunk_id FROM knowledge_chunks_fts WHERE knowledge_chunks_fts MATCH '北极星'"
        ).fetchall()
        self.assertEqual(matched, [("chunk-1",)])
        state = self.conn.execute(
            "SELECT indexed_chunk_count FROM knowledge_search_index_state WHERE id = 1"
        ).fetchone()
        self.assertEqual(state, (1,))

    def test_failed_migration_rolls_back_its_changes(self):
        def fail(conn):
            conn.execute("CREATE TABLE should_rollback (id TEXT)")
            raise RuntimeError("boom")

        from server import schema_migrations
        original = schema_migrations.MIGRATIONS
        try:
            schema_migrations.MIGRATIONS = (Migration(99, "failure", fail),)
            with self.assertRaises(MigrationError):
                apply_migrations(self.conn, lambda: 123)
        finally:
            schema_migrations.MIGRATIONS = original
        self.assertIsNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'should_rollback'").fetchone())
        self.assertEqual(migration_status(self.conn)["current_version"], 0)
