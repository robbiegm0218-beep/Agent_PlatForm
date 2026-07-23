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


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "personal_accounts_and_security_events", _personal_accounts),
    Migration(2, "account_deletion_requests", _account_deletion_requests),
    Migration(3, "login_throttles", _login_throttles),
    Migration(4, "trial_invitations", _trial_invitations),
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
