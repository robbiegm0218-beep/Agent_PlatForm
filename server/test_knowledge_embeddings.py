import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.knowledge_embeddings import (
    EmbeddingConfig,
    EmbeddingError,
    KnowledgeEmbeddingService,
    pack_vector,
    unpack_vector,
)
from server.knowledge_service import KnowledgeService
from server.schema_migrations import apply_migrations


class FakeProvider:
    def __init__(self, dimensions=3, fail_on=""):
        self.dimensions = dimensions
        self.fail_on = fail_on
        self.calls = []

    def embed(self, texts):
        self.calls.extend(texts)
        if self.fail_on and any(self.fail_on in text for text in texts):
            raise EmbeddingError("fixture failure")
        return [[float(index + 1) for index in range(self.dimensions)] for _ in texts]


class KnowledgeEmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "embedding.db"
        with sqlite3.connect(self.database) as conn:
            conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
            conn.execute("CREATE TABLE artifacts (id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at INTEGER NOT NULL)")
            conn.execute("""CREATE TABLE knowledge_documents (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL DEFAULT '',
                filename TEXT NOT NULL DEFAULT '', scope TEXT NOT NULL DEFAULT 'general',
                project_space_id TEXT NOT NULL DEFAULT '',
                chunk_count INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL
            )""")
            apply_migrations(conn, lambda: 100)
            conn.execute("""INSERT INTO knowledge_documents
                (id, user_id, filename, scope, chunk_count, created_at, active_chunk_version)
                VALUES ('doc-1', 'user-1', 'a.md', 'general', 2, 100, 1)""")
            conn.executemany("""INSERT INTO knowledge_chunks
                (id, document_id, position, content, chunk_version, active, content_sha256)
                VALUES (?, 'doc-1', ?, ?, 1, 1, ?)""", [
                    ("chunk-1", 0, "alpha", "hash-alpha"),
                    ("chunk-2", 1, "beta", "hash-beta"),
                ])
        self.ids = 0
        self.clock = 100

    def tearDown(self):
        self.temp_dir.cleanup()

    def db(self):
        conn = sqlite3.connect(self.database)
        conn.row_factory = sqlite3.Row
        return conn

    def now(self):
        self.clock += 1
        return self.clock

    def new_id(self, prefix):
        self.ids += 1
        return f"{prefix}-{self.ids}"

    def service(self, provider, model="embed-v1"):
        config = EmbeddingConfig(
            provider="openai_compatible", base_url="https://example.test/v1",
            api_key="secret", model=model, dimensions=3,
        )
        return KnowledgeEmbeddingService(self.db, self.now, self.new_id, config, provider)

    def test_vectors_are_normalized_and_validated(self):
        payload = pack_vector([3.0, 4.0], 2)
        values = sqlite3.Binary(payload)
        self.assertEqual(len(values), 8)
        unpacked = unpack_vector(payload, 2)
        self.assertAlmostEqual(sum(value * value for value in unpacked), 1.0, places=5)
        with self.assertRaises(EmbeddingError):
            pack_vector([math.nan, 1.0], 2)

    def test_enabled_configuration_requires_endpoint_key_model_and_dimensions(self):
        with self.assertRaises(ValueError):
            EmbeddingConfig(provider="openai_compatible").validate()
        EmbeddingConfig(
            provider="openai_compatible", base_url="https://example.test/v1",
            api_key="secret", model="embed-v1", dimensions=3,
        ).validate()

    def test_job_succeeds_and_reuses_unchanged_content(self):
        provider = FakeProvider()
        service = self.service(provider)
        service.enqueue_document("doc-1", "user-1")
        first = service.process_next()
        self.assertEqual(first["status"], "ready")
        self.assertEqual(len(provider.calls), 2)
        service.enqueue_document("doc-1", "user-1")
        second = service.process_next()
        self.assertEqual(second["reused_count"], 2)
        self.assertEqual(len(provider.calls), 2)
        with self.db() as conn:
            document = conn.execute("""SELECT active_embedding_model_version, embedding_status
                FROM knowledge_documents WHERE id = 'doc-1'""").fetchone()
        self.assertEqual(document["active_embedding_model_version"], service.config.version)
        self.assertEqual(document["embedding_status"], "ready")

    def test_admin_inventory_status_and_rollback_targets_are_content_free(self):
        service = self.service(FakeProvider())
        status = service.status()
        self.assertTrue(status["enabled"])
        self.assertTrue(status["configuration"]["endpoint_configured"])
        self.assertTrue(status["configuration"]["credential_configured"])
        self.assertEqual(status["jobs"], {
            "queued": 0, "running": 0, "ready": 0, "partial": 0, "failed": 0,
        })
        self.assertEqual(service.inventory()["document_count"], 1)
        self.assertEqual(service.rollback_targets(), [])
        service.enqueue_document("doc-1", "user-1")
        service.process_next()
        targets = service.rollback_targets()
        self.assertEqual(targets[0]["filename"], "a.md")
        self.assertEqual(targets[0]["available_model_versions"], [service.config.version])
        with self.db() as conn:
            conn.execute("CREATE TABLE thread_folders (id TEXT PRIMARY KEY, user_id TEXT NOT NULL)")
        self.assertEqual(service.rollback_targets("user-2"), [])
        self.assertEqual(service.rollback_targets("user-1")[0]["document_id"], "doc-1")
        self.assertNotIn("content", targets[0])
        self.assertNotIn("vector", targets[0])

    def test_partial_failure_keeps_previous_active_model(self):
        first = self.service(FakeProvider(), "embed-v1")
        first.enqueue_document("doc-1", "user-1")
        self.assertEqual(first.process_next()["status"], "ready")
        previous = first.config.version
        second = self.service(FakeProvider(fail_on="beta"), "embed-v2")
        second.enqueue_document("doc-1", "user-1")
        result = second.process_next()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["failed_count"], 1)
        with self.db() as conn:
            document = conn.execute("""SELECT active_embedding_model_version, embedding_status
                FROM knowledge_documents WHERE id = 'doc-1'""").fetchone()
        self.assertEqual(document["active_embedding_model_version"], previous)
        self.assertEqual(document["embedding_status"], "partial")
        first.rollback_document("doc-1", previous)

    def test_disabled_configuration_never_queues(self):
        service = KnowledgeEmbeddingService(
            self.db, self.now, self.new_id, EmbeddingConfig(), None
        )
        self.assertEqual(service.enqueue_document("doc-1")["status"], "disabled")
        self.assertIsNone(service.process_next())

    def test_vector_candidates_enforce_general_library_acl(self):
        provider = FakeProvider()
        service = self.service(provider)
        service.enqueue_document("doc-1", "user-1")
        service.process_next()
        query_vector, model_version = service.embed_query("alpha")
        knowledge = KnowledgeService(self.db)
        own = knowledge.vector_candidates("user-1", query_vector, model_version)
        foreign = knowledge.vector_candidates("user-2", query_vector, model_version)
        self.assertEqual({item["document_id"] for item in own}, {"doc-1"})
        self.assertEqual(foreign, [])

    def test_vector_candidates_require_project_membership(self):
        provider = FakeProvider()
        service = self.service(provider)
        service.enqueue_document("doc-1", "user-1")
        service.process_next()
        with self.db() as conn:
            conn.execute("CREATE TABLE thread_folders (id TEXT PRIMARY KEY)")
            conn.execute("CREATE TABLE space_members (space_id TEXT NOT NULL, user_id TEXT NOT NULL)")
            conn.execute("INSERT INTO thread_folders VALUES ('space-1')")
            conn.execute("INSERT INTO space_members VALUES ('space-1', 'member-1')")
            conn.execute("""UPDATE knowledge_documents
                SET scope = 'project', project_space_id = 'space-1' WHERE id = 'doc-1'""")
        query_vector, model_version = service.embed_query("alpha")
        knowledge = KnowledgeService(self.db)
        member = knowledge.vector_candidates(
            "member-1", query_vector, model_version, project_space_id="space-1"
        )
        outsider = knowledge.vector_candidates(
            "outsider", query_vector, model_version, project_space_id="space-1"
        )
        self.assertEqual({item["document_id"] for item in member}, {"doc-1"})
        self.assertEqual(outsider, [])


if __name__ == "__main__":
    unittest.main()
