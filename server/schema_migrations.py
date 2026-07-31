"""Versioned, transactional schema migrations for deployable instances."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _personal_accounts(conn: sqlite3.Connection) -> None:
    if "is_admin" not in _column_names(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    conn.execute("""CREATE TABLE IF NOT EXISTS security_events (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL,
            outcome TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL
        )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_security_events_user_created
            ON security_events(user_id, created_at DESC)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT UNIQUE NOT NULL,
            expires_at INTEGER NOT NULL,
            used_at INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user
            ON password_reset_tokens(user_id, created_at DESC)""")


def _account_deletion_requests(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS account_deletion_requests (
            user_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            requested_at INTEGER NOT NULL,
            scheduled_for INTEGER NOT NULL,
            cancelled_at INTEGER NOT NULL DEFAULT 0
        )""")


def _login_throttles(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS login_throttles (
            scope_key TEXT PRIMARY KEY,
            failure_count INTEGER NOT NULL DEFAULT 0,
            locked_until INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL
        )""")


def _trial_invitations(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS trial_invitations (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            token_hash TEXT UNIQUE NOT NULL,
            expires_at INTEGER NOT NULL,
            used_at INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trial_invitations_email ON trial_invitations(email, expires_at DESC)")


def _artifact_preview_contract(conn: sqlite3.Connection) -> None:
    columns = _column_names(conn, "artifacts")
    additions = (
        ("mime_type", "TEXT NOT NULL DEFAULT ''"),
        ("status", "TEXT NOT NULL DEFAULT 'ready'"),
        ("revision", "INTEGER NOT NULL DEFAULT 1"),
        ("size_bytes", "INTEGER NOT NULL DEFAULT 0"),
        ("updated_at", "INTEGER NOT NULL DEFAULT 0"),
        ("content_sha256", "TEXT NOT NULL DEFAULT ''"),
    )
    for name, declaration in additions:
        if name not in columns:
            conn.execute(f"ALTER TABLE artifacts ADD COLUMN {name} {declaration}")
    conn.execute("""UPDATE artifacts
        SET mime_type = CASE kind
            WHEN 'markdown' THEN 'text/markdown; charset=utf-8'
            WHEN 'html' THEN 'text/html; charset=utf-8'
            WHEN 'xlsx' THEN 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            WHEN 'json' THEN 'application/json; charset=utf-8'
            ELSE 'application/octet-stream'
        END
        WHERE mime_type = ''""")
    conn.execute("UPDATE artifacts SET updated_at = created_at WHERE updated_at = 0")


def _knowledge_ingestion_observability(conn: sqlite3.Connection) -> None:
    columns = _column_names(conn, "knowledge_documents")
    additions = (
        ("processing_status", "TEXT NOT NULL DEFAULT 'ready'"),
        ("active_ingestion_run_id", "TEXT NOT NULL DEFAULT ''"),
        ("updated_at", "INTEGER NOT NULL DEFAULT 0"),
    )
    for name, declaration in additions:
        if name not in columns:
            conn.execute(f"ALTER TABLE knowledge_documents ADD COLUMN {name} {declaration}")
    conn.execute("UPDATE knowledge_documents SET processing_status = 'ready' WHERE processing_status = ''")
    conn.execute("UPDATE knowledge_documents SET updated_at = created_at WHERE updated_at = 0")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_ingestion_runs (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL DEFAULT '',
            user_id TEXT NOT NULL,
            filename TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT 'general',
            project_space_id TEXT NOT NULL DEFAULT '',
            trigger_type TEXT NOT NULL DEFAULT 'upload',
            status TEXT NOT NULL,
            current_stage TEXT NOT NULL,
            parser_profile TEXT NOT NULL DEFAULT 'auto',
            parser_version TEXT NOT NULL DEFAULT 'plain-text-v1',
            chunk_policy_version TEXT NOT NULL DEFAULT 'fixed-char-v1',
            index_policy_version TEXT NOT NULL DEFAULT 'lexical-retrieval-v1',
            raw_sha256 TEXT NOT NULL DEFAULT '',
            normalized_sha256 TEXT NOT NULL DEFAULT '',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            block_count INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            warning_count INTEGER NOT NULL DEFAULT 0,
            error_code TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            started_at INTEGER NOT NULL,
            completed_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL
        )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_pipeline_events (
            id TEXT PRIMARY KEY,
            ingestion_run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL
        )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_knowledge_ingestion_user_updated
            ON knowledge_ingestion_runs(user_id, updated_at DESC)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_knowledge_ingestion_document
            ON knowledge_ingestion_runs(document_id, started_at DESC)""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_ingestion_idempotency
            ON knowledge_ingestion_runs(user_id, idempotency_key)
            WHERE idempotency_key != ''""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_pipeline_sequence
            ON knowledge_pipeline_events(ingestion_run_id, sequence)""")


