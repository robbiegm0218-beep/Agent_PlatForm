"""Deterministic governance helpers for retrieval-policy experiments."""
from __future__ import annotations

from server.knowledge_retrieval import RetrievalConfig


MIN_FEEDBACK_FOR_SUGGESTION = 20
MIN_REASON_COUNT = 3


def config_from_json(value: object, fallback: RetrievalConfig | None = None) -> RetrievalConfig:
    base = fallback or RetrievalConfig()
    raw = value if isinstance(value, dict) else {}
    limit = raw.get("limit", base.limit)
    max_excerpt_chars = raw.get("max_excerpt_chars", base.max_excerpt_chars)
    max_total_chars = raw.get("max_total_chars", base.max_total_chars)
    neighbor_radius = raw.get("neighbor_radius", base.neighbor_radius)
    if not all(isinstance(item, int) for item in (limit, max_excerpt_chars, max_total_chars, neighbor_radius)):
        raise ValueError("检索策略参数必须为整数")
    return RetrievalConfig(
        limit=min(max(limit, 1), 20),
        max_excerpt_chars=min(max(max_excerpt_chars, 100), 4000),
        max_total_chars=min(max(max_total_chars, 500), 16000),
        neighbor_radius=min(max(neighbor_radius, 0), 3),
    )


def config_as_dict(config: RetrievalConfig) -> dict:
    return {
        "limit": config.limit,
        "max_excerpt_chars": config.max_excerpt_chars,
        "max_total_chars": config.max_total_chars,
        "neighbor_radius": config.neighbor_radius,
    }


def suggestions_for_feedback(document_feedback_count: int, reason_counts: dict[str, int], config: RetrievalConfig) -> list[dict]:
    """Return at most one single-variable candidate based on sufficient evidence."""
    if document_feedback_count < MIN_FEEDBACK_FOR_SUGGESTION:
        return []
    missing = int(reason_counts.get("missing_evidence", 0))
    wrong_document = int(reason_counts.get("wrong_document", 0))
    if missing >= MIN_REASON_COUNT and missing >= wrong_document and config.limit < 20:
        target = config.limit + 1
        return [{
            "id": f"increase_limit_to_{target}",
            "changed_variable": "limit",
            "target_value": target,
            "title": "扩大候选资料数量",
            "rationale": "多次反馈显示缺少应有资料；只增加返回数量以验证是否改善覆盖。",
            "evidence": {"document_feedback_count": document_feedback_count, "reason_code": "missing_evidence", "count": missing},
            "risk": "可能增加不相关资料，需要通过离线质量门。",
        }]
    if wrong_document >= MIN_REASON_COUNT and config.limit > 1:
        target = config.limit - 1
        return [{
            "id": f"decrease_limit_to_{target}",
            "changed_variable": "limit",
            "target_value": target,
            "title": "收紧候选资料数量",
            "rationale": "多次反馈显示命中了不相关文档；只减少返回数量以验证是否降低误召回。",
            "evidence": {"document_feedback_count": document_feedback_count, "reason_code": "wrong_document", "count": wrong_document},
            "risk": "可能遗漏相关资料，需要通过离线质量门。",
        }]
    return []


def apply_suggestion(config: RetrievalConfig, suggestion: dict) -> RetrievalConfig:
    if suggestion.get("changed_variable") != "limit":
        raise ValueError("当前仅支持调整候选资料数量")
    return config_from_json({**config_as_dict(config), "limit": suggestion.get("target_value")}, config)
