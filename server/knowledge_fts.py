"""FTS5 query construction and content-safe retrieval trace helpers."""

from __future__ import annotations

import hashlib
import json
import re


FTS_POLICY_VERSION = "fts5-bm25-v1"
FTS_CANDIDATE_LIMIT = 64


def fts_query_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    for word in re.findall(r"[A-Za-z0-9_]{3,}", query.lower()):
        tokens.append(word[:64])
    for run in re.findall(r"[\u3400-\u9fff]{3,}", query):
        tokens.extend(run[index:index + 3] for index in range(len(run) - 2))
    return list(dict.fromkeys(tokens))[:24]


def build_fts_query(query: str) -> str:
    tokens = fts_query_tokens(query)
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def query_sha256(query: str) -> str:
    normalized = re.sub(r"\s+", " ", query.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def candidate_trace_summary(candidates: list[dict], selected: list[dict]) -> str:
    selected_keys = {
        (str(item.get("document_id", "")), int(item.get("position", 0)))
        for item in selected
    }
    summary = []
    for candidate in candidates[:200]:
        key = (str(candidate.get("document_id", "")), int(candidate.get("position", 0)))
        picked = key in selected_keys
        summary.append({
            "chunk_id": str(candidate.get("id", "")),
            "document_id": key[0],
            "position": key[1],
            "bm25_score": candidate.get("bm25_score"),
            "vector_score": candidate.get("vector_score"),
            "lexical_rank": candidate.get("lexical_rank"),
            "vector_rank": candidate.get("vector_rank"),
            "rrf_score": round(float(candidate.get("hybrid_rrf_score") or 0.0), 8),
            "selected": picked,
            "reason": "selected" if picked else "relevance_filter_duplicate_or_context_budget",
        })
    return json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
