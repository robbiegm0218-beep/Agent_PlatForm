"""Project-space access, membership and mutation service."""
from __future__ import annotations


class SpaceService:
    def __init__(self, db_factory, now=None, new_id=None):
        self.db_factory = db_factory
        self.now = now
        self.new_id = new_id

    def get_accessible_space(self, space_id: str, user_id: str):
        with self.db_factory() as conn:
            return conn.execute("""SELECT thread_folders.*, space_members.role AS member_role FROM thread_folders
                LEFT JOIN space_members ON space_members.space_id = thread_folders.id AND space_members.user_id = ?
                WHERE thread_folders.id = ? AND thread_folders.section = 'project' AND
                (thread_folders.user_id = ? OR space_members.user_id = ?)""", (user_id, space_id, user_id, user_id)).fetchone()

    def list_accessible_spaces(self, user_id: str):
        with self.db_factory() as conn:
            return conn.execute("""SELECT thread_folders.*, space_members.role AS member_role FROM thread_folders
                LEFT JOIN space_members ON space_members.space_id = thread_folders.id AND space_members.user_id = ?
                WHERE thread_folders.user_id = ? OR space_members.user_id = ?
                ORDER BY sort_order ASC, created_at ASC, id ASC""", (user_id, user_id, user_id)).fetchall()

    def can_access_space(self, space_id: str, user_id: str) -> bool:
        return bool(self.get_accessible_space(space_id, user_id))

    def can_manage_members(self, space, user_id: str) -> bool:
        return bool(space and space["user_id"] == user_id and space["member_role"] == "owner")

    def get_owned_space(self, space_id: str, user_id: str):
        with self.db_factory() as conn:
            return conn.execute("SELECT * FROM thread_folders WHERE id = ? AND user_id = ? AND section = 'project'", (space_id, user_id)).fetchone()

    def create_space(self, user_id, name):
        with self.db_factory() as conn:
            space_id = self.new_id("folder")
            order = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM thread_folders WHERE user_id = ? AND section = 'project'", (user_id,)).fetchone()[0]
            conn.execute("INSERT INTO thread_folders (id, user_id, name, section, sort_order, created_at, updated_at) VALUES (?, ?, ?, 'project', ?, ?, ?)", (space_id, user_id, name[:80], order, self.now(), self.now()))
            conn.execute("INSERT INTO space_members (space_id, user_id, role, created_at) VALUES (?, ?, 'owner', ?)", (space_id, user_id, self.now()))
            return conn.execute("SELECT * FROM thread_folders WHERE id = ?", (space_id,)).fetchone()

    def update_space(self, space_id, user_id, name=None, position=None):
        with self.db_factory() as conn:
            space = conn.execute("SELECT * FROM thread_folders WHERE id = ? AND user_id = ? AND section = 'project'", (space_id, user_id)).fetchone()
            if not space:
                return None
            if name is not None:
                conn.execute("UPDATE thread_folders SET name = ?, updated_at = ? WHERE id = ?", (name[:80], self.now(), space_id))
            elif position is not None:
                rows = conn.execute("SELECT id FROM thread_folders WHERE user_id = ? AND section = 'project' ORDER BY sort_order, created_at, id", (user_id,)).fetchall()
                ids = [row["id"] for row in rows if row["id"] != space_id]; ids.insert(max(0, min(position, len(ids))), space_id)
                for order, identifier in enumerate(ids): conn.execute("UPDATE thread_folders SET sort_order = ?, updated_at = ? WHERE id = ?", (order, self.now(), identifier))
            return conn.execute("SELECT * FROM thread_folders WHERE id = ?", (space_id,)).fetchone()

    def invite_member(self, space_id: str, owner_id: str, email: str, role: str = "member"):
        if role != "member":
            return None, "invalid_role"
        with self.db_factory() as conn:
            space = conn.execute("SELECT id FROM thread_folders WHERE id = ? AND user_id = ? AND section = 'project'", (space_id, owner_id)).fetchone()
            if not space:
                return None, "space_not_found"
            existing = conn.execute("SELECT id FROM space_invitations WHERE space_id = ? AND email = ? AND status = 'pending'", (space_id, email)).fetchone()
            if existing:
                return None, "pending_exists"
            invitation_id = self.new_id("invite")
            invited_user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            status = "accepted" if invited_user else "pending"
            conn.execute("INSERT INTO space_invitations (id, space_id, email, role, status, invited_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (invitation_id, space_id, email, role, status, owner_id, self.now()))
            if invited_user:
                conn.execute("INSERT OR IGNORE INTO space_members (space_id, user_id, role, created_at) VALUES (?, ?, ?, ?)", (space_id, invited_user["id"], role, self.now()))
            return {"id": invitation_id, "email": email, "status": status, "role": role}, ""

    def accept_pending_invitations(self, conn, user_id: str, email: str) -> None:
        conn.execute("INSERT OR IGNORE INTO space_members (space_id, user_id, role, created_at) SELECT space_id, ?, role, ? FROM space_invitations WHERE email = ? AND status = 'pending'", (user_id, self.now(), email))
        conn.execute("UPDATE space_invitations SET status = 'accepted' WHERE email = ? AND status = 'pending'", (email,))

    def remove_member(self, space_id: str, owner_id: str, member_id: str) -> str:
        with self.db_factory() as conn:
            space = conn.execute("SELECT id FROM thread_folders WHERE id = ? AND user_id = ? AND section = 'project'", (space_id, owner_id)).fetchone()
            member = conn.execute("SELECT role FROM space_members WHERE space_id = ? AND user_id = ?", (space_id, member_id)).fetchone()
            if not space or not member:
                return "not_found"
            if member["role"] == "owner":
                return "owner"
            conn.execute("DELETE FROM space_members WHERE space_id = ? AND user_id = ?", (space_id, member_id))
            return "removed"

    def get_space_detail(self, space_id: str, user_id: str, parse_json):
        """Return every project-space read model after one membership check."""
        with self.db_factory() as conn:
            space = conn.execute("""SELECT thread_folders.*, space_members.role AS member_role FROM thread_folders
                LEFT JOIN space_members ON space_members.space_id = thread_folders.id AND space_members.user_id = ?
                WHERE thread_folders.id = ? AND thread_folders.section = 'project' AND
                (thread_folders.user_id = ? OR space_members.user_id = ?)""", (user_id, space_id, user_id, user_id)).fetchone()
            if not space:
                return None
            tasks = conn.execute("""SELECT threads.*, users.name AS author_name FROM threads JOIN users ON users.id = threads.user_id
                WHERE folder_id = ? ORDER BY updated_at DESC, id DESC""", (space_id,)).fetchall()
            artifacts = conn.execute("""SELECT artifacts.*, threads.title AS task_title, users.name AS author_name FROM artifacts
                JOIN runs ON runs.id = artifacts.run_id JOIN threads ON threads.id = runs.thread_id
                JOIN users ON users.id = threads.user_id WHERE threads.folder_id = ?
                ORDER BY artifacts.created_at DESC, artifacts.id DESC""", (space_id,)).fetchall()
            runs = conn.execute("""SELECT runs.id, runs.execution_context, threads.title FROM runs JOIN threads ON threads.id = runs.thread_id
                WHERE threads.folder_id = ? ORDER BY runs.started_at DESC, runs.id DESC""", (space_id,)).fetchall()
            web_events = conn.execute("""SELECT run_events.run_id, run_events.payload, threads.title FROM run_events
                JOIN runs ON runs.id = run_events.run_id JOIN threads ON threads.id = runs.thread_id
                WHERE threads.folder_id = ? AND run_events.type = 'tool_result' ORDER BY run_events.created_at DESC""", (space_id,)).fetchall()
            members = conn.execute("""SELECT users.id, users.name, users.email, space_members.role, space_members.created_at
                FROM space_members JOIN users ON users.id = space_members.user_id
                WHERE space_members.space_id = ? ORDER BY space_members.created_at ASC""", (space_id,)).fetchall()
            invitations = conn.execute("SELECT * FROM space_invitations WHERE space_id = ? ORDER BY created_at DESC", (space_id,)).fetchall()
            knowledge_documents = conn.execute("""SELECT knowledge_documents.id, knowledge_documents.filename, knowledge_documents.mime_type,
                knowledge_documents.size_bytes, knowledge_documents.chunk_count, knowledge_documents.created_at,
                knowledge_documents.upload_origin, users.name AS author_name FROM knowledge_documents
                JOIN users ON users.id = knowledge_documents.created_by_user_id
                WHERE knowledge_documents.scope = 'project' AND knowledge_documents.project_space_id = ?
                ORDER BY knowledge_documents.created_at DESC""", (space_id,)).fetchall()
            visible_document_ids = {row["id"] for row in conn.execute("""SELECT id FROM knowledge_documents
                WHERE (scope = 'general' AND user_id = ?) OR
                (scope = 'project' AND EXISTS (SELECT 1 FROM space_members
                    WHERE space_members.space_id = knowledge_documents.project_space_id AND space_members.user_id = ?))""",
                (user_id, user_id)).fetchall()}

        sources: list[dict] = []
        seen_sources: set[tuple[str, str]] = set()
        for run in runs:
            for reference in parse_json(run["execution_context"]).get("knowledge_refs", []):
                if not isinstance(reference, dict):
                    continue
                key = ("knowledge", f"{reference.get('document_id', '')}:{reference.get('position', '')}")
                if key in seen_sources:
                    continue
                seen_sources.add(key)
                if str(reference.get("document_id", "")) not in visible_document_ids:
                    sources.append({"kind": "knowledge", "title": "资料引用已隐藏", "redacted": True, "task_title": run["title"]})
                    continue
                sources.append({"kind": "knowledge", "title": str(reference.get("filename", "本地资料"))[:255], "excerpt": str(reference.get("excerpt", ""))[:320], "task_title": run["title"]})
        for event in web_events:
            for source in parse_json(event["payload"]).get("sources", []):
                if not isinstance(source, dict) or source.get("kind") != "web":
                    continue
                url = str(source.get("url", ""))
                key = ("web", url)
                if not url or key in seen_sources:
                    continue
                seen_sources.add(key)
                sources.append({"kind": "web", "title": str(source.get("title", "网页来源"))[:255], "url": url[:2048], "excerpt": str(source.get("excerpt", ""))[:320], "task_title": event["title"]})
        return {"space": space, "tasks": tasks, "artifacts": artifacts, "sources": sources,
                "knowledge_documents": knowledge_documents, "members": members, "invitations": invitations}
