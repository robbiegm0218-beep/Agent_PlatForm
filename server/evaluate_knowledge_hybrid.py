#!/usr/bin/env python3
"""Offline P51-6 gates for hybrid fusion, semantic recall and safety."""
from __future__ import annotations

import json
from pathlib import Path

from server.evaluate_knowledge_retrieval import DEFAULT_FIXTURE, evaluate, validate_cases
from server.knowledge_hybrid import bounded_query_rewrite, reciprocal_rank_fusion
from server.knowledge_retrieval import KnowledgeRetriever, RetrievalConfig, assess_candidate_relevance


REPORT_PATH = Path(__file__).with_name("evals") / "p51_hybrid_report.json"


def run(config: RetrievalConfig | None = None) -> dict:
    cases = validate_cases(json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8")))
    active = config or RetrievalConfig()
    baseline = evaluate(cases, KnowledgeRetriever(active))
    retriever = KnowledgeRetriever(active)

    semantic_rows = [
        {
            "id": "semantic", "document_id": "release", "filename": "发布规范.md",
            "position": 1, "content": "发布许可需要负责人完成风险签字。",
            "vector_score": 0.91, "semantic_candidate": True,
            "hybrid_rrf_score": 1 / 61,
        },
        {
            "id": "neighbor", "document_id": "release", "filename": "发布规范.md",
            "position": 2, "content": "风险签字完成后进入部署窗口。",
        },
        {
            "id": "noise", "document_id": "noise", "filename": "食谱.md",
            "position": 0, "content": "晚餐建议使用时令蔬菜。",
            "vector_score": 0.55, "semantic_candidate": True,
        },
    ]
    semantic = retriever.search("上线审批责任人", semantic_rows) if active.hybrid_enabled else []
    named_anchor = retriever.search("Atlas 上线审批责任人", semantic_rows, gate_v2=True) if active.hybrid_enabled else []
    named_assessment = assess_candidate_relevance("Atlas 上线审批责任人", named_anchor, gate_v2=True)

    lexical = [
        {"id": "lex", "document_id": "lex", "position": 0, "content": "发布审批"},
        {"id": "shared", "document_id": "shared", "position": 0, "content": "发布审批签字"},
    ]
    vector = [
        {"id": "shared", "document_id": "shared", "position": 0, "content": "发布审批签字", "vector_score": 0.84},
        {"id": "vec", "document_id": "vec", "position": 0, "content": "发布许可", "vector_score": 0.9},
    ]
    fused = reciprocal_rank_fusion(lexical, vector, rrf_k=active.rrf_k)
    rewrite = bounded_query_rewrite("请根据知识库核对 Atlas-42 在 release-plan.md 中的发布要求") if active.rewrite_enabled else ""
    gates = {
        "baseline_recall_preserved": baseline["recall_at_4"] == 1.0,
        "baseline_top1_preserved": baseline["top1_accuracy"] == 1.0,
        "baseline_negative_accuracy_preserved": baseline["no_match_accuracy"] == 1.0,
        "semantic_synonym_recalled": bool(semantic) and semantic[0]["document_id"] == "release",
        "low_vector_not_forced": all(item["document_id"] != "noise" for item in semantic),
        "neighbor_expansion": bool(semantic) and semantic[0]["neighbor_positions"] == [2],
        "rrf_shared_candidate_first": fused[0]["document_id"] == "shared",
        "named_anchor_blocks_implicit_injection": not named_assessment["strong_anchor"],
        "rewrite_preserves_anchors": "atlas-42" in rewrite and "release-plan.md" in rewrite,
    }
    return {
        "policy_version": "hybrid-rrf-v1",
        "baseline": baseline,
        "targeted_gates": gates,
        "passed": all(gates.values()),
    }


def main() -> int:
    report = run()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
