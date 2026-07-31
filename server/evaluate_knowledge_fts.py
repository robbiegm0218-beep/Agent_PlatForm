#!/usr/bin/env python3
"""Evaluate P51-4 FTS candidate recall and scan reduction on synthetic fixtures."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from server.evaluate_knowledge_retrieval import DEFAULT_FIXTURE, validate_cases
from server.knowledge_fts import FTS_POLICY_VERSION, build_fts_query
from server.knowledge_retrieval import KnowledgeRetriever


REPORT_PATH = Path(__file__).with_name("evals") / "p51_fts_report.json"


def _unique(values):
    return list(dict.fromkeys(values))


def scale_benchmark(row_count: int = 2000, repetitions: int = 25) -> dict:
    rows = [{
        "id": f"noise-{index}",
        "document_id": f"noise-doc-{index}",
        "filename": f"noise-{index}.md",
        "position": 0,
        "content": f"普通背景资料 {index}，不包含目标产品术语。",
    } for index in range(row_count - 1)]
    target = {
        "id": "target",
        "document_id": "target-doc",
        "filename": "产品指标.md",
        "position": 0,
        "content": "北极星指标是每周完成首次核心任务的活跃用户数。",
    }
    rows.append(target)
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE VIRTUAL TABLE chunks_fts USING fts5(
        chunk_id UNINDEXED, document_id UNINDEXED, filename, title, body, tags,
        tokenize='trigram'
    )""")
    conn.executemany(
        "INSERT INTO chunks_fts VALUES (?, ?, ?, '', ?, '')",
        [(row["id"], row["document_id"], row["filename"], row["content"]) for row in rows],
    )
    query = "北极星指标"
    fts_query = build_fts_query(query)
    retriever = KnowledgeRetriever()
    by_id = {row["id"]: row for row in rows}
    legacy_ms = []
    fts_ms = []
    for _ in range(repetitions):
        started = time.perf_counter()
        retriever.search(query, rows, gate_v2=True)
        legacy_ms.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        matched_ids = [
            row[0] for row in conn.execute(
                "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT 64",
                (fts_query,),
            )
        ]
        candidates = [by_id[chunk_id] for chunk_id in matched_ids]
        retriever.search(query, candidates, gate_v2=True)
        fts_ms.append((time.perf_counter() - started) * 1000)
    conn.close()
    legacy = sorted(legacy_ms)[max(0, (len(legacy_ms) * 95 + 99) // 100 - 1)]
    fts = sorted(fts_ms)[max(0, (len(fts_ms) * 95 + 99) // 100 - 1)]
    return {
        "rows": row_count,
        "repetitions": repetitions,
        "fts_candidates": len(candidates),
        "legacy_p95_ms": round(legacy, 4),
        "fts_p95_ms": round(fts, 4),
        "p95_speedup": round(legacy / fts, 4) if fts else None,
        "candidate_row_ratio": round(len(candidates) / row_count, 6),
    }


def evaluate(cases: list[dict]) -> dict:
    failures = []
    relevant = recalled = top1 = non_empty = empty = empty_correct = 0
    total_rows = candidate_rows = 0
    indexed_cases = reduced_cases = fallback_cases = 0
    durations = []
    case_results = []
    retriever = KnowledgeRetriever()
    for case in cases:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE VIRTUAL TABLE chunks_fts USING fts5(
            chunk_id UNINDEXED, document_id UNINDEXED, filename, title, body, tags,
            tokenize='trigram'
        )""")
        conn.executemany(
            "INSERT INTO chunks_fts VALUES (?, ?, ?, '', ?, '')",
            [
                (row["id"], row["document_id"], row["filename"], row["content"])
                for row in case["documents"]
            ],
        )
        started = time.perf_counter()
        fts_query = build_fts_query(case["query"])
        candidates = []
        fallback = ""
        if fts_query:
            # The fixture rows are already in memory; use FTS only to resolve IDs.
            matched_ids = [
                row[0] for row in conn.execute(
                    "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts)",
                    (fts_query,),
                )
            ]
            by_id = {row["id"]: row for row in case["documents"]}
            candidates = [dict(by_id[chunk_id]) for chunk_id in matched_ids if chunk_id in by_id]
        if not fts_query:
            fallback = "insufficient_query_terms"
        elif not candidates:
            fallback = "no_fts_candidates"
        rows = case["documents"] if fallback else candidates
        results = retriever.search(case["query"], rows, gate_v2=True)
        if not results and rows and not fallback:
            fallback = "fts_candidates_filtered"
            rows = case["documents"]
            results = retriever.search(case["query"], rows, gate_v2=True)
        durations.append((time.perf_counter() - started) * 1000)
        conn.close()
        actual = _unique(item["document_id"] for item in results)[:4]
        expected = case["expected_document_ids"]
        if case["expect_empty"]:
            empty += 1
            empty_correct += int(not actual)
            if actual:
                failures.append({"id": case["id"], "kind": "unexpected_result"})
        else:
            non_empty += 1
            relevant += len(expected)
            recalled += len(set(expected) & set(actual))
            top1 += int(bool(actual) and actual[0] == expected[0])
            if not set(expected) <= set(actual):
                failures.append({"id": case["id"], "kind": "recall_miss"})
        total = len(case["documents"])
        count = len(candidates)
        total_rows += total
        candidate_rows += count if not fallback else total
        if not fallback:
            indexed_cases += 1
            reduced_cases += int(count < total)
        else:
            fallback_cases += 1
        case_results.append({
            "id": case["id"],
            "document_rows": total,
            "fts_candidates": count,
            "fallback_reason": fallback,
            "actual_document_ids": actual,
            "passed": not failures or failures[-1].get("id") != case["id"],
        })
    ordered = sorted(durations)
    p95 = ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)] if ordered else 0
    benchmark = scale_benchmark()
    if benchmark["fts_p95_ms"] >= benchmark["legacy_p95_ms"]:
        failures.append({"id": "scale-benchmark", "kind": "latency_not_improved"})
    return {
        "schema_version": 1,
        "policy_version": FTS_POLICY_VERSION,
        "cases": len(cases),
        "recall_at_4": round(recalled / relevant, 4) if relevant else 1.0,
        "top1_accuracy": round(top1 / non_empty, 4) if non_empty else 1.0,
        "no_match_accuracy": round(empty_correct / empty, 4) if empty else 1.0,
        "indexed_cases": indexed_cases,
        "fallback_cases": fallback_cases,
        "full_scan_avoided_cases": reduced_cases,
        "candidate_row_ratio": round(candidate_rows / total_rows, 4) if total_rows else 0,
        "p95_ms": round(p95, 4),
        "scale_benchmark": benchmark,
        "case_results": case_results,
        "failures": failures,
    }


def main() -> int:
    cases = validate_cases(json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8")))
    report = evaluate(cases)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        key: report[key]
        for key in (
            "cases", "recall_at_4", "top1_accuracy", "no_match_accuracy",
            "indexed_cases", "fallback_cases", "full_scan_avoided_cases",
            "candidate_row_ratio", "p95_ms", "failures",
        )
    }, ensure_ascii=False, indent=2))
    print(json.dumps({"scale_benchmark": report["scale_benchmark"]}, ensure_ascii=False, indent=2))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
