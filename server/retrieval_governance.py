"""Deterministic governance helpers for retrieval-policy experiments."""
from __future__ import annotations

from server.knowledge_retrieval import RetrievalConfig


# Personal hosted pilot: the operator explicitly accepted 12 document-level
# evaluations as the observation threshold. A candidate still needs a
# classified issue signal and must pass offline evaluation before publish.
MIN_FEEDBACK_FOR_SUGGESTION = 12
# The personal-hosted pilot operator approved one explicit, classified issue as
# enough to create an offline-only hypothesis. It never changes the active
# policy automatically: candidate creation, evaluation, and publish stay
# separate administrator actions.
MIN_REASON_COUNT = 1


def config_from_json(value: object, fallback: RetrievalConfig | None = None, *, strict: bool = False) -> RetrievalConfig:
    base = fallback or RetrievalConfig()
    raw = value if isinstance(value, dict) else {}
    limit = raw.get("limit", base.limit)
    max_excerpt_chars = raw.get("max_excerpt_chars", base.max_excerpt_chars)
    max_total_chars = raw.get("max_total_chars", base.max_total_chars)
    neighbor_radius = raw.get("neighbor_radius", base.neighbor_radius)
    hybrid_enabled = raw.get("hybrid_enabled", base.hybrid_enabled)
    vector_min_score = raw.get("vector_min_score", base.vector_min_score)
    rrf_k = raw.get("rrf_k", base.rrf_k)
    candidate_limit = raw.get("candidate_limit", base.candidate_limit)
    rewrite_enabled = raw.get("rewrite_enabled", base.rewrite_enabled)
    if not all(isinstance(item, int) for item in (limit, max_excerpt_chars, max_total_chars, neighbor_radius)):
        raise ValueError("检索策略参数必须为整数")
    if not isinstance(hybrid_enabled, bool) or not isinstance(rewrite_enabled, bool):
        raise ValueError("混合检索和查询改写开关必须为布尔值")
    if not isinstance(vector_min_score, (int, float)) or isinstance(vector_min_score, bool):
        raise ValueError("向量分数门槛必须为数字")
    if not isinstance(rrf_k, int) or not isinstance(candidate_limit, int):
        raise ValueError("RRF 和候选数量参数必须为整数")
    ranges = {
        "limit": (limit, 1, 20),
        "max_excerpt_chars": (max_excerpt_chars, 100, 4000),
        "max_total_chars": (max_total_chars, 500, 16000),
        "neighbor_radius": (neighbor_radius, 0, 3),
        "vector_min_score": (float(vector_min_score), 0.5, 0.95),
        "rrf_k": (rrf_k, 10, 200),
        "candidate_limit": (candidate_limit, 8, 200),
    }
    if strict:
        invalid = [name for name, (current, low, high) in ranges.items() if current < low or current > high]
        if invalid:
            raise ValueError("检索策略参数超出允许范围：" + "、".join(invalid))
    return RetrievalConfig(
        limit=min(max(limit, 1), 20),
        max_excerpt_chars=min(max(max_excerpt_chars, 100), 4000),
        max_total_chars=min(max(max_total_chars, 500), 16000),
        neighbor_radius=min(max(neighbor_radius, 0), 3),
        hybrid_enabled=hybrid_enabled,
        vector_min_score=min(max(float(vector_min_score), 0.5), 0.95),
        rrf_k=min(max(rrf_k, 10), 200),
        candidate_limit=min(max(candidate_limit, 8), 200),
        rewrite_enabled=rewrite_enabled,
    )


def config_as_dict(config: RetrievalConfig) -> dict:
    return {
        "limit": config.limit,
        "max_excerpt_chars": config.max_excerpt_chars,
        "max_total_chars": config.max_total_chars,
        "neighbor_radius": config.neighbor_radius,
        "hybrid_enabled": config.hybrid_enabled,
        "vector_min_score": config.vector_min_score,
        "rrf_k": config.rrf_k,
        "candidate_limit": config.candidate_limit,
        "rewrite_enabled": config.rewrite_enabled,
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
            "rationale": "反馈显示缺少应有资料；只增加返回数量以验证是否改善覆盖。",
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
            "rationale": "反馈显示命中了不相关文档；只减少返回数量以验证是否降低误召回。",
            "evidence": {"document_feedback_count": document_feedback_count, "reason_code": "wrong_document", "count": wrong_document},
            "risk": "可能遗漏相关资料，需要通过离线质量门。",
        }]
    return []


def apply_suggestion(config: RetrievalConfig, suggestion: dict) -> RetrievalConfig:
    if suggestion.get("changed_variable") != "limit":
        raise ValueError("当前仅支持调整候选资料数量")
    return config_from_json({**config_as_dict(config), "limit": suggestion.get("target_value")}, config)
