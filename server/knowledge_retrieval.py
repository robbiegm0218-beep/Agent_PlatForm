"""Deterministic local knowledge retrieval with explainable lexical scoring."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Iterable, Mapping


_QUERY_NOISE = (
    "请根据", "请基于", "基于", "根据", "本地资料", "知识库", "参考资料", "上传资料",
    "帮我", "请问", "请", "总结", "说明", "介绍", "解释", "查阅", "检索", "回答",
    "是什么", "什么是", "如何", "怎么", "哪些", "一下",
)

_V2_QUERY_NOISE = (
    "制定", "生成", "执行", "项目", "计划", "方案", "页面", "分析", "内容",
)

RETRIEVAL_POLICY_VERSION = "lexical-retrieval-v1"


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())


def query_terms(query: str, gate_v2: bool = False) -> list[str]:
    cleaned = query.lower()
    for marker in (*_QUERY_NOISE, *(_V2_QUERY_NOISE if gate_v2 else ())):
        cleaned = cleaned.replace(marker, " ")
    english = re.findall(r"[a-z0-9_]{2,}", cleaned)
    chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", cleaned)
    chinese: list[str] = []
    for run in chinese_runs:
        if len(run) <= 4:
            chinese.append(run)
        chinese.extend(run[index:index + 2] for index in range(len(run) - 1))
    return list(dict.fromkeys(english + chinese))[:32]


def named_query_anchors(query: str) -> list[str]:
    """Return explicit ASCII names whose absence should weaken a candidate."""
    return list(dict.fromkeys(
        token.lower()
        for token in re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", query)
    ))[:8]


def assess_candidate_relevance(
    query: str,
    references: list[dict],
    gate_v2: bool = False,
) -> dict:
    """Return content-free, explainable relevance gates for the top candidate."""
    terms = query_terms(query, gate_v2=gate_v2)
    expected_matches = 1 if len(terms) <= 1 else 2
    top = references[0] if references else None
    if not top:
        return {
            "sufficient": False,
            "strong_anchor": False,
            "rank_confident": False,
            "top1_score": None,
            "top1_top2_gap": None,
            "coverage_ratio": 0.0,
            "filename_match_count": 0,
            "rare_match_count": 0,
            "unmatched_named_anchor_count": 0,
        }

    signals = top.get("match_signals") or {}
    matched_terms = list(top.get("matched_terms") or [])
    filename_terms = list(signals.get("filename_terms") or [])
    rare_terms = list(signals.get("rare_terms") or [])
    coverage_ratio = float(signals.get("coverage_ratio") or 0.0)
    score = float(top.get("score") or 0.0)
    second_document = next(
        (
            item for item in references[1:]
            if item.get("document_id") != top.get("document_id")
        ),
        None,
    )
    gap = (
        score - float(second_document.get("score") or 0.0)
        if second_document is not None
        else None
    )
    named_anchors = named_query_anchors(query)
    normalized_candidate = normalize_text(
        f"{top.get('filename', '')} {top.get('excerpt', '')}"
    )
    unmatched_named_anchors = [
        anchor for anchor in named_anchors if anchor not in normalized_candidate
    ]
    informative_rare_terms = [
        term for term in rare_terms
        if len(term) >= 3
    ]
    exact_phrase = bool(signals.get("exact_phrase"))
    filename_anchor = len(filename_terms) >= 2 and coverage_ratio >= 0.4
    rare_anchor = bool(informative_rare_terms) and coverage_ratio >= 0.5
    strong_anchor = not unmatched_named_anchors and (
        exact_phrase or filename_anchor or rare_anchor
    )
    rank_confident = (
        gap is None
        or float(gap) >= 0.75
        or exact_phrase
        or len(filename_terms) >= 2
    )
    sufficient = (
        len(matched_terms) >= expected_matches
        and score >= 2.0
    )
    return {
        "sufficient": sufficient,
        "strong_anchor": strong_anchor,
        "rank_confident": rank_confident,
        "top1_score": round(score, 6),
        "top1_top2_gap": round(float(gap), 6) if gap is not None else None,
        "coverage_ratio": round(coverage_ratio, 6),
        "filename_match_count": len(filename_terms),
        "rare_match_count": len(rare_terms),
        "unmatched_named_anchor_count": len(unmatched_named_anchors),
    }


@dataclass(frozen=True)
class RetrievalConfig:
    limit: int = 4
    max_excerpt_chars: int = 900
    max_total_chars: int = 2800
    neighbor_radius: int = 1
    hybrid_enabled: bool = True
    vector_min_score: float = 0.72
    rrf_k: int = 60
    candidate_limit: int = 64
    rewrite_enabled: bool = True


def retrieval_policy_snapshot(config: RetrievalConfig | None = None, version: str = RETRIEVAL_POLICY_VERSION) -> dict:
    """Return the immutable retrieval settings recorded with each Run."""
    active = config or RetrievalConfig()
    return {
        "version": version,
        "config": {
            "limit": active.limit,
            "max_excerpt_chars": active.max_excerpt_chars,
            "max_total_chars": active.max_total_chars,
            "neighbor_radius": active.neighbor_radius,
            "hybrid_enabled": active.hybrid_enabled,
            "vector_min_score": active.vector_min_score,
            "rrf_k": active.rrf_k,
            "candidate_limit": active.candidate_limit,
            "rewrite_enabled": active.rewrite_enabled,
        },
    }


class KnowledgeRetriever:
    def __init__(self, config: RetrievalConfig | None = None) -> None:
        self.config = config or RetrievalConfig()

    def search(self, query: str, rows: Iterable[Mapping], gate_v2: bool = False) -> list[dict]:
        records = [dict(row) for row in rows]
        terms = query_terms(query, gate_v2=gate_v2)
        if not records or not terms:
            return []
        named_anchors = named_query_anchors(query)

        document_frequency = {
            term: sum(1 for row in records if term in normalize_text(str(row.get("content", ""))))
            for term in terms
        }
        normalized_query = normalize_text(query)
        ranked = []
        for row in records:
            content = str(row.get("content", ""))
            normalized_content = normalize_text(content)
            normalized_filename = normalize_text(str(row.get("filename", "")))
            normalized_section = normalize_text(str(row.get("section_path_json", "")))
            searchable_heading = f"{normalized_filename}{normalized_section}"
            matched = [term for term in terms if term in normalized_content or term in searchable_heading]
            filename_matches = [term for term in matched if term in normalized_filename]
            section_matches = [term for term in matched if term in normalized_section]
            rare_matches = [
                term for term in matched
                if document_frequency[term] <= max(1, math.ceil(len(records) * 0.25))
            ]
            matched_named_anchors = [
                anchor for anchor in named_anchors
                if anchor in normalized_content or anchor in normalized_filename
            ]
            vector_score = float(row.get("vector_score") or 0.0)
            semantic_candidate = bool(row.get("semantic_candidate")) and vector_score >= self.config.vector_min_score
            minimum_matches = 1 if len(terms) == 1 else 2
            if len(matched) < minimum_matches and not semantic_candidate:
                continue

            lexical = 0.0
            title = 0.0
            for term in matched:
                frequency = normalized_content.count(term)
                if frequency:
                    inverse_document_frequency = math.log((len(records) + 1) / (document_frequency[term] + 1)) + 1
                    lexical += (1 + math.log(min(frequency, 6))) * inverse_document_frequency
                if term in normalized_filename:
                    title += 2.5
                elif term in normalized_section:
                    title += 1.5
            coverage = 4.0 * len(matched) / len(terms)
            phrase = 8.0 if len(normalized_query) >= 4 and normalized_query in normalized_content else 0.0
            length_normalization = 1 / math.sqrt(max(len(normalized_content), 120) / 120)
            semantic = max(0.0, vector_score) * 3.0 if semantic_candidate else 0.0
            fusion = float(row.get("hybrid_rrf_score") or 0.0) * 30.0
            score = (lexical * length_normalization) + title + coverage + phrase + semantic + fusion
            ranked.append((
                score, phrase, title, lexical, coverage, semantic, fusion, matched, row,
                filename_matches, section_matches, rare_matches, matched_named_anchors,
            ))

        ranked.sort(key=lambda item: (-item[0], int(item[8].get("position", 0)), str(item[8].get("id", ""))))
        by_document_position = {
            (str(row.get("document_id", "")), int(row.get("position", 0))): row for row in records
        }
        results = []
        seen_hashes: set[str] = set()
        seen_normalized: list[str] = []
        remaining_budget = self.config.max_total_chars
        for (
            score, phrase, title, lexical, coverage, semantic, fusion, matched, row,
            filename_matches, section_matches, rare_matches, matched_named_anchors,
        ) in ranked:
            if len(results) >= self.config.limit or remaining_budget <= 0:
                break
            primary_content = str(row.get("content", "")).strip()
            normalized_primary = normalize_text(primary_content)
            content_hash = hashlib.sha256(normalized_primary.encode("utf-8")).hexdigest()
            if content_hash in seen_hashes:
                continue
            if any(
                min(len(normalized_primary), len(previous)) >= 80
                and (
                    normalized_primary in previous
                    or previous in normalized_primary
                )
                and min(len(normalized_primary), len(previous)) / max(len(normalized_primary), len(previous)) >= 0.85
                for previous in seen_normalized
            ):
                continue
            seen_hashes.add(content_hash)
            seen_normalized.append(normalized_primary)

            document_id = str(row.get("document_id", ""))
            position = int(row.get("position", 0))
            parts = [primary_content]
            neighbor_positions = []
            for distance in range(1, self.config.neighbor_radius + 1):
                for neighbor_position in (position - distance, position + distance):
                    neighbor = by_document_position.get((document_id, neighbor_position))
                    if neighbor:
                        neighbor_content = str(neighbor.get("content", "")).strip()
                        if neighbor_content and neighbor_content not in parts:
                            parts.append(neighbor_content)
                            neighbor_positions.append(neighbor_position)
            excerpt_limit = min(self.config.max_excerpt_chars, remaining_budget)
            excerpt = "\n\n".join(parts)[:excerpt_limit].strip()
            if not excerpt:
                continue
            remaining_budget -= len(excerpt)
            results.append({
                "document_id": document_id,
                "filename": str(row.get("filename", "")),
                "position": position,
                "excerpt": excerpt,
                "score": round(score, 6),
                "matched_terms": matched,
                "neighbor_positions": sorted(neighbor_positions),
                "score_breakdown": {
                    "phrase": round(phrase, 6),
                    "title": round(title, 6),
                    "lexical": round(lexical, 6),
                    "coverage": round(coverage, 6),
                    "semantic": round(semantic, 6),
                    "fusion": round(fusion, 6),
                },
                "match_signals": {
                    "exact_phrase": bool(phrase),
                    "filename_terms": filename_matches,
                    "section_terms": section_matches,
                    "rare_terms": rare_matches,
                    "coverage_ratio": round(len(matched) / len(terms), 6),
                    "named_anchors": named_anchors,
                    "matched_named_anchors": matched_named_anchors,
                    "unmatched_named_anchors": [
                        anchor for anchor in named_anchors
                        if anchor not in matched_named_anchors
                    ],
                    "semantic_candidate": bool(row.get("semantic_candidate")),
                    "vector_score": row.get("vector_score"),
                    "lexical_rank": row.get("lexical_rank"),
                    "vector_rank": row.get("vector_rank"),
                    "rrf_score": round(float(row.get("hybrid_rrf_score") or 0.0), 8),
                },
            })
        if results:
            top_document_id = results[0]["document_id"]
            second_document = next(
                (item for item in results[1:] if item["document_id"] != top_document_id),
                None,
            )
            top_score = float(results[0]["score"])
            second_score = float(second_document["score"]) if second_document else None
            results[0]["ranking_signals"] = {
                "top1_score": round(top_score, 6),
                "top2_document_score": round(second_score, 6) if second_score is not None else None,
                "top1_top2_document_gap": (
                    round(top_score - second_score, 6) if second_score is not None else None
                ),
            }
        return results
