"""Persistence and audit helpers for the P52 knowledge configuration read model."""
from __future__ import annotations

import json
from typing import Callable

from server.knowledge_configuration_contracts import KNOWLEDGE_RETRIEVAL_PROFILE_IDS
from server.knowledge_presets import PRESET_IDS


DEFAULT_KNOWLEDGE_PREFERENCES = {
    "retrieval_profile": "balanced",
    "default_scope": "auto",
    "default_upload_preset": "standard",
}
KNOWLEDGE_DEFAULT_SCOPES = ("auto", "general", "current_project")


class KnowledgeConfigurationService:
    def __init__(self, db_factory, now: Callable[[], int], new_id: Callable[[str], str]):
        self.db_factory = db_factory
        self.now = now
        self.new_id = new_id

    def preferences(self, user_id: str) -> dict:
        with self.db_factory() as conn:
            row = conn.execute(
                """SELECT retrieval_profile, default_scope, default_upload_preset,
                          version, created_at, updated_at
                   FROM user_knowledge_preferences WHERE user_id = ?""",
                (user_id,),
            ).fetchone()
        if not row:
            return {
                **DEFAULT_KNOWLEDGE_PREFERENCES,
                "version": 0,
                "created_at": 0,
                "updated_at": 0,
                "source": "code_boundary",
            }
        return {**dict(row), "source": "user_preference"}

    def update_preferences(self, user_id: str, payload: dict) -> tuple[dict, dict, dict]:
        if not isinstance(payload, dict):
            raise ValueError("知识库偏好必须是对象")
        allowed = set(DEFAULT_KNOWLEDGE_PREFERENCES)
        if not payload or not set(payload) <= allowed:
            raise ValueError("知识库偏好字段无效")
        before = self.preferences(user_id)
        values = {key: payload.get(key, before[key]) for key in allowed}
        if values["retrieval_profile"] not in KNOWLEDGE_RETRIEVAL_PROFILE_IDS:
            raise ValueError("用户检索预设无效")
        if values["default_scope"] not in KNOWLEDGE_DEFAULT_SCOPES:
            raise ValueError("默认资料范围无效")
        if values["default_upload_preset"] not in PRESET_IDS:
            raise ValueError("默认上传切分预设无效")
        with self.db_factory() as conn:
            available = conn.execute(
                "SELECT 1 FROM knowledge_processing_presets WHERE id = ? AND status = 'active'",
                (values["default_upload_preset"],),
            ).fetchone()
        if not available:
            raise ValueError("默认上传切分预设当前不可用")
        changed_fields = sorted(
            key for key in allowed if values[key] != before[key]
        )
        if not changed_fields:
            return before, before, {
                "before_version": f"user-preferences-v{before['version']}",
                "after_version": f"user-preferences-v{before['version']}",
                "source": "user_preference",
                "impact_scope": "future_user_defaults",
                "changed_fields": [],
            }
        timestamp = self.now()
        next_version = int(before["version"]) + 1
        with self.db_factory() as conn:
            conn.execute(
                """INSERT INTO user_knowledge_preferences
                   (user_id, retrieval_profile, default_scope, default_upload_preset,
                    version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     retrieval_profile = excluded.retrieval_profile,
                     default_scope = excluded.default_scope,
                     default_upload_preset = excluded.default_upload_preset,
                     version = excluded.version,
                     updated_at = excluded.updated_at""",
                (
                    user_id, values["retrieval_profile"], values["default_scope"],
                    values["default_upload_preset"], next_version, timestamp, timestamp,
                ),
            )
            change = self._record_event(
                conn,
                actor_user_id=user_id,
                scope_type="user",
                scope_id=user_id,
                configuration_area="user_preferences",
                changed_fields=changed_fields,
                before_version=f"user-preferences-v{before['version']}",
                after_version=f"user-preferences-v{next_version}",
                source="user_preference",
                impact_scope="future_user_defaults",
                created_at=timestamp,
            )
        return before, self.preferences(user_id), change

    def record_event(
        self,
        *,
        actor_user_id: str,
        scope_type: str,
        scope_id: str,
        configuration_area: str,
        changed_fields: list[str],
        before_version: str,
        after_version: str,
        source: str,
        impact_scope: str,
    ) -> dict:
        with self.db_factory() as conn:
            return self._record_event(
                conn,
                actor_user_id=actor_user_id,
                scope_type=scope_type,
                scope_id=scope_id,
                configuration_area=configuration_area,
                changed_fields=changed_fields,
                before_version=before_version,
                after_version=after_version,
                source=source,
                impact_scope=impact_scope,
                created_at=self.now(),
            )

    def _record_event(self, conn, **event) -> dict:
        fields = sorted(set(str(item) for item in event.pop("changed_fields") if item))
        event_id = self.new_id("knowledge_configuration_event")
        conn.execute(
            """INSERT INTO knowledge_configuration_events
               (id, actor_user_id, scope_type, scope_id, configuration_area,
                changed_fields_json, before_version, after_version, source,
                impact_scope, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id, event["actor_user_id"], event["scope_type"],
                event["scope_id"], event["configuration_area"],
                json.dumps(fields, ensure_ascii=False), event["before_version"],
                event["after_version"], event["source"], event["impact_scope"],
                event["created_at"],
            ),
        )
        return {
            "event_id": event_id,
            "before_version": event["before_version"],
            "after_version": event["after_version"],
            "source": event["source"],
            "impact_scope": event["impact_scope"],
            "changed_fields": fields,
        }
