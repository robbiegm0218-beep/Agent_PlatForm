"""Knowledge read-model service; write migration follows in P41-2c/d."""
from __future__ import annotations

import sqlite3

from server.knowledge_embeddings import EmbeddingError, unpack_vector


class KnowledgeService:
    def __init__(self, db_factory):
        self.db_factory = db_factory

    def list_visible(self, user_id: str):
        with self.db_factory() as conn:
            return conn.execute("""SELECT knowledge_documents.id, knowledge_documents.filename, knowledge_documents.mime_type,
                knowledge_documents.size_bytes, knowledge_documents.chunk_count, knowledge_documents.created_at,
                knowledge_documents.scope, knowledge_documents.project_space_id, knowledge_documents.upload_origin,
                knowledge_documents.created_by_user_id, knowledge_documents.processing_status,
                knowledge_documents.active_ingestion_run_id, knowledge_documents.updated_at,
                knowledge_documents.document_ir_version, knowledge_documents.parser_version,
                knowledge_documents.parsed_block_count, knowledge_documents.normalized_text_sha256,
                knowledge_documents.active_chunk_version, knowledge_documents.chunk_policy_version,
                knowledge_documents.chunk_preset, knowledge_documents.active_embedding_model_version,
                knowledge_documents.embedding_status, knowledge_documents.embedding_updated_at,
                thread_folders.name AS project_space_name
                FROM knowledge_documents LEFT JOIN thread_folders ON thread_folders.id = knowledge_documents.project_space_id
                WHERE (knowledge_documents.user_id = ? AND knowledge_documents.scope = 'general') OR
                (knowledge_documents.scope = 'project' AND EXISTS (SELECT 1 FROM space_members WHERE space_members.space_id = knowledge_documents.project_space_id AND space_members.user_id = ?))
                ORDER BY knowledge_documents.created_at DESC""", (user_id, user_id)).fetchall()

    def get_visible(self, document_id: str, user_id: str):
        with self.db_factory() as conn:
            return conn.execute("""SELECT knowledge_documents.* FROM knowledge_documents
                WHERE knowledge_documents.id = ? AND (
                  (knowledge_documents.scope = 'general' AND knowledge_documents.user_id = ?) OR
                  (knowledge_documents.scope = 'project' AND EXISTS (
                    SELECT 1 FROM space_members
                    WHERE space_members.space_id = knowledge_documents.project_space_id
                      AND space_members.user_id = ?
                  ))
                )""", (document_id, user_id, user_id)).fetchone()

    def list_for_space(self, space_id: str):
        with self.db_factory() as conn:
            return conn.execute("""SELECT knowledge_documents.id, knowledge_documents.filename, knowledge_documents.mime_type,
                knowledge_documents.size_bytes, knowledge_documents.chunk_count, knowledge_documents.created_at,
                knowledge_documents.upload_origin, knowledge_documents.processing_status,
                knowledge_documents.active_ingestion_run_id, knowledge_documents.updated_at,
                knowledge_documents.document_ir_version, knowledge_documents.parser_version,
                knowledge_documents.parsed_block_count, knowledge_documents.active_chunk_version,
                knowledge_documents.chunk_policy_version, knowledge_documents.chunk_preset,
                knowledge_documents.active_embedding_model_version,
                knowledge_documents.embedding_status, knowledge_documents.embedding_updated_at,
                users.name AS author_name
                FROM knowledge_documents JOIN users ON users.id = knowledge_documents.created_by_user_id
                WHERE knowledge_documents.scope = 'project' AND knowledge_documents.project_space_id = ?
                ORDER BY knowledge_documents.created_at DESC""", (space_id,)).fetchall()

    def searchable_chunks(self, user_id: str, project_space_id: str = "", include_all_projects: bool = False):
        with self.db_factory() as conn:
            if project_space_id:
                return conn.execute("""SELECT knowledge_chunks.*, knowledge_documents.filename, knowledge_documents.scope, knowledge_documents.project_space_id
                    FROM knowledge_chunks JOIN knowledge_documents ON knowledge_documents.id = knowledge_chunks.document_id
                    WHERE knowledge_chunks.active = 1 AND ((knowledge_documents.scope = 'general' AND knowledge_documents.user_id = ?) OR
                    (knowledge_documents.scope = 'project' AND knowledge_documents.project_space_id = ? AND
                    EXISTS (SELECT 1 FROM space_members WHERE space_members.space_id = ? AND space_members.user_id = ?)))""",
                    (user_id, project_space_id, project_space_id, user_id)).fetchall()
            if include_all_projects:
                return conn.execute("""SELECT knowledge_chunks.*, knowledge_documents.filename, knowledge_documents.scope, knowledge_documents.project_space_id
                    FROM knowledge_chunks JOIN knowledge_documents ON knowledge_documents.id = knowledge_chunks.document_id
                    WHERE knowledge_chunks.active = 1 AND ((knowledge_documents.scope = 'general' AND knowledge_documents.user_id = ?) OR
                    (knowledge_documents.scope = 'project' AND EXISTS
                        (SELECT 1 FROM space_members WHERE space_members.space_id = knowledge_documents.project_space_id
                         AND space_members.user_id = ?)))""", (user_id, user_id)).fetchall()
            return conn.execute("""SELECT knowledge_chunks.*, knowledge_documents.filename, knowledge_documents.scope, knowledge_documents.project_space_id
                FROM knowledge_chunks JOIN knowledge_documents ON knowledge_documents.id = knowledge_chunks.document_id
                WHERE knowledge_chunks.active = 1 AND knowledge_documents.user_id = ? AND knowledge_documents.scope = 'general'""", (user_id,)).fetchall()

    def fts_candidates(
        self,
        user_id: str,
        fts_query: str,
        *,
        project_space_id: str = "",
        include_all_projects: bool = False,
        limit: int = 64,
        neighbor_radius: int = 1,
    ):
        if not fts_query:
            return [], "insufficient_query_terms"
        acl = "knowledge_documents.scope = 'general' AND knowledge_documents.user_id = ?"
        params: list = [user_id]
        if project_space_id:
            acl = f"""({acl}) OR (
                knowledge_documents.scope = 'project'
                AND knowledge_documents.project_space_id = ?
                AND EXISTS (
                  SELECT 1 FROM space_members
                  WHERE space_members.space_id = knowledge_documents.project_space_id
                    AND space_members.user_id = ?
                )
            )"""
            params.extend([project_space_id, user_id])
        elif include_all_projects:
            acl = f"""({acl}) OR (
                knowledge_documents.scope = 'project'
                AND EXISTS (
                  SELECT 1 FROM space_members
                  WHERE space_members.space_id = knowledge_documents.project_space_id
                    AND space_members.user_id = ?
                )
            )"""
            params.append(user_id)
        try:
            with self.db_factory() as conn:
                ranked = conn.execute(
                    f"""SELECT knowledge_chunks.*, knowledge_documents.filename,
                               knowledge_documents.scope, knowledge_documents.project_space_id,
                               bm25(knowledge_chunks_fts, 0.0, 0.0, 5.0, 3.0, 1.0, 1.5) AS fts_rank
                        FROM knowledge_chunks_fts
                        JOIN knowledge_chunks ON knowledge_chunks.id = knowledge_chunks_fts.chunk_id
                        JOIN knowledge_documents ON knowledge_documents.id = knowledge_chunks.document_id
                        WHERE knowledge_chunks_fts MATCH ?
                          AND knowledge_chunks.active = 1
                          AND ({acl})
                        ORDER BY fts_rank ASC, knowledge_chunks.position ASC
                        LIMIT ?""",
                    [fts_query, *params, min(max(int(limit), 1), 200)],
                ).fetchall()
                candidates = []
                for row in ranked:
                    item = dict(row)
                    item["bm25_score"] = round(-float(item.pop("fts_rank") or 0.0), 6)
                    item["retrieval_candidate"] = True
                    candidates.append(item)
                if not candidates or neighbor_radius <= 0:
                    return candidates, "" if candidates else "no_fts_candidates"
                clauses = []
                neighbor_params = []
                for item in candidates:
                    clauses.append("(knowledge_chunks.document_id = ? AND knowledge_chunks.position BETWEEN ? AND ?)")
                    neighbor_params.extend([
                        item["document_id"],
                        max(0, int(item["position"]) - neighbor_radius),
                        int(item["position"]) + neighbor_radius,
                    ])
                neighbors = conn.execute(
                    f"""SELECT knowledge_chunks.*, knowledge_documents.filename,
                               knowledge_documents.scope, knowledge_documents.project_space_id
                        FROM knowledge_chunks
                        JOIN knowledge_documents ON knowledge_documents.id = knowledge_chunks.document_id
                        WHERE knowledge_chunks.active = 1 AND ({' OR '.join(clauses)})""",
                    neighbor_params,
                ).fetchall()
        except sqlite3.OperationalError:
            return [], "fts_unavailable"
        seen = {(str(item["document_id"]), int(item["position"])) for item in candidates}
        for row in neighbors:
            item = dict(row)
            key = (str(item["document_id"]), int(item["position"]))
            if key in seen:
                continue
            seen.add(key)
            item["bm25_score"] = None
            item["retrieval_candidate"] = False
            candidates.append(item)
        return candidates, ""

    def vector_candidates(
        self,
        user_id: str,
        query_vector: list[float],
        model_version: str,
        *,
        project_space_id: str = "",
        include_all_projects: bool = False,
        limit: int = 64,
        minimum_score: float = 0.62,
    ):
        if not query_vector or not model_version:
            return []
        acl = "knowledge_documents.scope = 'general' AND knowledge_documents.user_id = ?"
        params: list = [model_version, len(query_vector), user_id]
        if project_space_id:
            acl = f"""({acl}) OR (
                knowledge_documents.scope = 'project'
                AND knowledge_documents.project_space_id = ?
                AND EXISTS (
                  SELECT 1 FROM space_members
                  WHERE space_members.space_id = knowledge_documents.project_space_id
                    AND space_members.user_id = ?
                )
            )"""
            params.extend([project_space_id, user_id])
        elif include_all_projects:
            acl = f"""({acl}) OR (
                knowledge_documents.scope = 'project'
                AND EXISTS (
                  SELECT 1 FROM space_members
                  WHERE space_members.space_id = knowledge_documents.project_space_id
                    AND space_members.user_id = ?
                )
            )"""
            params.append(user_id)
        with self.db_factory() as conn:
            rows = conn.execute(
                f"""SELECT knowledge_chunks.*, knowledge_documents.filename,
                           knowledge_documents.scope, knowledge_documents.project_space_id,
                           knowledge_chunk_embeddings.vector_blob,
                           knowledge_chunk_embeddings.dimensions
                    FROM knowledge_chunk_embeddings
                    JOIN knowledge_chunks
                      ON knowledge_chunks.id = knowledge_chunk_embeddings.chunk_id
                    JOIN knowledge_documents
                      ON knowledge_documents.id = knowledge_chunks.document_id
                    WHERE knowledge_chunk_embeddings.model_version = ?
                      AND knowledge_chunk_embeddings.dimensions = ?
                      AND knowledge_chunk_embeddings.status = 'ready'
                      AND knowledge_chunk_embeddings.vector_blob IS NOT NULL
                      AND knowledge_chunks.active = 1
                      AND knowledge_documents.active_embedding_model_version = ?
                      AND ({acl})""",
                [model_version, len(query_vector), model_version, *params[2:]],
            ).fetchall()
        ranked = []
        for row in rows:
            try:
                vector = unpack_vector(row["vector_blob"], int(row["dimensions"]))
            except (EmbeddingError, ValueError, TypeError):
                continue
            score = sum(left * right for left, right in zip(query_vector, vector))
            if score < minimum_score:
                continue
            item = dict(row)
            item.pop("vector_blob", None)
            item["vector_score"] = round(score, 6)
            item["semantic_candidate"] = True
            ranked.append(item)
        ranked.sort(
            key=lambda item: (
                -float(item["vector_score"]),
                int(item.get("position", 0)),
                str(item.get("id", "")),
            )
        )
        return ranked[: min(max(int(limit), 1), 200)]

    def candidate_neighbors(self, candidates: list[dict], radius: int = 1):
        if not candidates or radius <= 0:
            return []
        clauses = []
        params = []
        for item in candidates:
            clauses.append("(knowledge_chunks.document_id = ? AND knowledge_chunks.position BETWEEN ? AND ?)")
            params.extend([
                str(item.get("document_id", "")),
                max(0, int(item.get("position", 0)) - radius),
                int(item.get("position", 0)) + radius,
            ])
        with self.db_factory() as conn:
            return conn.execute(
                f"""SELECT knowledge_chunks.*, knowledge_documents.filename,
                           knowledge_documents.scope, knowledge_documents.project_space_id
                    FROM knowledge_chunks
                    JOIN knowledge_documents ON knowledge_documents.id = knowledge_chunks.document_id
                    WHERE knowledge_chunks.active = 1 AND ({' OR '.join(clauses)})""",
                params,
            ).fetchall()

    @staticmethod
    def _refresh_fts_document(conn, document_id: str) -> None:
        conn.execute("DELETE FROM knowledge_chunks_fts WHERE document_id = ?", (document_id,))
        conn.execute(
            """INSERT INTO knowledge_chunks_fts
               (chunk_id, document_id, filename, title, body, tags)
               SELECT knowledge_chunks.id, knowledge_chunks.document_id,
                      knowledge_documents.filename, knowledge_chunks.section_path_json,
                      knowledge_chunks.content,
                      knowledge_chunks.preset || ' ' || knowledge_chunks.source_location_json
               FROM knowledge_chunks
               JOIN knowledge_documents ON knowledge_documents.id = knowledge_chunks.document_id
               WHERE knowledge_chunks.document_id = ? AND knowledge_chunks.active = 1""",
            (document_id,),
        )
        conn.execute(
            """UPDATE knowledge_search_index_state
               SET indexed_chunk_count = (SELECT COUNT(*) FROM knowledge_chunks_fts)
               WHERE id = 1""",
        )

    def record_retrieval_trace(self, trace: dict) -> None:
        with self.db_factory() as conn:
            # Retrieval can run while the chat request owns a write transaction.
            # Observability must never wait on that lock or delay the answer.
            conn.execute("PRAGMA busy_timeout = 0")
            conn.execute(
                """INSERT INTO knowledge_retrieval_traces
                   (id, user_id, project_space_id, query_sha256, backend,
                    policy_version, candidate_count, selected_count, fallback_reason,
                    candidate_summary_json, duration_ms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace["id"], trace["user_id"], trace.get("project_space_id", ""),
                    trace["query_sha256"], trace["backend"], trace["policy_version"],
                    int(trace.get("candidate_count", 0)), int(trace.get("selected_count", 0)),
                    trace.get("fallback_reason", ""),
                    trace.get("candidate_summary_json", "[]"),
                    int(trace.get("duration_ms", 0)), int(trace["created_at"]),
                ),
            )

    def retrieval_trace_summary(self, user_id: str, limit: int = 20):
        with self.db_factory() as conn:
            return conn.execute(
                """SELECT id, project_space_id, query_sha256, backend, policy_version,
                          candidate_count, selected_count, fallback_reason,
                          duration_ms, created_at
                   FROM knowledge_retrieval_traces WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, min(max(int(limit), 1), 100)),
            ).fetchall()

    def search_index_state(self):
        with self.db_factory() as conn:
            return conn.execute(
                """SELECT backend, policy_version, indexed_chunk_count, last_backfill_at
                   FROM knowledge_search_index_state WHERE id = 1"""
            ).fetchone()

    def persist_upload(self, document, chunks, blocks=()):
        storage_path = document["storage_path"]
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(document.pop("raw"))
        with self.db_factory() as conn:
            keys = ("id", "user_id", "filename", "storage_path", "mime_type", "content_hash", "size_bytes", "chunk_count", "created_at", "scope", "project_space_id", "upload_origin", "created_by_user_id", "processing_status", "active_ingestion_run_id", "updated_at", "document_ir_version", "parser_version", "parsed_block_count", "normalized_text_sha256", "active_chunk_version", "chunk_policy_version", "chunk_preset")
            values = tuple(str(document[key]) if key == "storage_path" else document[key] for key in keys)
            conn.execute("""INSERT INTO knowledge_documents (id, user_id, filename, storage_path, mime_type, content_hash, size_bytes, chunk_count, created_at, scope, project_space_id, upload_origin, created_by_user_id, processing_status, active_ingestion_run_id, updated_at, document_ir_version, parser_version, parsed_block_count, normalized_text_sha256, active_chunk_version, chunk_policy_version, chunk_preset)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", values)
            self._insert_chunks(conn, chunks)
            conn.execute(
                """INSERT INTO knowledge_chunk_versions
                   (id, document_id, version, policy_version, preset, status, chunk_count,
                    created_by_user_id, supersedes_version, created_at, activated_at)
                   VALUES (?, ?, 1, ?, ?, 'active', ?, ?, 0, ?, ?)""",
                (
                    f"chunk_version_{document['id']}_1", document["id"],
                    document["chunk_policy_version"], document["chunk_preset"],
                    len(chunks), document["created_by_user_id"],
                    document["created_at"], document["created_at"],
                ),
            )
            self._refresh_fts_document(conn, document["id"])
            conn.executemany(
                """INSERT INTO knowledge_document_blocks
                   (id, document_id, ingestion_run_id, ordinal, block_type, text,
                    section_path_json, source_location_json, metadata_json, char_count,
                    content_sha256, parser_version, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        block["block_id"], block["document_id"], block["ingestion_run_id"],
                        block["ordinal"], block["block_type"], block["text"],
                        block["section_path_json"], block["source_location_json"],
                        block["metadata_json"], block["char_count"], block["content_sha256"],
                        block["parser_version"], block["created_at"],
                    )
                    for block in blocks
                ],
            )

    def document_blocks(self, document_id: str, user_id: str):
        document = self.get_visible(document_id, user_id)
        if not document:
            return None
        with self.db_factory() as conn:
            blocks = conn.execute(
                """SELECT id, ordinal, block_type, text, section_path_json,
                          source_location_json, metadata_json, char_count,
                          content_sha256, parser_version, created_at
                   FROM knowledge_document_blocks
                   WHERE document_id = ? ORDER BY ordinal ASC""",
                (document_id,),
            ).fetchall()
        return document, blocks

    @staticmethod
    def _insert_chunks(conn, chunks):
        conn.executemany(
            """INSERT INTO knowledge_chunks
               (id, document_id, position, content, chunk_version, active,
                block_ids_json, section_path_json, source_location_json,
                token_count, overlap_tokens, policy_version, preset,
                content_sha256, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    chunk["id"], chunk["document_id"], chunk["position"], chunk["content"],
                    chunk["chunk_version"], chunk["active"], chunk["block_ids_json"],
                    chunk["section_path_json"], chunk["source_location_json"],
                    chunk["token_count"], chunk["overlap_tokens"], chunk["policy_version"],
                    chunk["preset"], chunk["content_sha256"], chunk["created_at"],
                )
                for chunk in chunks
            ],
        )

    def chunk_results(self, document_id: str, user_id: str):
        document = self.get_visible(document_id, user_id)
        if not document:
            return None
        with self.db_factory() as conn:
            versions = conn.execute(
                """SELECT version, policy_version, preset, status, chunk_count,
                          supersedes_version, error_message, created_at, activated_at
                   FROM knowledge_chunk_versions WHERE document_id = ?
                   ORDER BY version DESC""",
                (document_id,),
            ).fetchall()
            chunks = conn.execute(
                """SELECT id, position, content, chunk_version, block_ids_json,
                          section_path_json, source_location_json, token_count,
                          overlap_tokens, policy_version, preset, content_sha256,
                          created_at
                   FROM knowledge_chunks
                   WHERE document_id = ? AND active = 1 ORDER BY position""",
                (document_id,),
            ).fetchall()
        return document, versions, chunks

    def get_manageable(self, document_id: str, actor_id: str):
        with self.db_factory() as conn:
            return conn.execute(
                """SELECT * FROM knowledge_documents WHERE id = ? AND (
                     (scope = 'general' AND user_id = ?) OR
                     (scope = 'project' AND EXISTS (
                       SELECT 1 FROM thread_folders
                       WHERE thread_folders.id = knowledge_documents.project_space_id
                         AND thread_folders.user_id = ?
                     ))
                   )""",
                (document_id, actor_id, actor_id),
            ).fetchone()

    def activate_new_chunks(self, document_id: str, actor_id: str, chunks, created_at: int):
        document = self.get_manageable(document_id, actor_id)
        if not document:
            return None
        with self.db_factory() as conn:
            current_version = int(document["active_chunk_version"])
            version = int(conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM knowledge_chunk_versions WHERE document_id = ?",
                (document_id,),
            ).fetchone()[0])
            rows = [
                dict(
                    chunk,
                    id=f"{chunk['id']}_v{version}",
                    chunk_version=version,
                    active=0,
                    created_at=created_at,
                )
                for chunk in chunks
            ]
            self._insert_chunks(conn, rows)
            policy_version = rows[0]["policy_version"] if rows else ""
            preset = rows[0]["preset"] if rows else ""
            conn.execute(
                """INSERT INTO knowledge_chunk_versions
                   (id, document_id, version, policy_version, preset, status, chunk_count,
                    created_by_user_id, supersedes_version, created_at, activated_at)
                   VALUES (?, ?, ?, ?, ?, 'building', ?, ?, ?, ?, 0)""",
                (
                    f"chunk_version_{document_id}_{version}", document_id, version,
                    policy_version, preset, len(rows), actor_id, current_version, created_at,
                ),
            )
            conn.execute("UPDATE knowledge_chunks SET active = 0 WHERE document_id = ?", (document_id,))
            conn.execute("UPDATE knowledge_chunks SET active = 1 WHERE document_id = ? AND chunk_version = ?", (document_id, version))
            conn.execute("UPDATE knowledge_chunk_versions SET status = 'archived' WHERE document_id = ? AND status = 'active'", (document_id,))
            conn.execute(
                "UPDATE knowledge_chunk_versions SET status = 'active', activated_at = ? WHERE document_id = ? AND version = ?",
                (created_at, document_id, version),
            )
            conn.execute(
                """UPDATE knowledge_documents
                   SET active_chunk_version = ?, chunk_policy_version = ?, chunk_preset = ?,
                       chunk_count = ?, updated_at = ?
                   WHERE id = ?""",
                (version, policy_version, preset, len(rows), created_at, document_id),
            )
            self._refresh_fts_document(conn, document_id)
        return version

    def stage_migration_version(
        self,
        document_id: str,
        actor_id: str,
        chunks,
        blocks,
        *,
        ingestion_run_id: str,
        document_ir_version: int,
        parser_version: str,
        normalized_sha256: str,
        created_at: int,
    ) -> int:
        """Persist a complete candidate version without changing active retrieval."""
        with self.db_factory() as conn:
            document = conn.execute(
                "SELECT * FROM knowledge_documents WHERE id = ?", (document_id,)
            ).fetchone()
            if not document:
                raise ValueError("历史资料不存在")
            current_version = int(document["active_chunk_version"])
            version = int(conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM knowledge_chunk_versions WHERE document_id = ?",
                (document_id,),
            ).fetchone()[0])
            rows = [
                dict(
                    chunk,
                    id=f"{chunk['id']}_v{version}",
                    chunk_version=version,
                    active=0,
                    created_at=created_at,
                )
                for chunk in chunks
            ]
            if not rows:
                raise ValueError("历史资料未生成候选片段")
            self._insert_chunks(conn, rows)
            policy_version = rows[0]["policy_version"]
            preset = rows[0]["preset"]
            conn.execute(
                """INSERT INTO knowledge_chunk_versions
                   (id, document_id, version, policy_version, preset, status, chunk_count,
                    created_by_user_id, supersedes_version, created_at, activated_at)
                   VALUES (?, ?, ?, ?, ?, 'staged', ?, ?, ?, ?, 0)""",
                (
                    f"chunk_version_{document_id}_{version}", document_id, version,
                    policy_version, preset, len(rows), actor_id, current_version, created_at,
                ),
            )
            conn.executemany(
                """INSERT OR REPLACE INTO knowledge_document_blocks
                   (id, document_id, ingestion_run_id, ordinal, block_type, text,
                    section_path_json, source_location_json, metadata_json, char_count,
                    content_sha256, parser_version, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        block["block_id"], block["document_id"], block["ingestion_run_id"],
                        block["ordinal"], block["block_type"], block["text"],
                        block["section_path_json"], block["source_location_json"],
                        block["metadata_json"], block["char_count"], block["content_sha256"],
                        block["parser_version"], block["created_at"],
                    )
                    for block in blocks
                ],
            )
            conn.execute(
                """UPDATE knowledge_documents
                   SET document_ir_version = ?, parser_version = ?, parsed_block_count = ?,
                       normalized_text_sha256 = ?, active_ingestion_run_id = ?,
                       processing_status = 'ready', updated_at = ?
                   WHERE id = ?""",
                (
                    document_ir_version, parser_version, len(blocks),
                    normalized_sha256, ingestion_run_id, created_at, document_id,
                ),
            )
        return version

    def activate_migration_version(
        self, document_id: str, target_version: int, activated_at: int
    ) -> int:
        with self.db_factory() as conn:
            target = conn.execute(
                """SELECT version, policy_version, preset, chunk_count
                   FROM knowledge_chunk_versions
                   WHERE document_id = ? AND version = ? AND status = 'staged'""",
                (document_id, target_version),
            ).fetchone()
            if not target:
                active = conn.execute(
                    """SELECT version FROM knowledge_chunk_versions
                       WHERE document_id = ? AND version = ? AND status = 'active'""",
                    (document_id, target_version),
                ).fetchone()
                if active:
                    return target_version
                raise ValueError("迁移候选切分版本不存在")
            conn.execute(
                """UPDATE knowledge_chunks
                   SET active = CASE WHEN chunk_version = ? THEN 1 ELSE 0 END
                   WHERE document_id = ?""",
                (target_version, document_id),
            )
            conn.execute(
                """UPDATE knowledge_chunk_versions SET status = 'archived'
                   WHERE document_id = ? AND status = 'active'""",
                (document_id,),
            )
            conn.execute(
                """UPDATE knowledge_chunk_versions SET status = 'active', activated_at = ?
                   WHERE document_id = ? AND version = ?""",
                (activated_at, document_id, target_version),
            )
            conn.execute(
                """UPDATE knowledge_documents SET active_chunk_version = ?,
                   chunk_policy_version = ?, chunk_preset = ?, chunk_count = ?,
                   updated_at = ? WHERE id = ?""",
                (
                    target["version"], target["policy_version"], target["preset"],
                    target["chunk_count"], activated_at, document_id,
                ),
            )
            self._refresh_fts_document(conn, document_id)
        return target_version

    def restore_migration_source(
        self, document_id: str, source_version: int, restored_at: int
    ) -> int:
        with self.db_factory() as conn:
            source = conn.execute(
                """SELECT version, policy_version, preset, chunk_count
                   FROM knowledge_chunk_versions
                   WHERE document_id = ? AND version = ? AND status IN ('archived', 'active')""",
                (document_id, source_version),
            ).fetchone()
            if not source:
                raise ValueError("迁移源切分版本不存在")
            conn.execute(
                """UPDATE knowledge_chunks
                   SET active = CASE WHEN chunk_version = ? THEN 1 ELSE 0 END
                   WHERE document_id = ?""",
                (source_version, document_id),
            )
            conn.execute(
                """UPDATE knowledge_chunk_versions SET status = 'staged'
                   WHERE document_id = ? AND status = 'active' AND version != ?""",
                (document_id, source_version),
            )
            conn.execute(
                """UPDATE knowledge_chunk_versions SET status = 'active', activated_at = ?
                   WHERE document_id = ? AND version = ?""",
                (restored_at, document_id, source_version),
            )
            conn.execute(
                """UPDATE knowledge_documents SET active_chunk_version = ?,
                   chunk_policy_version = ?, chunk_preset = ?, chunk_count = ?,
                   updated_at = ? WHERE id = ?""",
                (
                    source["version"], source["policy_version"], source["preset"],
                    source["chunk_count"], restored_at, document_id,
                ),
            )
            self._refresh_fts_document(conn, document_id)
        return source_version

    def chunks_for_version(self, document_id: str, version: int):
        with self.db_factory() as conn:
            return conn.execute(
                """SELECT knowledge_chunks.*, knowledge_documents.filename,
                          knowledge_documents.scope, knowledge_documents.project_space_id
                   FROM knowledge_chunks
                   JOIN knowledge_documents ON knowledge_documents.id = knowledge_chunks.document_id
                   WHERE knowledge_chunks.document_id = ?
                     AND knowledge_chunks.chunk_version = ?
                   ORDER BY knowledge_chunks.position""",
                (document_id, version),
            ).fetchall()

    def migration_candidate_chunks(
        self,
        batch_id: str,
        user_id: str,
        project_space_id: str = "",
        include_all_projects: bool = False,
    ):
        acl = "knowledge_documents.scope = 'general' AND knowledge_documents.user_id = ?"
        params: list = [batch_id, user_id]
        if project_space_id:
            acl = f"""({acl}) OR (
                knowledge_documents.scope = 'project'
                AND knowledge_documents.project_space_id = ?
                AND EXISTS (
                  SELECT 1 FROM space_members
                  WHERE space_members.space_id = knowledge_documents.project_space_id
                    AND space_members.user_id = ?
                )
            )"""
            params.extend([project_space_id, user_id])
        elif include_all_projects:
            acl = f"""({acl}) OR (
                knowledge_documents.scope = 'project'
                AND EXISTS (
                  SELECT 1 FROM space_members
                  WHERE space_members.space_id = knowledge_documents.project_space_id
                    AND space_members.user_id = ?
                )
            )"""
            params.append(user_id)
        with self.db_factory() as conn:
            return conn.execute(
                f"""SELECT knowledge_chunks.*, knowledge_documents.filename,
                           knowledge_documents.scope, knowledge_documents.project_space_id
                    FROM knowledge_migration_items
                    JOIN knowledge_chunks
                      ON knowledge_chunks.document_id = knowledge_migration_items.document_id
                     AND knowledge_chunks.chunk_version = knowledge_migration_items.target_chunk_version
                    JOIN knowledge_documents
                      ON knowledge_documents.id = knowledge_migration_items.document_id
                    WHERE knowledge_migration_items.batch_id = ?
                      AND knowledge_migration_items.status = 'staged'
                      AND ({acl})
                    ORDER BY knowledge_documents.id, knowledge_chunks.position""",
                params,
            ).fetchall()

    def rollback_chunks(self, document_id: str, actor_id: str, target_version: int, activated_at: int):
        document = self.get_manageable(document_id, actor_id)
        if not document:
            return None
        with self.db_factory() as conn:
            target = conn.execute(
                """SELECT version, policy_version, preset, chunk_count
                   FROM knowledge_chunk_versions
                   WHERE document_id = ? AND version = ? AND status IN ('active', 'archived')""",
                (document_id, target_version),
            ).fetchone()
            if not target:
                raise ValueError("目标切分版本不存在")
            conn.execute("UPDATE knowledge_chunks SET active = CASE WHEN chunk_version = ? THEN 1 ELSE 0 END WHERE document_id = ?", (target_version, document_id))
            conn.execute("UPDATE knowledge_chunk_versions SET status = 'archived' WHERE document_id = ? AND status = 'active'", (document_id,))
            conn.execute("UPDATE knowledge_chunk_versions SET status = 'active', activated_at = ? WHERE document_id = ? AND version = ?", (activated_at, document_id, target_version))
            conn.execute(
                """UPDATE knowledge_documents SET active_chunk_version = ?,
                   chunk_policy_version = ?, chunk_preset = ?, chunk_count = ?, updated_at = ?
                   WHERE id = ?""",
                (target["version"], target["policy_version"], target["preset"], target["chunk_count"], activated_at, document_id),
            )
            self._refresh_fts_document(conn, document_id)
        return target_version

    def delete_document(self, document_id: str, user_id: str):
        with self.db_factory() as conn:
            row = conn.execute("""SELECT storage_path FROM knowledge_documents WHERE id = ? AND (user_id = ? OR
                (scope = 'project' AND EXISTS (SELECT 1 FROM thread_folders WHERE thread_folders.id = knowledge_documents.project_space_id AND thread_folders.user_id = ?)))""", (document_id, user_id, user_id)).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM knowledge_chunks_fts WHERE document_id = ?", (document_id,))
            conn.execute("UPDATE knowledge_search_index_state SET indexed_chunk_count = (SELECT COUNT(*) FROM knowledge_chunks_fts) WHERE id = 1")
            conn.execute("DELETE FROM knowledge_document_blocks WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM knowledge_chunk_embeddings WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM knowledge_embedding_jobs WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM knowledge_chunk_versions WHERE document_id = ?", (document_id,))
            batch_ids = [
                str(item[0]) for item in conn.execute(
                    "SELECT batch_id FROM knowledge_migration_items WHERE document_id = ?",
                    (document_id,),
                ).fetchall()
            ]
            conn.execute(
                "DELETE FROM knowledge_migration_items WHERE document_id = ?",
                (document_id,),
            )
            for batch_id in batch_ids:
                if not conn.execute(
                    "SELECT 1 FROM knowledge_migration_items WHERE batch_id = ? LIMIT 1",
                    (batch_id,),
                ).fetchone():
                    conn.execute(
                        "DELETE FROM knowledge_migration_shadow_diffs WHERE batch_id = ?",
                        (batch_id,),
                    )
                    conn.execute(
                        "DELETE FROM knowledge_migration_batches WHERE id = ?",
                        (batch_id,),
                    )
            conn.execute("DELETE FROM knowledge_pipeline_events WHERE ingestion_run_id IN (SELECT id FROM knowledge_ingestion_runs WHERE document_id = ?)", (document_id,))
            conn.execute("DELETE FROM knowledge_ingestion_runs WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM knowledge_documents WHERE id = ?", (document_id,))
            return row["storage_path"]

    def delete_space_documents(self, space_id: str):
        with self.db_factory() as conn:
            rows = conn.execute("SELECT storage_path FROM knowledge_documents WHERE scope = 'project' AND project_space_id = ?", (space_id,)).fetchall()
            document_ids = [
                str(row[0]) for row in conn.execute(
                    "SELECT id FROM knowledge_documents WHERE scope = 'project' AND project_space_id = ?",
                    (space_id,),
                ).fetchall()
            ]
            if document_ids:
                marks = ",".join("?" for _ in document_ids)
                conn.execute(
                    f"DELETE FROM knowledge_migration_items WHERE document_id IN ({marks})",
                    document_ids,
                )
                conn.execute(
                    """DELETE FROM knowledge_migration_shadow_diffs
                       WHERE batch_id IN (
                         SELECT id FROM knowledge_migration_batches
                         WHERE NOT EXISTS (
                           SELECT 1 FROM knowledge_migration_items
                           WHERE knowledge_migration_items.batch_id = knowledge_migration_batches.id
                         )
                       )"""
                )
                conn.execute(
                    """DELETE FROM knowledge_migration_batches
                       WHERE NOT EXISTS (
                         SELECT 1 FROM knowledge_migration_items
                         WHERE knowledge_migration_items.batch_id = knowledge_migration_batches.id
                       )"""
                )
            conn.execute("DELETE FROM knowledge_chunks_fts WHERE document_id IN (SELECT id FROM knowledge_documents WHERE scope = 'project' AND project_space_id = ?)", (space_id,))
            conn.execute("UPDATE knowledge_search_index_state SET indexed_chunk_count = (SELECT COUNT(*) FROM knowledge_chunks_fts) WHERE id = 1")
            conn.execute("DELETE FROM knowledge_document_blocks WHERE document_id IN (SELECT id FROM knowledge_documents WHERE scope = 'project' AND project_space_id = ?)", (space_id,))
            conn.execute("DELETE FROM knowledge_chunk_embeddings WHERE document_id IN (SELECT id FROM knowledge_documents WHERE scope = 'project' AND project_space_id = ?)", (space_id,))
            conn.execute("DELETE FROM knowledge_embedding_jobs WHERE document_id IN (SELECT id FROM knowledge_documents WHERE scope = 'project' AND project_space_id = ?)", (space_id,))
            conn.execute("DELETE FROM knowledge_chunks WHERE document_id IN (SELECT id FROM knowledge_documents WHERE scope = 'project' AND project_space_id = ?)", (space_id,))
            conn.execute("DELETE FROM knowledge_chunk_versions WHERE document_id IN (SELECT id FROM knowledge_documents WHERE scope = 'project' AND project_space_id = ?)", (space_id,))
            conn.execute("DELETE FROM knowledge_pipeline_events WHERE ingestion_run_id IN (SELECT id FROM knowledge_ingestion_runs WHERE project_space_id = ?)", (space_id,))
            conn.execute("DELETE FROM knowledge_ingestion_runs WHERE project_space_id = ?", (space_id,))
            conn.execute("DELETE FROM knowledge_documents WHERE scope = 'project' AND project_space_id = ?", (space_id,))
            return [row["storage_path"] for row in rows]

    def update_document(self, document_id, actor_id, filename, scope, project_space_id):
        with self.db_factory() as conn:
            document = conn.execute("""SELECT * FROM knowledge_documents WHERE id = ? AND (user_id = ? OR
                (scope = 'project' AND EXISTS (SELECT 1 FROM thread_folders WHERE thread_folders.id = knowledge_documents.project_space_id AND thread_folders.user_id = ?)))""", (document_id, actor_id, actor_id)).fetchone()
            if not document:
                return None
            if project_space_id and not conn.execute("""SELECT id FROM thread_folders WHERE id = ? AND section = 'project' AND EXISTS
                (SELECT 1 FROM space_members WHERE space_members.space_id = thread_folders.id AND space_members.user_id = ?)""", (project_space_id, actor_id)).fetchone():
                raise PermissionError("没有目标项目空间的资料管理权限")
            conn.execute("UPDATE knowledge_documents SET filename = ?, scope = ?, project_space_id = ?, user_id = ? WHERE id = ?", (filename or document["filename"], scope, project_space_id if scope == "project" else "", actor_id if scope == "general" else document["user_id"], document_id))
            self._refresh_fts_document(conn, document_id)
            return conn.execute("SELECT * FROM knowledge_documents WHERE id = ?", (document_id,)).fetchone()
