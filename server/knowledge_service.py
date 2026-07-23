"""Knowledge read-model service; write migration follows in P41-2c/d."""
from __future__ import annotations


class KnowledgeService:
    def __init__(self, db_factory):
        self.db_factory = db_factory

    def list_visible(self, user_id: str):
        with self.db_factory() as conn:
            return conn.execute("""SELECT knowledge_documents.id, knowledge_documents.filename, knowledge_documents.mime_type,
                knowledge_documents.size_bytes, knowledge_documents.chunk_count, knowledge_documents.created_at,
                knowledge_documents.scope, knowledge_documents.project_space_id, knowledge_documents.upload_origin,
                knowledge_documents.created_by_user_id, thread_folders.name AS project_space_name
                FROM knowledge_documents LEFT JOIN thread_folders ON thread_folders.id = knowledge_documents.project_space_id
                WHERE (knowledge_documents.user_id = ? AND knowledge_documents.scope = 'general') OR
                (knowledge_documents.scope = 'project' AND EXISTS (SELECT 1 FROM space_members WHERE space_members.space_id = knowledge_documents.project_space_id AND space_members.user_id = ?))
                ORDER BY knowledge_documents.created_at DESC""", (user_id, user_id)).fetchall()

    def list_for_space(self, space_id: str):
        with self.db_factory() as conn:
            return conn.execute("""SELECT knowledge_documents.id, knowledge_documents.filename, knowledge_documents.mime_type,
                knowledge_documents.size_bytes, knowledge_documents.chunk_count, knowledge_documents.created_at,
                knowledge_documents.upload_origin, users.name AS author_name
                FROM knowledge_documents JOIN users ON users.id = knowledge_documents.created_by_user_id
                WHERE knowledge_documents.scope = 'project' AND knowledge_documents.project_space_id = ?
                ORDER BY knowledge_documents.created_at DESC""", (space_id,)).fetchall()

    def searchable_chunks(self, user_id: str, project_space_id: str = "", include_all_projects: bool = False):
        with self.db_factory() as conn:
            if project_space_id:
                return conn.execute("""SELECT knowledge_chunks.*, knowledge_documents.filename, knowledge_documents.scope, knowledge_documents.project_space_id
                    FROM knowledge_chunks JOIN knowledge_documents ON knowledge_documents.id = knowledge_chunks.document_id
                    WHERE (knowledge_documents.scope = 'general' AND knowledge_documents.user_id = ?) OR
                    (knowledge_documents.scope = 'project' AND knowledge_documents.project_space_id = ? AND
                    EXISTS (SELECT 1 FROM space_members WHERE space_members.space_id = ? AND space_members.user_id = ?))""",
                    (user_id, project_space_id, project_space_id, user_id)).fetchall()
            if include_all_projects:
                return conn.execute("""SELECT knowledge_chunks.*, knowledge_documents.filename, knowledge_documents.scope, knowledge_documents.project_space_id
                    FROM knowledge_chunks JOIN knowledge_documents ON knowledge_documents.id = knowledge_chunks.document_id
                    WHERE (knowledge_documents.scope = 'general' AND knowledge_documents.user_id = ?) OR
                    (knowledge_documents.scope = 'project' AND EXISTS
                        (SELECT 1 FROM space_members WHERE space_members.space_id = knowledge_documents.project_space_id
                         AND space_members.user_id = ?))""", (user_id, user_id)).fetchall()
            return conn.execute("""SELECT knowledge_chunks.*, knowledge_documents.filename, knowledge_documents.scope, knowledge_documents.project_space_id
                FROM knowledge_chunks JOIN knowledge_documents ON knowledge_documents.id = knowledge_chunks.document_id
                WHERE knowledge_documents.user_id = ? AND knowledge_documents.scope = 'general'""", (user_id,)).fetchall()

    def persist_upload(self, document, chunks):
        storage_path = document["storage_path"]
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(document.pop("raw"))
        with self.db_factory() as conn:
            values = tuple(str(document[key]) if key == "storage_path" else document[key] for key in ("id", "user_id", "filename", "storage_path", "mime_type", "content_hash", "size_bytes", "chunk_count", "created_at", "scope", "project_space_id", "upload_origin", "created_by_user_id"))
            conn.execute("""INSERT INTO knowledge_documents (id, user_id, filename, storage_path, mime_type, content_hash, size_bytes, chunk_count, created_at, scope, project_space_id, upload_origin, created_by_user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", values)
            conn.executemany("INSERT INTO knowledge_chunks (id, document_id, position, content) VALUES (?, ?, ?, ?)", chunks)

    def delete_document(self, document_id: str, user_id: str):
        with self.db_factory() as conn:
            row = conn.execute("""SELECT storage_path FROM knowledge_documents WHERE id = ? AND (user_id = ? OR
                (scope = 'project' AND EXISTS (SELECT 1 FROM thread_folders WHERE thread_folders.id = knowledge_documents.project_space_id AND thread_folders.user_id = ?)))""", (document_id, user_id, user_id)).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM knowledge_documents WHERE id = ?", (document_id,))
            return row["storage_path"]

    def delete_space_documents(self, space_id: str):
        with self.db_factory() as conn:
            rows = conn.execute("SELECT storage_path FROM knowledge_documents WHERE scope = 'project' AND project_space_id = ?", (space_id,)).fetchall()
            conn.execute("DELETE FROM knowledge_chunks WHERE document_id IN (SELECT id FROM knowledge_documents WHERE scope = 'project' AND project_space_id = ?)", (space_id,))
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
            return conn.execute("SELECT * FROM knowledge_documents WHERE id = ?", (document_id,)).fetchone()
