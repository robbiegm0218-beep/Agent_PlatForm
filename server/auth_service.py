"""Authentication domain service; HTTP concerns remain in app.py."""
from __future__ import annotations

import hashlib
import json
import secrets


def validate_new_password(password: str) -> str:
    if len(password) < 10:
        return "新密码至少需要 10 个字符"
    if len(password) > 256:
        return "新密码过长"
    if password.isspace():
        return "新密码不能只包含空白字符"
    return ""


class AuthService:
    def __init__(self, db_factory, now, new_id, verify_password, hash_password, ttl_seconds: int, space_service=None):
        self.db_factory = db_factory
        self.now = now
        self.new_id = new_id
        self.verify_password = verify_password
        self.hash_password = hash_password
        self.ttl_seconds = ttl_seconds
        self.space_service = space_service

    def _event(self, conn, event_type: str, outcome: str, user_id: str = "", detail: dict | None = None) -> None:
        conn.execute(
            "INSERT INTO security_events (id, user_id, event_type, outcome, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (self.new_id("security"), user_id, event_type, outcome, json.dumps(detail or {}, ensure_ascii=False), self.now()),
        )

    @staticmethod
    def _email_fingerprint(email: str) -> str:
        return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]

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
                self._event(conn, "login", "failed", user["id"] if user else "", {"email_hash": self._email_fingerprint(email)})
                return None, ""
            if self.space_service:
                self.space_service.accept_pending_invitations(conn, user["id"], email)
            token = self.new_id("session")
            if not user["password_hash"].startswith("pbkdf2_sha256$"):
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (self.hash_password(password), user["id"]))
            conn.execute("INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)", (token, user["id"], self.now(), self.now() + self.ttl_seconds * 1_000_000_000))
            self._event(conn, "login", "succeeded", user["id"])
            return user, token

    def logout(self, token: str) -> None:
        with self.db_factory() as conn:
            session = conn.execute("SELECT user_id FROM sessions WHERE token = ?", (token,)).fetchone()
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            if session:
                self._event(conn, "logout", "succeeded", session["user_id"])

    def logout_all(self, user_id: str) -> None:
        with self.db_factory() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            self._event(conn, "sessions_revoked", "succeeded", user_id)

    def change_password(self, user_id: str, current_password: str, new_password: str) -> str:
        validation_error = validate_new_password(new_password)
        if validation_error:
            return validation_error
        with self.db_factory() as conn:
            user = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user or not self.verify_password(current_password, user["password_hash"]):
                self._event(conn, "password_change", "failed", user_id, {"reason": "current_password_invalid"})
                return "当前密码不正确"
            if self.verify_password(new_password, user["password_hash"]):
                return "新密码不能与当前密码相同"
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (self.hash_password(new_password), user_id))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            self._event(conn, "password_change", "succeeded", user_id)
        return ""

    def create_password_reset(self, email: str, ttl_seconds: int = 1800) -> str | None:
        with self.db_factory() as conn:
            user = conn.execute("SELECT id FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
            if not user:
                self._event(conn, "password_reset_requested", "ignored", "", {"email_hash": self._email_fingerprint(email)})
                return None
            current = self.now()
            conn.execute("UPDATE password_reset_tokens SET used_at = ? WHERE user_id = ? AND used_at = 0", (current, user["id"]))
            token = secrets.token_urlsafe(32)
            conn.execute(
                """INSERT INTO password_reset_tokens
                   (id, user_id, token_hash, expires_at, used_at, created_at)
                   VALUES (?, ?, ?, ?, 0, ?)""",
                (self.new_id("reset"), user["id"], hashlib.sha256(token.encode("utf-8")).hexdigest(), current + ttl_seconds * 1_000_000_000, current),
            )
            self._event(conn, "password_reset_requested", "succeeded", user["id"])
            return token

    def reset_password(self, token: str, new_password: str) -> str:
        validation_error = validate_new_password(new_password)
        if validation_error:
            return validation_error
        token_hash = hashlib.sha256(token.strip().encode("utf-8")).hexdigest()
        with self.db_factory() as conn:
            current = self.now()
            record = conn.execute(
                """SELECT id, user_id FROM password_reset_tokens
                   WHERE token_hash = ? AND used_at = 0 AND expires_at > ?""",
                (token_hash, current),
            ).fetchone()
            if not record:
                self._event(conn, "password_reset", "failed", "", {"reason": "invalid_or_expired_token"})
                return "重置凭证无效或已过期"
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (self.hash_password(new_password), record["user_id"]))
            conn.execute("UPDATE password_reset_tokens SET used_at = ? WHERE id = ?", (current, record["id"]))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (record["user_id"],))
            self._event(conn, "password_reset", "succeeded", record["user_id"])
        return ""

    def security_events(self, user_id: str, limit: int = 20):
        with self.db_factory() as conn:
            return conn.execute(
                """SELECT id, event_type, outcome, detail_json, created_at FROM security_events
                   WHERE user_id = ? OR user_id = '' ORDER BY created_at DESC, id DESC LIMIT ?""",
                (user_id, max(1, min(limit, 100))),
            ).fetchall()
