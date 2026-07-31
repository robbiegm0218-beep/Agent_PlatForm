"""Governed knowledge parsing/chunking presets shared by upload and rechunk."""
from __future__ import annotations

import json

from server.knowledge_pipeline_contracts import ChunkPolicy


PRESET_IDS = ("standard", "long_document", "table_dense")
PARSER_PROFILES = ("structure_preserving", "auto")


class KnowledgePresetService:
    def __init__(self, db_factory, now):
        self.db_factory = db_factory
        self.now = now

    def list(self) -> list[dict]:
        with self.db_factory() as conn:
            rows = conn.execute(
                """SELECT id, label, description, parser_profile, chunk_config_json,
                          revision, status, updated_by_user_id, updated_at
                   FROM knowledge_processing_presets
                   WHERE status = 'active'
                   ORDER BY CASE id WHEN 'standard' THEN 1 WHEN 'long_document' THEN 2 ELSE 3 END"""
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["chunk_config"] = json.loads(item.pop("chunk_config_json"))
            result.append(item)
        return result

    def policy(self, preset_id: str) -> tuple[ChunkPolicy, dict]:
        with self.db_factory() as conn:
            row = conn.execute(
                """SELECT id, label, description, parser_profile, chunk_config_json,
                          revision, status, updated_by_user_id, updated_at
                   FROM knowledge_processing_presets WHERE id = ? AND status = 'active'""",
                (preset_id,),
            ).fetchone()
        if not row:
            raise ValueError("切分预设无效")
        item = dict(row)
        config = json.loads(item.pop("chunk_config_json"))
        return ChunkPolicy(
            version=f"structure-token-v1:{preset_id}:r{int(item['revision'])}",
            preset=preset_id,
            target_tokens=int(config["target_tokens"]),
            max_tokens=int(config["max_tokens"]),
            overlap_tokens=int(config["overlap_tokens"]),
        ), {**item, "chunk_config": config}

    def update(self, preset_id: str, payload: dict, actor_user_id: str) -> dict:
        if preset_id not in PRESET_IDS:
            raise ValueError("只能配置平台提供的三种知识处理预设")
        parser_profile = str(payload.get("parser_profile", "")).strip()
        if parser_profile not in PARSER_PROFILES:
            raise ValueError("解析预设无效")
        config = payload.get("chunk_config")
        if not isinstance(config, dict):
            raise ValueError("切分配置必须是对象")
        allowed = {"target_tokens", "max_tokens", "overlap_tokens"}
        if set(config) != allowed or not all(isinstance(config[key], int) for key in allowed):
            raise ValueError("切分配置字段无效")
        target = config["target_tokens"]
        maximum = config["max_tokens"]
        overlap = config["overlap_tokens"]
        if not 200 <= target <= 1800:
            raise ValueError("目标 Token 必须在 200 到 1800 之间")
        if not target <= maximum <= 2400:
            raise ValueError("最大 Token 必须不小于目标值且不超过 2400")
        if not 0 <= overlap < target or overlap > 400:
            raise ValueError("重叠 Token 必须小于目标值且不超过 400")
        timestamp = self.now()
        with self.db_factory() as conn:
            current = conn.execute(
                "SELECT revision FROM knowledge_processing_presets WHERE id = ?",
                (preset_id,),
            ).fetchone()
            if not current:
                raise ValueError("知识处理预设不存在")
            revision = int(current[0]) + 1
            conn.execute(
                """UPDATE knowledge_processing_presets
                   SET parser_profile = ?, chunk_config_json = ?, revision = ?,
                       updated_by_user_id = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    parser_profile,
                    json.dumps(config, ensure_ascii=False, sort_keys=True),
                    revision, actor_user_id, timestamp, preset_id,
                ),
            )
        _, item = self.policy(preset_id)
        return item
