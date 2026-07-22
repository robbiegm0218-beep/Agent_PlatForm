#!/usr/bin/env python3
"""Execute already-due personal account deletions through an explicit local command.

The HTTP API only schedules or cancels a request. This command defaults to a
dry run and requires an explicit confirmation before it deletes anything.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import time
from pathlib import Path


def due_account_ids(conn: sqlite3.Connection, current_ns: int) -> list[str]:
    return [str(row[0]) for row in conn.execute(
        "SELECT user_id FROM account_deletion_requests WHERE status = 'scheduled' AND scheduled_for <= ? ORDER BY scheduled_for, user_id",
        (current_ns,),
    )]


def _safe_remove(path: Path, root: Path) -> None:
    if path.exists() and path.resolve().is_relative_to(root.resolve()):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def _shared_owned_spaces(conn: sqlite3.Connection, user_id: str) -> list[str]:
    rows = conn.execute("""SELECT thread_folders.id FROM thread_folders
        JOIN space_members ON space_members.space_id = thread_folders.id AND space_members.user_id != ?
        WHERE thread_folders.user_id = ? AND thread_folders.section = 'project'""", (user_id, user_id)).fetchall()
    return [str(row[0]) for row in rows]


def delete_due_accounts(database: Path, data_dir: Path, *, execute: bool = False, current_ns: int | None = None) -> dict:
    """Return a deletion plan, or execute it when explicitly requested.

    Shared project spaces owned by the account are intentionally blocked: their
    ownership must be resolved before a personal account can be deleted.
    """
    current_ns = current_ns if current_ns is not None else time.time_ns()
    report = {"dry_run": not execute, "planned": [], "deleted": [], "blocked": []}
    pending_file_removals: list[tuple[Path, Path]] = []
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        for user_id in due_account_ids(conn, current_ns):
            shared_spaces = _shared_owned_spaces(conn, user_id)
            if shared_spaces:
                report["blocked"].append({"user_id": user_id, "reason": "owned_shared_project_space", "space_ids": shared_spaces})
                continue
            artifacts = conn.execute("SELECT storage_path FROM artifacts WHERE user_id = ?", (user_id,)).fetchall()
            documents = conn.execute("SELECT id, storage_path FROM knowledge_documents WHERE user_id = ? OR created_by_user_id = ?", (user_id, user_id)).fetchall()
            thread_ids = [row[0] for row in conn.execute("SELECT id FROM threads WHERE user_id = ?", (user_id,))]
            run_ids = [row[0] for row in conn.execute("SELECT id FROM runs WHERE thread_id IN (SELECT id FROM threads WHERE user_id = ?)", (user_id,))]
            owned_spaces = [row[0] for row in conn.execute("SELECT id FROM thread_folders WHERE user_id = ? AND section = 'project'", (user_id,))]
            document_ids = [row["id"] for row in documents]
            placeholders = lambda items: ",".join("?" for _ in items)
            if run_ids:
                marks = placeholders(run_ids)
                conn.execute(f"DELETE FROM run_events WHERE run_id IN ({marks})", run_ids)
                conn.execute(f"DELETE FROM run_steps WHERE run_id IN ({marks})", run_ids)
                conn.execute(f"DELETE FROM run_confirmations WHERE run_id IN ({marks})", run_ids)
                conn.execute(f"DELETE FROM run_approval_requests WHERE run_id IN ({marks})", run_ids)
                conn.execute(f"DELETE FROM memory_usage WHERE run_id IN ({marks})", run_ids)
                conn.execute(f"DELETE FROM run_feedback WHERE run_id IN ({marks})", run_ids)
                conn.execute(f"DELETE FROM citation_feedback_items WHERE run_id IN ({marks})", run_ids)
            if document_ids:
                marks = placeholders(document_ids)
                conn.execute(f"DELETE FROM knowledge_chunks WHERE document_id IN ({marks})", document_ids)
                conn.execute(f"DELETE FROM citation_feedback_items WHERE document_id IN ({marks})", document_ids)
                conn.execute(f"DELETE FROM knowledge_documents WHERE id IN ({marks})", document_ids)
            conn.execute("DELETE FROM messages WHERE thread_id IN (SELECT id FROM threads WHERE user_id = ?)", (user_id,))
            conn.execute("DELETE FROM runs WHERE thread_id IN (SELECT id FROM threads WHERE user_id = ?)", (user_id,))
            conn.execute("DELETE FROM threads WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM run_feedback WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM citation_feedback_items WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM artifacts WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM manual_tool_invocations WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM user_enabled_skills WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM retrieval_policy_events WHERE actor_user_id = ?", (user_id,))
            conn.execute("DELETE FROM retrieval_policies WHERE created_by_user_id = ?", (user_id,))
            conn.execute("DELETE FROM space_members WHERE user_id = ?", (user_id,))
            if owned_spaces:
                marks = placeholders(owned_spaces)
                conn.execute(f"DELETE FROM space_invitations WHERE space_id IN ({marks})", owned_spaces)
                conn.execute(f"DELETE FROM thread_folders WHERE id IN ({marks})", owned_spaces)
            conn.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM security_events WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM account_deletion_requests WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            pending_file_removals.extend((Path(row["storage_path"]), data_dir / "artifacts") for row in artifacts)
            pending_file_removals.extend((Path(row["storage_path"]), data_dir / "knowledge") for row in documents)
            summary = {"user_id": user_id, "threads": len(thread_ids), "runs": len(run_ids), "documents": len(documents), "artifacts": len(artifacts)}
            report["deleted" if execute else "planned"].append(summary)
        if not execute:
            conn.rollback()
            return report
    for path, root in pending_file_removals:
        _safe_remove(path, root)
    return report


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="执行到期的个人账号删除申请（默认仅预览）")
    parser.add_argument("--database", type=Path, default=root / "agent_platform.db")
    parser.add_argument("--data-dir", type=Path, default=root / "data")
    parser.add_argument("--execute", action="store_true", help="实际执行删除")
    parser.add_argument("--confirmation", default="", help="执行时必须为 DELETE_DUE_ACCOUNTS")
    args = parser.parse_args()
    if args.execute and args.confirmation != "DELETE_DUE_ACCOUNTS":
        parser.error("实际执行必须提供 --confirmation DELETE_DUE_ACCOUNTS")
    print(delete_due_accounts(args.database, args.data_dir, execute=args.execute))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
