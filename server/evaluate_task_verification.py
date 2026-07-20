#!/usr/bin/env python3
import json
from pathlib import Path
from server.task_verifier import verify

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "server" / "evals" / "task_verification.json"
TEMPLATES = {
 "answer": ({"goal":"说明"}, {}, "直接回答", True),
 "knowledge_gap": ({"goal":"知识回答","evidence_requirements":[{"id":"e"}]}, {"decision":"retrieve_more","missing_requirement_ids":["e"]}, "根据资料确定", False),
 "analysis_missing": ({"goal":"分析风险"}, {}, "结论如下", False),
 "plan_missing": ({"goal":"方案计划"}, {}, "给出方案", False),
 "plan_complete": ({"goal":"方案计划"}, {}, "行动 负责人 时间 风险 指标", True),
 "code_missing": ({"goal":"代码实现"}, {}, "已完成", False),
 "code_complete": ({"goal":"代码实现"}, {}, "变更内容与测试结果", True, [{"type":"tool_result","tool_id":"apply_patch"},{"type":"tool_result","tool_id":"run_tests"}]),
}
def evaluate(suite):
    rows=[]
    for case in suite["cases"]:
        template = TEMPLATES[case["template"]]
        frame, ledger, answer, expected = template[:4]
        tool_events = template[4] if len(template) > 4 else None
        actual=verify(frame,ledger,answer, tool_events=tool_events)["passed"]
        rows.append({"id":case["id"],"passed":actual==expected})
    return {"summary":{"total":len(rows),"passed":sum(x["passed"] for x in rows),"failed":sum(not x["passed"] for x in rows)},"results":rows}
def main():
    suite=json.loads(DEFAULT.read_text(encoding="utf-8")); assert len(suite["cases"])>=35
    report=evaluate(suite); print(json.dumps(report,ensure_ascii=False)); return 0 if not report["summary"]["failed"] else 1
if __name__=="__main__": raise SystemExit(main())
