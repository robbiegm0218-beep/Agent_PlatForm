"""Content-safe processing records for P51 knowledge ingestion."""

from __future__ import annotations

import json
import re
from typing import Callable


PIPELINE_STAGES = (
    "uploaded",
    "validating",
    "parsing",
    "normalized",
    "chunking",
    "lexical_indexing",
    "embedding",
    "ready",
)
RUN_STATUSES = {"running", "ready", "partial", "failed"}
EVENT_STATUSES = {"started", "completed", "skipped", "failed"}


def safe_error_code(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value).lower()).strip("_")
    return normalized[:80] or "processing_failed"


class KnowledgeIngestionService:
    def __init__(self, db_factory, now: Callable[[], int], new_id: Callable[[str], str]):
        self.db_factory = db_factory
        self.now = now
        self.new_id = new_id

    def _event(self, conn, run_id: str, stage: str, status: str, detail: dict | None = None) -> None:
        if stage not in PIPELINE_STAGES:
            raise ValueError(f"知识处理阶段无效：{stage}")
        if status not in EVENT_STATUSES:
            raise ValueError(f"知识处理事件状态无效：{status}")
        sequence = int(conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM knowledge_pipeline_events WHERE ingestion_run_id = ?",
            (run_id,),
        ).fetchone()[0])
        conn.execute(
            """INSERT INTO knowledge_pipeline_events
               (id, ingestion_run_id, sequence, stage, status, detail_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                self.new_id("knowledge_event"),
                run_id,
                sequence,
                stage,
                status,
                json.dumps(detail or {}, ensure_ascii=False),
                self.now(),
            ),
        )

    def begin(
        self,
        *,
        user_id: str,
        filename: str,
        scope: str,
        project_space_id: str,
        size_bytes: int,
        raw_sha256: str,
        idempotency_key: str = "",
    ) -> tuple[str, str]:
        current = self.now()
        run_id = self.new_id("knowledge_ingestion")
        with self.db_factory() as conn:
            if idempotency_key:
                existing = conn.execute(
                    "SELECT id, document_id, status FROM knowledge_ingestion_runs WHERE user_id = ? AND idempotency_key = ?",
                    (user_id, idempotency_key),
                ).fetchone()
                if existing:
                    if existing["status"] == "ready" and existing["document_id"]:
                        return str(existing["id"]), str(existing["document_id"])
                    if existing["status"] == "running":
                        raise ValueError("相同资料上传请求正在处理")
                    raise ValueError("相同资料上传请求已失败，请重新选择文件上传")
            conn.execute(
                """INSERT INTO knowledge_ingestion_runs
                   (id, user_id, filename, scope, project_space_id, trigger_type, status,
                    current_stage, raw_sha256, size_bytes, idempotency_key, started_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'upload', 'running', 'uploaded', ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    user_id,
                    filename[:255],
                    scope,
                    project_space_id,
                    raw_sha256,
                    size_bytes,
                    idempotency_key[:120],
                    current,
                    current,
                ),
            )
            self._event(conn, run_id, "uploaded", "completed", {"size_bytes": size_bytes})
        return run_id, ""

    def begin_reprocess(self, document: dict, actor_user_id: str, *, trigger_type: str,
                        parser_profile: str) -> str:
        if trigger_type not in {"reparse", "rechunk", "reindex"}:
            raise ValueError("资料重新处理类型无效")
        run_id = self.new_id("knowledge_ingestion")
        current = self.now()
        with self.db_factory() as conn:
            conn.execute(
                """INSERT INTO knowledge_ingestion_runs
                   (id, document_id, user_id, filename, scope, project_space_id,
                    trigger_type, status, current_stage, parser_profile,
                    raw_sha256, size_bytes, started_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'running', 'uploaded', ?, ?, ?, ?, ?)""",
                (
                    run_id, document["id"], actor_user_id, document["filename"],
                    document["scope"], document["project_space_id"], trigger_type,
                    parser_profile, document["content_hash"], int(document["size_bytes"]),
                    current, current,
                ),
            )
            self._event(conn, run_id, "uploaded", "completed", {"trigger_type": trigger_type})
        return run_id

    def stage(self, run_id: str, stage: str, status: str, detail: dict | None = None) -> None:
        if stage not in PIPELINE_STAGES:
            raise ValueError(f"知识处理阶段无效：{stage}")
        with self.db_factory() as conn:
            row = conn.execute("SELECT status FROM knowledge_ingestion_runs WHERE id = ?", (run_id,)).fetchone()
            if not row:
                raise ValueError("知识处理记录不存在")
            if row["status"] in {"ready", "partial"}:
                return
            conn.execute(
                "UPDATE knowledge_ingestion_runs SET current_stage = ?, updated_at = ? WHERE id = ?",
                (stage, self.now(), run_id),
            )
            self._event(conn, run_id, stage, status, detail)

    def fail(self, run_id: str, stage: str, error_code: str, error_message: str) -> None:
        message = str(error_message).strip()[:500]
        with self.db_factory() as conn:
            row = conn.execute("SELECT status FROM knowledge_ingestion_runs WHERE id = ?", (run_id,)).fetchone()
            if not row or row["status"] in {"ready", "partial"}:
                return
            current = self.now()
            conn.execute(
                """UPDATE knowledge_ingestion_runs
                   SET status = 'failed', current_stage = ?, error_code = ?, error_message = ?,
                       completed_at = ?, updated_at = ?
                   WHERE id = ?""",
                (stage, safe_error_code(error_code), message, current, current, run_id),
            )
            self._event(conn, run_id, stage, "failed", {"error_code": safe_error_code(error_code)})

    def complete(
        self,
        run_id: str,
        *,
        document_id: str,
        normalized_sha256: str,
        block_count: int,
        chunk_count: int,
        parser_version: str,
        chunk_policy_version: str = "fixed-char-v1",
        index_policy_version: str = "lexical-retrieval-v1",
    ) -> None:
        with self.db_factory() as conn:
            current = self.now()
            conn.execute(
                """UPDATE knowledge_ingestion_runs
                   SET document_id = ?, status = 'ready', current_stage = 'ready',
                       parser_version = ?, normalized_sha256 = ?, block_count = ?,
                       chunk_policy_version = ?, index_policy_version = ?,
                       chunk_count = ?, completed_at = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    document_id,
                    parser_version[:80],
                    normalized_sha256,
                    block_count,
                    chunk_policy_version[:80],
                    index_policy_version[:80],
                    chunk_count,
                    current,
                    current,
                    run_id,
                ),
            )
            conn.execute(
                """UPDATE knowledge_documents
                   SET processing_status = 'ready', active_ingestion_run_id = ?, updated_at = ?
                   WHERE id = ?""",
                (run_id, current, document_id),
            )
            self._event(conn, run_id, "ready", "completed", {
                "block_count": block_count,
                "chunk_count": chunk_count,
            })

    def list_visible(self, user_id: str, limit: int = 20):
        with self.db_factory() as conn:
            return conn.execute(
                """SELECT id, document_id, filename, scope, project_space_id, trigger_type,
                          status, current_stage, parser_profile, parser_version,
                          chunk_policy_version, index_policy_version, size_bytes, block_count,
                          chunk_count, warning_count, error_code, error_message,
                          started_at, completed_at, updated_at
                   FROM knowledge_ingestion_runs
                   WHERE user_id = ? OR (
                     scope = 'project' AND EXISTS (
                       SELECT 1 FROM space_members
                       WHERE space_members.space_id = knowledge_ingestion_runs.project_space_id
                         AND space_members.user_id = ?
                     )
                   )
                   ORDER BY updated_at DESC, id DESC LIMIT ?""",
                (user_id, user_id, min(max(limit, 1), 100)),
            ).fetchall()

    def document_history(self, document_id: str, user_id: str):
        with self.db_factory() as conn:
            visible = conn.execute(
                """SELECT id FROM knowledge_documents
                   WHERE id = ? AND (
                     (scope = 'general' AND user_id = ?) OR
                     (scope = 'project' AND EXISTS (
                       SELECT 1 FROM space_members
                       WHERE space_members.space_id = knowledge_documents.project_space_id
                         AND space_members.user_id = ?
                     ))
                   )""",
                (document_id, user_id, user_id),
            ).fetchone()
            if not visible:
                return None
            runs = conn.execute(
                """SELECT id, document_id, filename, trigger_type, status, current_stage,
                          parser_profile, parser_version, chunk_policy_version,
                          index_policy_version, size_bytes, block_count, chunk_count,
                          warning_count, error_code, error_message, started_at,
                          completed_at, updated_at
                   FROM knowledge_ingestion_runs
                   WHERE document_id = ? ORDER BY started_at DESC, id DESC""",
                (document_id,),
            ).fetchall()
            events = {}
            for run in runs:
                events[str(run["id"])] = conn.execute(
                    """SELECT sequence, stage, status, detail_json, created_at
                       FROM knowledge_pipeline_events
                       WHERE ingestion_run_id = ? ORDER BY sequence ASC""",
                    (run["id"],),
                ).fetchall()
        return runs, events