def _knowledge_document_ir(conn: sqlite3.Connection) -> None:
    columns = _column_names(conn, "knowledge_documents")
    additions = (
        ("document_ir_version", "INTEGER NOT NULL DEFAULT 0"),
        ("parser_version", "TEXT NOT NULL DEFAULT ''"),
        ("parsed_block_count", "INTEGER NOT NULL DEFAULT 0"),
        ("normalized_text_sha256", "TEXT NOT NULL DEFAULT ''"),
    )
    for name, declaration in additions:
        if name not in columns:
            conn.execute(f"ALTER TABLE knowledge_documents ADD COLUMN {name} {declaration}")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_document_blocks (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            ingestion_run_id TEXT NOT NULL DEFAULT '',
            ordinal INTEGER NOT NULL,
            block_type TEXT NOT NULL,
            text TEXT NOT NULL,
            section_path_json TEXT NOT NULL DEFAULT '[]',
            source_location_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            char_count INTEGER NOT NULL DEFAULT 0,
            content_sha256 TEXT NOT NULL DEFAULT '',
            parser_version TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        )""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_blocks_document_ordinal
            ON knowledge_document_blocks(document_id, ordinal)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_knowledge_blocks_ingestion
            ON knowledge_document_blocks(ingestion_run_id, ordinal)""")


def _knowledge_structure_chunks(conn: sqlite3.Connection) -> None:
    document_columns = _column_names(conn, "knowledge_documents")
    document_additions = (
        ("active_chunk_version", "INTEGER NOT NULL DEFAULT 1"),
        ("chunk_policy_version", "TEXT NOT NULL DEFAULT 'fixed-char-v1'"),
        ("chunk_preset", "TEXT NOT NULL DEFAULT 'standard'"),
    )
    for name, declaration in document_additions:
        if name not in document_columns:
            conn.execute(f"ALTER TABLE knowledge_documents ADD COLUMN {name} {declaration}")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            content TEXT NOT NULL
        )""")
    chunk_columns = _column_names(conn, "knowledge_chunks")
    chunk_additions = (
        ("chunk_version", "INTEGER NOT NULL DEFAULT 1"),
        ("active", "INTEGER NOT NULL DEFAULT 1"),
        ("block_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("section_path_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("source_location_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("token_count", "INTEGER NOT NULL DEFAULT 0"),
        ("overlap_tokens", "INTEGER NOT NULL DEFAULT 0"),
        ("policy_version", "TEXT NOT NULL DEFAULT 'fixed-char-v1'"),
        ("preset", "TEXT NOT NULL DEFAULT 'standard'"),
        ("content_sha256", "TEXT NOT NULL DEFAULT ''"),
        ("created_at", "INTEGER NOT NULL DEFAULT 0"),
    )
    for name, declaration in chunk_additions:
        if name not in chunk_columns:
            conn.execute(f"ALTER TABLE knowledge_chunks ADD COLUMN {name} {declaration}")
    conn.execute("UPDATE knowledge_chunks SET token_count = length(content) WHERE token_count = 0")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_chunk_versions (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            policy_version TEXT NOT NULL,
            preset TEXT NOT NULL,
            status TEXT NOT NULL,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            created_by_user_id TEXT NOT NULL DEFAULT '',
            supersedes_version INTEGER NOT NULL DEFAULT 0,
            error_message TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            activated_at INTEGER NOT NULL DEFAULT 0
        )""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_chunk_version
            ON knowledge_chunk_versions(document_id, version)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_active
            ON knowledge_chunks(document_id, active, position)""")
    chunk_count_expression = "COALESCE(chunk_count, 0)" if "chunk_count" in document_columns else "0"
    conn.execute(f"""INSERT OR IGNORE INTO knowledge_chunk_versions
            (id, document_id, version, policy_version, preset, status, chunk_count,
             supersedes_version, created_at, activated_at)
            SELECT 'chunk_version_' || id, id, 1, chunk_policy_version, chunk_preset,
                   'active', {chunk_count_expression}, 0, created_at, created_at
            FROM knowledge_documents""")


def _knowledge_fts5_index(conn: sqlite3.Connection) -> None:
    backend = "fts5_trigram"
    try:
        conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
                USING fts5(
                    chunk_id UNINDEXED,
                    document_id UNINDEXED,
                    filename,
                    title,
                    body,
                    tags,
                    tokenize='trigram'
                )""")
    except sqlite3.OperationalError:
        backend = "fts5_unicode61"
        conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
                USING fts5(
                    chunk_id UNINDEXED,
                    document_id UNINDEXED,
                    filename,
                    title,
                    body,
                    tags,
                    tokenize='unicode61'
                )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_search_index_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            backend TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            indexed_chunk_count INTEGER NOT NULL DEFAULT 0,
            last_backfill_at INTEGER NOT NULL DEFAULT 0
        )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_retrieval_traces (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            project_space_id TEXT NOT NULL DEFAULT '',
            query_sha256 TEXT NOT NULL,
            backend TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            candidate_count INTEGER NOT NULL DEFAULT 0,
            selected_count INTEGER NOT NULL DEFAULT 0,
            fallback_reason TEXT NOT NULL DEFAULT '',
            candidate_summary_json TEXT NOT NULL DEFAULT '[]',
            duration_ms INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_knowledge_retrieval_trace_user
            ON knowledge_retrieval_traces(user_id, created_at DESC)""")
    conn.execute("DELETE FROM knowledge_chunks_fts")
    filename_expression = "knowledge_documents.filename" if "filename" in _column_names(conn, "knowledge_documents") else "''"
    conn.execute(f"""INSERT INTO knowledge_chunks_fts
            (chunk_id, document_id, filename, title, body, tags)
            SELECT knowledge_chunks.id, knowledge_chunks.document_id,
                   {filename_expression},
                   knowledge_chunks.section_path_json,
                   knowledge_chunks.content,
                   knowledge_chunks.preset || ' ' || knowledge_chunks.source_location_json
            FROM knowledge_chunks
            JOIN knowledge_documents ON knowledge_documents.id = knowledge_chunks.document_id
            WHERE knowledge_chunks.active = 1""")
    indexed = int(conn.execute("SELECT COUNT(*) FROM knowledge_chunks_fts").fetchone()[0])
    conn.execute("""INSERT INTO knowledge_search_index_state
            (id, backend, policy_version, indexed_chunk_count, last_backfill_at)
            VALUES (1, ?, 'fts5-bm25-v1', ?, 0)
            ON CONFLICT(id) DO UPDATE SET backend = excluded.backend,
                policy_version = excluded.policy_version,
                indexed_chunk_count = excluded.indexed_chunk_count""", (backend, indexed))


def _knowledge_vector_index(conn: sqlite3.Connection) -> None:
    document_columns = _column_names(conn, "knowledge_documents")
    additions = (
        ("active_embedding_model_version", "TEXT NOT NULL DEFAULT ''"),
        ("embedding_status", "TEXT NOT NULL DEFAULT 'disabled'"),
        ("embedding_updated_at", "INTEGER NOT NULL DEFAULT 0"),
    )
    for name, declaration in additions:
        if name not in document_columns:
            conn.execute(f"ALTER TABLE knowledge_documents ADD COLUMN {name} {declaration}")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_embedding_models (
            version TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            config_fingerprint TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            activated_at INTEGER NOT NULL DEFAULT 0
        )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_embedding_jobs (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            chunk_version INTEGER NOT NULL,
            model_version TEXT NOT NULL,
            requested_by_user_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            total_count INTEGER NOT NULL DEFAULT 0,
            reused_count INTEGER NOT NULL DEFAULT 0,
            succeeded_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            started_at INTEGER NOT NULL DEFAULT 0,
            completed_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL
        )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_knowledge_embedding_jobs_status
            ON knowledge_embedding_jobs(status, created_at)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_knowledge_embedding_jobs_document
            ON knowledge_embedding_jobs(document_id, created_at DESC)""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_embedding_jobs_pending
            ON knowledge_embedding_jobs(document_id, chunk_version, model_version)
            WHERE status IN ('queued', 'running')""")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_chunk_embeddings (
            id TEXT PRIMARY KEY,
            chunk_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            chunk_version INTEGER NOT NULL,
            model_version TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            vector_blob BLOB,
            status TEXT NOT NULL,
            error_message TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )""")
    conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_chunk_embedding
            ON knowledge_chunk_embeddings(chunk_id, model_version)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_knowledge_embedding_document_model
            ON knowledge_chunk_embeddings(document_id, chunk_version, model_version, status)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_knowledge_embedding_reuse
            ON knowledge_chunk_embeddings(document_id, model_version, content_sha256, status)""")


