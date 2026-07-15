from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Callable


EVENT_SCHEMA_VERSION = 1

RUN_TRANSITIONS = {
    "queued": {"running", "cancelled", "failed"},
    "running": {"awaiting_confirmation", "completed", "failed", "cancelled"},
    "awaiting_confirmation": {"running", "cancelled", "failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}

TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}


class RunStateError(ValueError):
    """Raised when a run attempts an invalid lifecycle transition."""


@dataclass(frozen=True)
class RuntimeDependencies:
    new_id: Callable[[str], str]
    now: Callable[[], int]


class AgentRuntimeStore:
    """Small persistence boundary for durable run state and audit events.

    It deliberately owns no model or HTTP behavior. This keeps the current
    local-first stack while giving future workers and MCP tools one lifecycle
    contract to use.
    """

    def __init__(self, dependencies: RuntimeDependencies):
        self._dependencies = dependencies

    def append_event(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        event_type: str,
        payload: dict | None = None,
    ) -> int:
        if not event_type or not isinstance(event_type, str):
            raise ValueError("运行事件类型无效")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("运行事件内容必须是对象")
        sequence = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS value FROM run_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()["value"]
        conn.execute(
            """
            INSERT INTO run_events
                (id, run_id, type, payload, schema_version, sequence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._dependencies.new_id("event"),
                run_id,
                event_type,
                json.dumps(payload or {}, ensure_ascii=False),
                EVENT_SCHEMA_VERSION,
                sequence,
                self._dependencies.now(),
            ),
        )
        return sequence

    def transition_run(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        target_status: str,
        *,
        error: str = "",
    ) -> str:
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            raise RunStateError("运行记录不存在")
        current_status = row["status"]
        if target_status == current_status:
            return current_status
        if target_status not in RUN_TRANSITIONS.get(current_status, set()):
            raise RunStateError(f"运行状态不能从 {current_status} 变为 {target_status}")

        completed_at = self._dependencies.now() if target_status in TERMINAL_RUN_STATUSES else None
        conn.execute(
            "UPDATE runs SET status = ?, completed_at = ?, error = ? WHERE id = ?",
            (target_status, completed_at, error, run_id),
        )
        return current_status
