import sqlite3
import unittest

from server.agent_runtime import AgentRuntimeStore, RunStateError, RuntimeDependencies


class AgentRuntimeStoreTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                completed_at INTEGER,
                error TEXT DEFAULT ''
            );
            CREATE TABLE run_events (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                type TEXT NOT NULL,
                payload TEXT NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                sequence INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            );
            INSERT INTO runs (id, status) VALUES ('run_1', 'running');
            """
        )
        ids = iter(["event_1", "event_2", "event_3"])
        times = iter([10, 20, 30, 40])
        self.store = AgentRuntimeStore(RuntimeDependencies(
            new_id=lambda _prefix: next(ids),
            now=lambda: next(times),
        ))

    def tearDown(self):
        self.conn.close()

    def test_events_have_stable_sequence_and_schema_version(self):
        self.assertEqual(self.store.append_event(self.conn, "run_1", "started"), 1)
        self.assertEqual(self.store.append_event(self.conn, "run_1", "model_request", {"model": "test"}), 2)
        rows = self.conn.execute(
            "SELECT sequence, schema_version, type FROM run_events ORDER BY sequence"
        ).fetchall()
        self.assertEqual([row["sequence"] for row in rows], [1, 2])
        self.assertEqual([row["schema_version"] for row in rows], [1, 1])

    def test_terminal_run_cannot_be_resumed(self):
        self.store.transition_run(self.conn, "run_1", "completed")
        with self.assertRaises(RunStateError):
            self.store.transition_run(self.conn, "run_1", "running")

    def test_confirmation_can_resume_then_complete(self):
        self.store.transition_run(self.conn, "run_1", "awaiting_confirmation")
        self.store.transition_run(self.conn, "run_1", "running")
        self.store.transition_run(self.conn, "run_1", "completed")
        row = self.conn.execute("SELECT status, completed_at FROM runs WHERE id = 'run_1'").fetchone()
        self.assertEqual(row["status"], "completed")
        self.assertIsNotNone(row["completed_at"])


if __name__ == "__main__":
    unittest.main()