def _knowledge_configuration_and_retrieval_lab(conn: sqlite3.Connection) -> None:
    if "is_knowledge_admin" not in _column_names(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN is_knowledge_admin INTEGER NOT NULL DEFAULT 0")
    conn.execute("UPDATE users SET is_knowledge_admin = 1 WHERE is_admin = 1")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_processing_presets (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            parser_profile TEXT NOT NULL DEFAULT 'structure_preserving',
            chunk_config_json TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active',
            updated_by_user_id TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )""")
    defaults = (
        ("standard", "标准", "适合一般文档、说明和知识资料。", 600, 900, 120),
        ("long_document", "长文档", "减少长文档片段数量并保留更多上下文。", 900, 1400, 150),
        ("table_dense", "表格密集", "优先保持表格行边界，使用更紧凑片段。", 420, 700, 60),
    )
    for preset_id, label, description, target, maximum, overlap in defaults:
        config = (
            '{"target_tokens":%d,"max_tokens":%d,"overlap_tokens":%d}'
            % (target, maximum, overlap)
        )
        conn.execute(
            """INSERT OR IGNORE INTO knowledge_processing_presets
               (id, label, description, parser_profile, chunk_config_json,
                revision, status, created_at, updated_at)
               VALUES (?, ?, ?, 'structure_preserving', ?, 1, 'active', 0, 0)""",
            (preset_id, label, description, config),
        )
    conn.execute("""CREATE TABLE IF NOT EXISTS retrieval_lab_experiments (
            id TEXT PRIMARY KEY,
            actor_user_id TEXT NOT NULL,
            query_sha256 TEXT NOT NULL,
            left_policy_version TEXT NOT NULL,
            right_policy_version TEXT NOT NULL,
            project_space_id TEXT NOT NULL DEFAULT '',
            summary_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL
        )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_retrieval_lab_actor_created
            ON retrieval_lab_experiments(actor_user_id, created_at DESC)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS retrieval_policies (
            version TEXT PRIMARY KEY,
            config_json TEXT NOT NULL,
            status TEXT NOT NULL,
            parent_version TEXT NOT NULL DEFAULT '',
            changed_variable TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            experiment_json TEXT NOT NULL DEFAULT '{}',
            created_by_user_id TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            activated_at INTEGER NOT NULL DEFAULT 0
        )""")
    hybrid_config = (
        '{"limit":4,"max_excerpt_chars":900,"max_total_chars":2800,'
        '"neighbor_radius":1,"hybrid_enabled":true,"vector_min_score":0.72,'
        '"rrf_k":60,"candidate_limit":64,"rewrite_enabled":true}'
    )
    active = conn.execute(
        "SELECT version, activated_at FROM retrieval_policies WHERE status = 'active' ORDER BY activated_at DESC LIMIT 1"
    ).fetchone()
    if active and str(active[0]) != "hybrid-rrf-v1":
        conn.execute("UPDATE retrieval_policies SET status = 'stable' WHERE status = 'active'")
        conn.execute(
            """INSERT OR IGNORE INTO retrieval_policies
               (version, config_json, status, parent_version, changed_variable,
                evidence_json, created_at, activated_at)
               VALUES ('hybrid-rrf-v1', ?, 'active', ?, 'p51_6_baseline',
                       '{"source":"p51-6-fixed-evaluation"}', ?, ?)""",
            (hybrid_config, str(active[0]), int(active[1] or 0), int(active[1] or 0)),
        )
    elif not active:
        conn.execute(
            """INSERT OR IGNORE INTO retrieval_policies
               (version, config_json, status, changed_variable, evidence_json,
                created_at, activated_at)
               VALUES ('hybrid-rrf-v1', ?, 'active', 'p51_6_baseline',
                       '{"source":"p51-6-fixed-evaluation"}', 0, 0)""",
            (hybrid_config,),
        )


def _knowledge_history_migration_and_rollout(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_migration_batches (
            id TEXT PRIMARY KEY,
            actor_user_id TEXT NOT NULL,
            preset TEXT NOT NULL DEFAULT 'standard',
            status TEXT NOT NULL,
            total_count INTEGER NOT NULL DEFAULT 0,
            processed_count INTEGER NOT NULL DEFAULT 0,
            succeeded_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            rollout_percentage INTEGER NOT NULL DEFAULT 0,
            baseline_document_count INTEGER NOT NULL DEFAULT 0,
            baseline_acl_sha256 TEXT NOT NULL DEFAULT '',
            evaluation_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            started_at INTEGER NOT NULL DEFAULT 0,
            completed_at INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL
        )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_knowledge_migration_batch_status
            ON knowledge_migration_batches(status, created_at DESC)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_migration_items (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            status TEXT NOT NULL,
            source_chunk_version INTEGER NOT NULL,
            target_chunk_version INTEGER NOT NULL DEFAULT 0,
            source_chunk_count INTEGER NOT NULL DEFAULT 0,
            target_chunk_count INTEGER NOT NULL DEFAULT 0,
            parser_version TEXT NOT NULL DEFAULT '',
            chunk_policy_version TEXT NOT NULL DEFAULT '',
            normalized_sha256 TEXT NOT NULL DEFAULT '',
            error_code TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            UNIQUE(batch_id, document_id)
        )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_knowledge_migration_item_batch
            ON knowledge_migration_items(batch_id, status, document_id)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_migration_shadow_diffs (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            actor_user_id TEXT NOT NULL,
            query_sha256 TEXT NOT NULL,
            source_kind TEXT NOT NULL DEFAULT 'live_shadow',
            baseline_count INTEGER NOT NULL DEFAULT 0,
            candidate_count INTEGER NOT NULL DEFAULT 0,
            top_document_agreement INTEGER NOT NULL DEFAULT 0,
            document_overlap REAL NOT NULL DEFAULT 0,
            baseline_documents_json TEXT NOT NULL DEFAULT '[]',
            candidate_documents_json TEXT NOT NULL DEFAULT '[]',
            created_at INTEGER NOT NULL
        )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_knowledge_migration_shadow_batch
            ON knowledge_migration_shadow_diffs(batch_id, created_at DESC)""")


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "personal_accounts_and_security_events", _personal_accounts),
    Migration(2, "account_deletion_requests", _account_deletion_requests),
    Migration(3, "login_throttles", _login_throttles),
    Migration(4, "trial_invitations", _trial_invitations),
    Migration(5, "artifact_preview_contract", _artifact_preview_contract),
    Migration(6, "knowledge_ingestion_observability", _knowledge_ingestion_observability),
    Migration(7, "knowledge_document_ir", _knowledge_document_ir),
    Migration(8, "knowledge_structure_chunks", _knowledge_structure_chunks),
    Migration(9, "knowledge_fts5_index", _knowledge_fts5_index),
    Migration(10, "knowledge_vector_index", _knowledge_vector_index),
    Migration(11, "knowledge_configuration_and_retrieval_lab", _knowledge_configuration_and_retrieval_lab),
    Migration(12, "knowledge_history_migration_and_rollout", _knowledge_history_migration_and_rollout),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version


def ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at INTEGER NOT NULL
    )""")


def migration_status(conn: sqlite3.Connection) -> dict:
    ensure_migration_table(conn)
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    current = int(row[0] or 0)
    return {
        "current_version": current,
        "latest_version": LATEST_SCHEMA_VERSION,
        "pending": [migration.version for migration in MIGRATIONS if migration.version > current],
        "ready": current == LATEST_SCHEMA_VERSION,
    }


def apply_migrations(conn: sqlite3.Connection, now: Callable[[], int]) -> dict:
    ensure_migration_table(conn)
    applied = {int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations")}
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        savepoint = f"schema_migration_{migration.version}"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            migration.apply(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, now()),
            )
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception as exc:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise MigrationError(f"数据库迁移 {migration.version}（{migration.name}）失败") from exc
    return migration_status(conn)
