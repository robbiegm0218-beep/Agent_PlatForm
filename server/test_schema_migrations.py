import sqlite3
import unittest

from server.schema_migrations import LATEST_SCHEMA_VERSION, Migration, MigrationError, apply_migrations, migration_status


class SchemaMigrationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")

    def tearDown(self):
        self.conn.close()

    def test_migrations_are_versioned_and_idempotent(self):
        first = apply_migrations(self.conn, lambda: 123)
        second = apply_migrations(self.conn, lambda: 456)
        self.assertEqual(first["current_version"], LATEST_SCHEMA_VERSION)
        self.assertTrue(second["ready"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], LATEST_SCHEMA_VERSION)
        self.assertIn("is_admin", {row[1] for row in self.conn.execute("PRAGMA table_info(users)")})
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'security_events'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'account_deletion_requests'").fetchone())
        self.assertIsNotNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'login_throttles'").fetchone())

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
