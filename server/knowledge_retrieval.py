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


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())


def query_terms(query: str) -> list[str]:
    cleaned = query.lower()
    for marker in _QUERY_NOISE:
        cleaned = cleaned.replace(marker, " ")
    english = re.findall(r"[a-z0-9_]{2,}", cleaned)
    chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", cleaned)
    chinese: list[str] = []
    for run in chinese_runs:
        if len(run) <= 4:
            chinese.append(run)
        chinese.extend(run[index:index + 2] for index in range(len(run) - 1))
    return list(dict.fromkeys(english + chinese))[:32]


@dataclass(frozen=True)
class RetrievalConfig:
    limit: int = 4
    max_excerpt_chars: int = 900
    max_total_chars: int = 2800
    neighbor_radius: int = 1


class KnowledgeRetriever:
    def __init__(self, config: RetrievalConfig | None = None) -> None:
        self.config = config or RetrievalConfig()

    def search(self, query: str, rows: Iterable[Mapping]) -> list[dict]:
        records = [dict(row) for row in rows]
        terms = query_terms(query)
        if not records or not terms:
            return []

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
            matched = [term for term in terms if term in normalized_content or term in normalized_filename]
            minimum_matches = 1 if len(terms) == 1 else 2
            if len(matched) < minimum_matches:
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
            coverage = 4.0 * len(matched) / len(terms)
            phrase = 8.0 if len(normalized_query) >= 4 and normalized_query in normalized_content else 0.0
            length_normalization = 1 / math.sqrt(max(len(normalized_content), 120) / 120)
            score = (lexical * length_normalization) + title + coverage + phrase
            ranked.append((score, phrase, title, lexical, coverage, matched, row))

        ranked.sort(key=lambda item: (-item[0], int(item[6].get("position", 0)), str(item[6].get("id", ""))))
        by_document_position = {
            (str(row.get("document_id", "")), int(row.get("position", 0))): row for row in records
        }
        results = []
        seen_hashes: set[str] = set()
        remaining_budget = self.config.max_total_chars
        for score, phrase, title, lexical, coverage, matched, row in ranked:
            if len(results) >= self.config.limit or remaining_budget <= 0:
                break
            primary_content = str(row.get("content", "")).strip()
            content_hash = hashlib.sha256(normalize_text(primary_content).encode("utf-8")).hexdigest()
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)

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
                },
            })
        return results
