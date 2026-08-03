"""Content-safe contracts for the P52 knowledge configuration center.

P52-0 freezes the product contract without wiring it into production reads or
writes. Later phases may expose these snapshots through additive APIs only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from server.knowledge_retrieval import RetrievalConfig


KNOWLEDGE_CONFIGURATION_SCHEMA_VERSION = 1
KNOWLEDGE_CONFIGURATION_ROLES = (
    "user",
    "knowledge_admin",
    "platform_admin",
)
KNOWLEDGE_CONFIGURATION_SURFACES = (
    "ui",
    "partial_ui",
    "api",
    "environment",
    "fixed_read_only",
)
KNOWLEDGE_CONFIGURATION_SOURCES = (
    "request_override",
    "user_preference",
    "processing_preset",
    "retrieval_policy",
    "runtime_status",
    "environment",
    "code_boundary",
)
KNOWLEDGE_RETRIEVAL_PROFILE_IDS = ("precise", "balanced", "high_recall")

_FORBIDDEN_KEY_MARKERS = (
    "api_key",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "base_url",
    "endpoint_url",
    "storage_path",
    "raw_content",
    "query_text",
    "knowledge_text",
)

RETRIEVAL_POLICY_RANGES = {
    "limit": (1, 20),
    "max_excerpt_chars": (100, 4000),
    "max_total_chars": (500, 16000),
    "neighbor_radius": (0, 3),
    "vector_min_score": (0.5, 0.95),
    "rrf_k": (10, 200),
    "candidate_limit": (8, 200),
}

PROCESSING_PRESET_DEFAULTS = {
    "standard": {
        "parser_profile": "structure_preserving",
        "target_tokens": 600,
        "max_tokens": 900,
        "overlap_tokens": 120,
    },
    "long_document": {
        "parser_profile": "structure_preserving",
        "target_tokens": 900,
        "max_tokens": 1400,
        "overlap_tokens": 150,
    },
    "table_dense": {
        "parser_profile": "structure_preserving",
        "target_tokens": 420,
        "max_tokens": 700,
        "overlap_tokens": 60,
    },
}


def _assert_content_safe(value: object, path: str = "snapshot") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            forbidden = any(marker in normalized for marker in _FORBIDDEN_KEY_MARKERS)
            safe_assertion = normalized.endswith("_exposed") and item is False
            if forbidden and not safe_assertion:
                raise ValueError(f"配置快照不能包含敏感字段：{path}.{key}")
            _assert_content_safe(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_content_safe(item, f"{path}[{index}]")


@dataclass(frozen=True)
class ConfigurationCapability:
    capability_id: str
    area: str
    label: str
    surfaces: tuple[str, ...]
    readable_roles: tuple[str, ...]
    writable_roles: tuple[str, ...]
    source: str
    effect_scope: str
    fields: tuple[str, ...]
    note: str = ""

    def __post_init__(self) -> None:
        if not self.capability_id.strip() or not self.area.strip() or not self.label.strip():
            raise ValueError("配置能力 ID、区域和名称不能为空")
        if not self.surfaces or not set(self.surfaces) <= set(KNOWLEDGE_CONFIGURATION_SURFACES):
            raise ValueError("配置能力入口无效")
        if not set(self.readable_roles) <= set(KNOWLEDGE_CONFIGURATION_ROLES):
            raise ValueError("配置能力读取角色无效")
        if not set(self.writable_roles) <= set(self.readable_roles):
            raise ValueError("配置能力写入角色必须具备读取权限")
        if self.source not in KNOWLEDGE_CONFIGURATION_SOURCES:
            raise ValueError("配置来源无效")
        if not self.effect_scope.strip() or not self.fields:
            raise ValueError("配置能力必须声明影响范围和字段")
        _assert_content_safe(asdict(self), self.capability_id)


@dataclass(frozen=True)
class KnowledgeConfigurationSnapshot:
    role: str
    capabilities: tuple[ConfigurationCapability, ...]
    user_preferences: dict[str, Any]
    processing: dict[str, Any]
    retrieval: dict[str, Any]
    index: dict[str, Any]
    migrations: dict[str, Any]
    security: dict[str, Any]
    schema_version: int = KNOWLEDGE_CONFIGURATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != KNOWLEDGE_CONFIGURATION_SCHEMA_VERSION:
            raise ValueError("知识库配置快照版本不受支持")
        if self.role not in KNOWLEDGE_CONFIGURATION_ROLES:
            raise ValueError("知识库配置角色无效")
        _assert_content_safe(asdict(self))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def capability_matrix() -> tuple[ConfigurationCapability, ...]:
    all_roles = KNOWLEDGE_CONFIGURATION_ROLES
    admin_roles = ("knowledge_admin", "platform_admin")
    platform_only = ("platform_admin",)
    return (
        ConfigurationCapability(
            "conversation_sources", "user", "对话资料来源",
            ("ui", "api"), all_roles, all_roles, "request_override", "run",
            ("source_mode", "knowledge_mode", "file_mode"),
        ),
        ConfigurationCapability(
            "knowledge_scope", "user", "通用库与项目范围",
            ("ui", "api"), all_roles, all_roles, "request_override", "document_and_run",
            ("scope", "project_space_id", "include_all_projects"),
        ),
        ConfigurationCapability(
            "user_retrieval_profile", "user", "用户检索预设",
            ("ui", "api"), all_roles, all_roles, "user_preference", "future_user_defaults_and_run",
            ("retrieval_profile",), "默认值约束后续 Run；请求覆盖只影响当前 Run。",
        ),
        ConfigurationCapability(
            "upload_chunk_preset", "processing", "上传默认切分预设",
            ("ui", "api"), all_roles, all_roles, "user_preference", "document_version",
            ("chunk_preset",), "用户默认值用于后续上传；上传弹窗可做本次覆盖。",
        ),
        ConfigurationCapability(
            "processing_presets", "processing", "知识处理预设",
            ("ui", "api"), all_roles, admin_roles, "processing_preset", "future_document_versions",
            ("parser_profile", "target_tokens", "max_tokens", "overlap_tokens"),
            "配置中心支持解析模式和 Token 切分边界的修订治理。",
        ),
        ConfigurationCapability(
            "document_rechunk", "processing", "文档重新切分与回滚",
            ("ui", "api"), all_roles, all_roles, "processing_preset", "document_version",
            ("preset", "chunk_version"),
        ),
        ConfigurationCapability(
            "retrieval_policy", "retrieval", "全局检索策略",
            ("ui", "api"), platform_only, platform_only, "retrieval_policy", "global_candidate",
            tuple((*RETRIEVAL_POLICY_RANGES.keys(), "hybrid_enabled", "rewrite_enabled")),
            "配置中心创建候选；评测通过后才能发布或回滚。",
        ),
        ConfigurationCapability(
            "retrieval_lab", "retrieval", "双策略检索实验",
            ("ui", "api"), platform_only, platform_only, "retrieval_policy", "offline_experiment",
            ("left_version", "right_version", "project_space_id", "include_all_projects"),
        ),
        ConfigurationCapability(
            "embedding_runtime", "index", "Embedding 运行配置",
            ("environment",), platform_only, (), "environment", "process_restart",
            ("provider", "model", "dimensions", "timeout_seconds", "configured"),
            "服务地址和密钥不进入配置快照。",
        ),
        ConfigurationCapability(
            "embedding_jobs", "index", "向量索引任务",
            ("ui", "api"), platform_only, platform_only, "runtime_status", "background_jobs",
            ("rebuild", "process_next", "model_version"),
        ),
        ConfigurationCapability(
            "historical_migration", "migration", "历史资料迁移与灰度",
            ("ui", "api"), platform_only, platform_only, "processing_preset", "migration_batch",
            ("preset", "limit", "rollout_percentage", "rollback"),
            "单活动批次按暂存、Shadow 门禁、灰度、全量与回滚状态推进；失败项需显式重试。",
        ),
        ConfigurationCapability(
            "safety_limits", "security", "知识文件安全限制",
            ("environment", "fixed_read_only"), platform_only, (), "environment", "process_restart",
            ("upload_bytes", "archive_files", "archive_bytes", "extracted_chars", "pdf_pages"),
        ),
        ConfigurationCapability(
            "fts_field_weights", "retrieval", "FTS/BM25 字段权重",
            ("fixed_read_only",), platform_only, (), "code_boundary", "global_fixed",
            ("filename_weight", "heading_weight", "content_weight", "tag_weight"),
        ),
        ConfigurationCapability(
            "ocr_and_table_runtime", "processing", "OCR 与表格解析能力",
            ("fixed_read_only",), all_roles, (), "code_boundary", "runtime_capability",
            ("ocr_engine", "ocr_languages", "table_parser"),
        ),
    )


def resolve_retrieval_profile(profile_id: str, base: RetrievalConfig | None = None) -> RetrievalConfig:
    """Resolve a bounded P52 user profile without mutating the active policy."""
    active = base or RetrievalConfig()
    if profile_id not in KNOWLEDGE_RETRIEVAL_PROFILE_IDS:
        raise ValueError("用户检索预设无效")
    if profile_id == "balanced":
        return active
    if profile_id == "precise":
        return RetrievalConfig(
            limit=min(active.limit, 3),
            max_excerpt_chars=min(active.max_excerpt_chars, 700),
            max_total_chars=min(active.max_total_chars, 2200),
            neighbor_radius=0,
            hybrid_enabled=active.hybrid_enabled,
            vector_min_score=min(0.95, max(active.vector_min_score, 0.78)),
            rrf_k=active.rrf_k,
            candidate_limit=max(8, min(active.candidate_limit, 32)),
            rewrite_enabled=False,
        )
    return RetrievalConfig(
        limit=min(8, max(active.limit, 6)),
        max_excerpt_chars=min(4000, max(active.max_excerpt_chars, 1100)),
        max_total_chars=min(16000, max(active.max_total_chars, 4200)),
        neighbor_radius=min(2, max(active.neighbor_radius, 1)),
        hybrid_enabled=active.hybrid_enabled,
        vector_min_score=active.vector_min_score,
        rrf_k=active.rrf_k,
        candidate_limit=min(200, max(active.candidate_limit, 96)),
        rewrite_enabled=active.rewrite_enabled,
    )


def configuration_contract_snapshot() -> dict[str, Any]:
    baseline = RetrievalConfig()
    profiles = {
        profile_id: asdict(resolve_retrieval_profile(profile_id, baseline))
        for profile_id in KNOWLEDGE_RETRIEVAL_PROFILE_IDS
    }
    snapshot = {
        "schema_version": KNOWLEDGE_CONFIGURATION_SCHEMA_VERSION,
        "roles": list(KNOWLEDGE_CONFIGURATION_ROLES),
        "surfaces": list(KNOWLEDGE_CONFIGURATION_SURFACES),
        "sources": list(KNOWLEDGE_CONFIGURATION_SOURCES),
        "capabilities": [asdict(item) for item in capability_matrix()],
        "processing_preset_defaults": PROCESSING_PRESET_DEFAULTS,
        "retrieval_policy_ranges": RETRIEVAL_POLICY_RANGES,
        "retrieval_policy_baseline": asdict(baseline),
        "user_retrieval_profiles": profiles,
        "content_safety": {
            "secret_values_exposed": False,
            "query_or_knowledge_content_exposed": False,
            "absolute_paths_exposed": False,
        },
    }
    _assert_content_safe(snapshot)
    return json.loads(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
