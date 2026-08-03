import sqlite3
import unittest

from server.knowledge_presets import KnowledgePresetService
from server.schema_migrations import apply_migrations


class KnowledgePresetServiceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
        self.conn.execute("CREATE TABLE artifacts (id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at INTEGER NOT NULL)")
        self.conn.execute("CREATE TABLE knowledge_documents (id TEXT PRIMARY KEY, created_at INTEGER NOT NULL)")
        apply_migrations(self.conn, lambda: 10)
        self.service = KnowledgePresetService(lambda: _ConnectionContext(self.conn), lambda: 20)

    def tearDown(self):
        self.conn.close()

    def test_three_presets_are_revisioned_and_used_by_policy(self):
        self.assertEqual([item["id"] for item in self.service.list()], [
            "standard", "long_document", "table_dense",
        ])
        updated = self.service.update("standard", {
            "parser_profile": "structure_preserving",
            "chunk_config": {
                "target_tokens": 700,
                "max_tokens": 1000,
                "overlap_tokens": 100,
            },
        }, "knowledge-admin")
        self.assertEqual(updated["revision"], 2)
        policy, _ = self.service.policy("standard")
        self.assertEqual(policy.version, "structure-token-v1:standard:r2")
        self.assertEqual(policy.target_tokens, 700)
        revisions = self.service.revisions("standard")
        self.assertEqual([item["revision"] for item in revisions], [2, 1])
        self.assertEqual(revisions[0]["chunk_config"]["target_tokens"], 700)
        self.assertNotIn("chunk_config_json", revisions[0])

    def test_unchanged_configuration_does_not_create_revision(self):
        _, current = self.service.policy("standard")
        with self.assertRaisesRegex(ValueError, "没有发生变化"):
            self.service.update("standard", {
                "parser_profile": current["parser_profile"],
                "chunk_config": current["chunk_config"],
            }, "knowledge-admin")
        self.assertEqual(len(self.service.revisions("standard")), 1)

    def test_invalid_preset_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "最大 Token"):
            self.service.update("standard", {
                "parser_profile": "auto",
                "chunk_config": {
                    "target_tokens": 900,
                    "max_tokens": 800,
                    "overlap_tokens": 50,
                },
            }, "knowledge-admin")


class _ConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args):
        self.connection.commit()
        return False


if __name__ == "__main__":
    unittest.main()
