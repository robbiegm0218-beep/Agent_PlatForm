"""Deterministic P45 task acceptance checks using TaskFrame and evidence metadata."""
from __future__ import annotations


def verify(task_frame: dict | None, ledger: dict | None, answer: str, *, tool_events: list[dict] | None = None,
           artifact_records: list[dict] | None = None, artifact_request: dict | None = None) -> dict:
    frame = task_frame or {}
    requirements = frame.get("evidence_requirements", [])
    evidence_decision = (ledger or {}).get("decision", "sufficient")
    results = []
    for item in frame.get("deliverables", []):
        results.append({"id": item.get("id", "deliverable"), "passed": bool(answer.strip()), "reason": "已生成回答" if answer.strip() else "未生成回答"})
    missing_evidence = list((ledger or {}).get("missing_requirement_ids", [])) if evidence_decision != "sufficient" else []
    unsupported = []
    goal = str(frame.get("goal", ""))
    requested_artifact = (artifact_request or {}).get("kind", "")
    task_type = "file" if requested_artifact or any(word in goal.lower() for word in ("文件", "markdown", "excel", "xlsx")) else "code" if any(word in goal for word in ("代码", "实现", "测试")) else "plan" if any(word in goal for word in ("方案", "计划", "复盘")) else "analysis" if any(word in goal for word in ("分析", "调研")) else "knowledge" if requirements else "answer"
    lower = answer.lower()
    if task_type == "plan":
        missing = [label for label in ("行动", "负责人", "时间", "风险", "指标") if label not in answer]
        if missing: unsupported.append("方案缺少：" + "、".join(missing))
    elif task_type == "code":
        missing = [label for label in ("变更", "测试") if label not in answer]
        if missing: unsupported.append("代码任务缺少：" + "、".join(missing))
        successful_tools = [item.get("tool_id", "") for item in (tool_events or []) if item.get("type") == "tool_result"]
        if not any(tool_id in {"write_file", "apply_patch", "edit_file"} for tool_id in successful_tools) and "未验证" not in answer:
            unsupported.append("代码任务没有可验证的变更记录")
        if not any(tool_id in {"run_tests", "test", "pytest"} for tool_id in successful_tools) and "未验证" not in answer:
            unsupported.append("代码任务没有可验证的测试记录")
    elif task_type == "file":
        matching_artifacts = [item for item in (artifact_records or []) if not requested_artifact or item.get("kind") == requested_artifact]
        if not matching_artifacts:
            unsupported.append("文件任务尚无已验证的实际产物")
    elif task_type == "analysis" and "推断" not in answer and "事实" not in answer:
        unsupported.append("分析未区分事实与推断")
    if tool_events and any(item.get("type") == "tool_error" for item in tool_events) and "未验证" not in answer:
        unsupported.append("工具失败后未说明未验证项")
    if requirements and missing_evidence and "资料" in answer and "不足" not in answer and "限制" not in answer:
        unsupported.append("资料证据存在缺口，但回答未说明限制")
    passed = bool(answer.strip()) and not unsupported and not missing_evidence
    action = "complete" if passed else "revise" if unsupported else "retrieve_more" if evidence_decision == "retrieve_more" else "clarify" if evidence_decision == "clarify" else "complete_with_limits"
    return {"passed": passed, "task_type": task_type, "requirement_results": results, "unsupported_claims": unsupported, "missing_evidence": missing_evidence, "action": action, "summary": "任务验收通过" if passed else "任务验收发现证据或表达缺口"}
