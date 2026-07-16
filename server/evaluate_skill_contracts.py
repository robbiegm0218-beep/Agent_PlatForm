from __future__ import annotations

import json
import argparse
from pathlib import Path

try:
    from server.skill_contract import normalize_skill_contract, skill_matches
except ModuleNotFoundError:
    from skill_contract import normalize_skill_contract, skill_matches


BUILTIN_SKILL_IDS = {
    "general_assistant", "writing_assistant", "code_assistant", "file_artifact", "research_brief",
}


def evaluate(skills_dir: Path | None = None, baseline: dict | None = None) -> dict:
    skills_dir = skills_dir or Path(__file__).with_name("skills")
    baseline_by_id = {item["skill_id"]: item for item in (baseline or {}).get("skills", [])}
    results = []
    for path in sorted(skills_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("id") not in BUILTIN_SKILL_IDS:
            continue
        skill = normalize_skill_contract(raw)
        cases = skill["eval_cases"]
        passed = sum(
            skill_matches(skill, str(case.get("input", ""))) is bool(case.get("expects_trigger"))
            for case in cases
        )
        contract_fields = ("input_schema", "output_schema", "steps", "acceptance_rules", "eval_cases")
        result = {
            "skill_id": skill["id"],
            "version": skill.get("version", ""),
            "cases": len(cases),
            "passed": passed,
            "trigger_accuracy": round(passed / len(cases), 4) if cases else 0.0,
            "contract_complete": all(bool(skill.get(field)) for field in contract_fields),
        }
        previous = baseline_by_id.get(skill["id"])
        if previous:
            result["comparison"] = {
                "previous_version": previous.get("version", ""),
                "trigger_accuracy_delta": round(result["trigger_accuracy"] - float(previous.get("trigger_accuracy", 0)), 4),
            }
        results.append(result)
    total_cases = sum(item["cases"] for item in results)
    total_passed = sum(item["passed"] for item in results)
    return {
        "skills": results,
        "skill_count": len(results),
        "case_count": total_cases,
        "passed": total_passed,
        "trigger_accuracy": round(total_passed / total_cases, 4) if total_cases else 0.0,
        "all_contracts_complete": bool(results) and all(item["contract_complete"] for item in results),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate built-in Skill Contracts")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    baseline_report = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    report = evaluate(baseline=baseline_report)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
