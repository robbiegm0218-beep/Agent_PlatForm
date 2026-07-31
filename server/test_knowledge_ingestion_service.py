import hashlib
import sqlite3
import unittest

from server.knowledge_ingestion_service import KnowledgeIngestionService
from server.schema_migrations import apply_migrations


class KnowledgeIngestionServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE users (id TEXT PRIMARY KEY);
            CREATE TABLE artifacts (id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at INTEGER NOT NULL);
            CREATE TABLE knowledge_documents (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'general',
                project_space_id TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL
            );
            CREATE TABLE space_members (
                space_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                PRIMARY KEY (space_id, user_id)
            );
        """)
        apply_migrations(self.conn, lambda: 100)
        self.clock = 100
        self.ids = 0

        def db_factory():
            return _SharedConnection(self.conn)

        def current_time():
            self.clock += 1
            return self.clock

        def new_id(prefix):
            self.ids += 1
            return f"{prefix}_{self.ids}"

        self.service = KnowledgeIngestionService(db_factory, current_time, new_id)

    def tearDown(self):
        self.conn.close()

    def test_records_content_safe_pipeline_and_document_history(self):
        run_id, existing_document = self.service.begin(
            user_id="user-1",
            filename="guide.md",
            scope="general",
            project_space_id="",
            size_bytes=12,
            raw_sha256=hashlib.sha256(b"fixture").hexdigest(),
            idempotency_key="upload-request-1",
        )
        self.assertEqual(existing_document, "")
        self.service.stage(run_id, "validating", "started")
        self.service.stage(run_id, "validating", "completed", {"mime_type": "text/markdown"})
        self.service.stage(run_id, "parsing", "completed", {"extracted_chars": 12})
        self.conn.execute(
            """INSERT INTO knowledge_documents
               (id, user_id, scope, project_space_id, created_at, processing_status, active_ingestion_run_id, updated_at)
               VALUES ('doc-1', 'user-1', 'general', '', 100, 'processing', ?, 100)""",
            (run_id,),
        )
        self.service.complete(
            run_id,
            document_id="doc-1",
            normalized_sha256=hashlib.sha256(b"normalized").hexdigest(),
            block_count=3,
            chunk_count=2,
            parser_version="utf8-text-v1",
        )
        listed = self.service.list_visible("user-1")
        self.assertEqual(listed[0]["status"], "ready")
        history = self.service.document_history("doc-1", "user-1")
        self.assertIsNotNone(history)
        runs, events = history
        self.assertEqual(runs[0]["chunk_count"], 2)
        self.assertEqual(runs[0]["block_count"], 3)
        self.assertEqual([event["stage"] for event in events[run_id]], ["uploaded", "validating", "validating", "parsing", "ready"])
        self.assertNotIn("fixture", str([dict(event) for event in events[run_id]]))

    def test_failed_run_is_visible_only_to_actor_or_project_member(self):
        run_id, _ = self.service.begin(
            user_id="user-1",
            filename="broken.pdf",
            scope="project",
            project_space_id="space-1",
            size_bytes=8,
            raw_sha256=hashlib.sha256(b"broken").hexdigest(),
        )
        self.service.fail(run_id, "validating", "invalid signature", "PDF 文件签名无效")
        self.assertEqual(len(self.service.list_visible("user-1")), 1)
        self.assertEqual(self.service.list_visible("user-2"), [])
        self.conn.execute("INSERT INTO space_members VALUES ('space-1', 'user-2')")
        self.assertEqual(len(self.service.list_visible("user-2")), 1)

    def test_successful_idempotency_key_replays_document(self):
        run_id, _ = self.service.begin(
            user_id="user-1",
            filename="guide.md",
            scope="general",
            project_space_id="",
            size_bytes=12,
            raw_sha256=hashlib.sha256(b"fixture").hexdigest(),
            idempotency_key="upload-request-2",
        )
        self.conn.execute(
            """INSERT INTO knowledge_documents
               (id, user_id, scope, project_space_id, created_at, processing_status, active_ingestion_run_id, updated_at)
               VALUES ('doc-2', 'user-1', 'general', '', 100, 'processing', ?, 100)""",
            (run_id,),
        )
        self.service.complete(
            run_id,
            document_id="doc-2",
            normalized_sha256=hashlib.sha256(b"normalized").hexdigest(),
            block_count=1,
            chunk_count=1,
            parser_version="utf8-text-v1",
        )
        replay_run, document_id = self.service.begin(
            user_id="user-1",
            filename="guide.md",
            scope="general",
            project_space_id="",
            size_bytes=12,
            raw_sha256=hashlib.sha256(b"fixture").hexdigest(),
            idempotency_key="upload-request-2",
        )
        self.assertEqual((replay_run, document_id), (run_id, "doc-2"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM knowledge_ingestion_runs").fetchone()[0], 1)


class _SharedConnection:
    """Keep one in-memory connection open while preserving context semantics."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        return False


if __name__ == "__main__":
    unittest.main()
