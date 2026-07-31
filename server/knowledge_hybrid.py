"""Deterministic hybrid retrieval fusion and bounded query rewriting."""
from __future__ import annotations

import re

from server.knowledge_retrieval import named_query_anchors, query_terms


HYBRID_POLICY_VERSION = "hybrid-rrf-v1"
RRF_K = 60
MIN_VECTOR_SCORE = 0.72


def bounded_query_rewrite(query: str) -> str:
    """Remove instruction noise while preserving names, IDs and file anchors."""
    terms = query_terms(query, gate_v2=True)
    protected = [
        token.lower()
        for token in re.findall(
            r"\b(?:[A-Za-z0-9_-]+\.(?:md|txt|pdf|docx|xlsx)|[A-Za-z][A-Za-z0-9_-]{2,})\b",
            query,
            flags=re.IGNORECASE,
        )
    ]
    protected.extend(named_query_anchors(query))
    rewritten = " ".join(dict.fromkeys([*protected, *terms[:12]])).strip()
    if not rewritten or rewritten == query.strip().lower():
        return ""
    return rewritten[:300]


def reciprocal_rank_fusion(
    lexical: list[dict],
    vector: list[dict],
    *,
    limit: int = 96,
    rrf_k: int = RRF_K,
) -> list[dict]:
    merged: dict[tuple[str, int], dict] = {}
    for source, rows in (("lexical", lexical), ("vector", vector)):
        for rank, raw in enumerate(rows, start=1):
            row = dict(raw)
            key = (str(row.get("document_id", "")), int(row.get("position", 0)))
            if not key[0]:
                continue
            item = merged.setdefault(key, row)
            item[f"{source}_rank"] = rank
            item["hybrid_rrf_score"] = float(item.get("hybrid_rrf_score", 0.0)) + 1.0 / (rrf_k + rank)
            if source == "vector":
                item["vector_score"] = float(row.get("vector_score", 0.0))
                item["semantic_candidate"] = True
            if source == "lexical":
                item["bm25_score"] = row.get("bm25_score")
                item["retrieval_candidate"] = row.get("retrieval_candidate", True)
            # Prefer the richer active-chunk row if the first source was sparse.
            for field, value in row.items():
                if field not in item or item[field] in (None, ""):
                    item[field] = value
    ranked = sorted(
        merged.values(),
        key=lambda item: (
            -float(item.get("hybrid_rrf_score", 0.0)),
            -float(item.get("vector_score", -1.0)),
            int(item.get("position", 0)),
            str(item.get("id", "")),
        ),
    )
    return ranked[: max(1, min(limit, 200))]
