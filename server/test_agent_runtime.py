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
                run_phase TEXT NOT NULL DEFAULT 'planning',
                phase_updated_at INTEGER DEFAULT 0,
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
        ids = iter(["event_1", "event_2", "event_3", "event_4", "event_5", "event_6", "event_7", "event_8"])
        times = iter([10, 20, 30, 40, 50, 60, 70, 80])
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

    def test_phase_transitions_are_durable_and_terminal_phases_cannot_resume(self):
        self.store.transition_phase(self.conn, "run_1", "retrieving")
        self.store.transition_phase(self.conn, "run_1", "generating")
        self.store.transition_phase(self.conn, "run_1", "reflecting")
        self.store.transition_phase(self.conn, "run_1", "completed")
        row = self.conn.execute("SELECT run_phase, phase_updated_at FROM runs WHERE id = 'run_1'").fetchone()
        self.assertEqual(row["run_phase"], "completed")
        self.assertGreater(row["phase_updated_at"], 0)
        with self.assertRaises(RunStateError):
            self.store.transition_phase(self.conn, "run_1", "generating")


if __name__ == "__main__":
    unittest.main()
