#!/usr/bin/env python3
"""Produce the deterministic, content-safe P52 configuration baseline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from server.evaluate_knowledge_hybrid import run as evaluate_hybrid
from server.evaluate_knowledge_retrieval import DEFAULT_FIXTURE, evaluate, validate_cases
from server.knowledge_configuration_contracts import configuration_contract_snapshot
from server.knowledge_retrieval import KnowledgeRetriever, RetrievalConfig


REPORT_PATH = Path(__file__).with_name("evals") / "p52_knowledge_configuration_report.json"


def run() -> dict:
    contract = configuration_contract_snapshot()
    contract_json = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    cases = validate_cases(json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8")))
    retrieval = evaluate(cases, KnowledgeRetriever(RetrievalConfig()), gate_v2=True)
    hybrid = evaluate_hybrid(RetrievalConfig())
    failures = []
    if retrieval["failures"]:
        failures.append({"id": "retrieval_baseline", "kind": "fixed_set_regression"})
    if not hybrid["passed"]:
        failures.append({"id": "hybrid_baseline", "kind": "targeted_gate_regression"})
    if contract["content_safety"] != {
        "secret_values_exposed": False,
        "query_or_knowledge_content_exposed": False,
        "absolute_paths_exposed": False,
    }:
        failures.append({"id": "contract_privacy", "kind": "unsafe_snapshot"})
    return {
        "schema_version": 1,
        "phase": "P52-8",
        "production_behavior_changed": True,
        "contract_sha256": hashlib.sha256(contract_json.encode("utf-8")).hexdigest(),
        "configuration_contract": contract,
        "retrieval_baseline": {
            key: retrieval[key]
            for key in ("cases", "recall_at_4", "top1_accuracy", "no_match_accuracy", "neighbor_accuracy")
        },
        "hybrid_targeted_gates": hybrid["targeted_gates"],
        "failures": failures,
    }


def main() -> int:
    report = run()
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
