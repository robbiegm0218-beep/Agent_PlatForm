"""Authentication domain service; HTTP concerns remain in app.py."""
from __future__ import annotations


class AuthService:
    def __init__(self, db_factory, now, new_id, verify_password, hash_password, ttl_seconds: int, space_service=None):
        self.db_factory = db_factory
        self.now = now
        self.new_id = new_id
        self.verify_password = verify_password
        self.hash_password = hash_password
        self.ttl_seconds = ttl_seconds
        self.space_service = space_service

    def current_user(self, token: str):
        if not token:
            return None
        with self.db_factory() as conn:
            return conn.execute("""SELECT users.* FROM users JOIN sessions ON sessions.user_id = users.id
                WHERE sessions.token = ? AND (sessions.expires_at = 0 OR sessions.expires_at > ?)""", (token, self.now())).fetchone()

    def login(self, email: str, password: str):
        with self.db_factory() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if not user or not self.verify_password(password, user["password_hash"]):
                return None, ""
            if self.space_service:
                self.space_service.accept_pending_invitations(conn, user["id"], email)
            token = self.new_id("session")
            if not user["password_hash"].startswith("pbkdf2_sha256$"):
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (self.hash_password(password), user["id"]))
            conn.execute("INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)", (token, user["id"], self.now(), self.now() + self.ttl_seconds * 1_000_000_000))
            return user, token

    def logout(self, token: str) -> None:
        with self.db_factory() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def logout_all(self, user_id: str) -> None:
        with self.db_factory() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
