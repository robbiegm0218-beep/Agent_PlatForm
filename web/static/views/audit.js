window.AgentAuditView = {
  renderRunList(state, els, onSelect) {
    els.runList.innerHTML = "";
    const labels = { completed: "已完成", failed: "失败", cancelled: "已取消", awaiting_confirmation: "待确认", running: "运行中", skipped: "已跳过" };
    state.runs.forEach((run) => {
      const button = document.createElement("button");
      button.className = `run-item ${run.status}`;
      button.textContent = `${labels[run.status] || "运行中"} · ${run.model}`;
      button.addEventListener("click", () => onSelect(run.id));
      els.runList.appendChild(button);
    });
    if (!state.runs.length) els.runDetail.textContent = "当前对话还没有运行记录。";
  },
  renderDetail(els, data, { onDownload, onFeedback, onCancel }) {
    const { run, events, steps, artifact, citation_feedback_items: savedCitationItems = [] } = data;
    const parse = (value, fallback) => { try { return JSON.parse(value || ""); } catch (_error) { return fallback; } };
    const context = parse(run.execution_context, {});
    const reflection = parse(run.reflection_snapshot, {});
    const plan = steps?.length ? steps : parse(run.plan_snapshot, []);
    const modes = context.execution_modes || {};
    const routeSummary = context.route_summary || {};
    const reasoningItems = events
      .filter((event) => event.type === "reasoning_summary")
      .flatMap((event) => parse(event.payload, {}).items || [])
      .filter((item) => typeof item === "string" && item.trim())
      .slice(0, 5);
    const elapsed = run.completed_at ? `${Math.max(0, Math.round((run.completed_at - run.started_at) / 1e9 * 10) / 10)} 秒` : "运行中";
    const skills = parse(run.skill_snapshot, []).map((skill) => skill.name).join("、") || "无";
    const tools = context.tools?.map((tool) => tool.name).join("、") || "无";
    const trace = events.filter((event) => ["tool_call", "tool_result", "tool_error"].includes(event.type)).map((event) => event.type).join(" → ") || "未调用工具";
    const reflectionText = reflection.applied ? `${reflection.summary || "已完成"}${reflection.revision_count ? `，已修订 ${reflection.revision_count} 次` : ""}` : "未触发";
    const modesText = `资料：${modes.source || "general"}｜知识库：${modes.knowledge || "auto"}（${routeSummary.knowledge_matches ?? context.knowledge_match_count ?? 0} 条）｜网络：${modes.web || "auto"}｜文件：${modes.file || "auto"}｜记忆：${routeSummary.memory_count ?? context.memories?.length ?? 0} 条`;
    const reasoningText = reasoningItems.length
      ? reasoningItems.map((item, index) => `${index + 1}. ${item}`).join("\n")
      : "未记录";
    els.runDetail.textContent = `模型：${run.model}\n任务档位：${context.task_tier || "standard"}\n路由：${context.model_route_reason || "未记录"}\n执行方式：${modesText}\n输出预算：${context.max_output_tokens || "未记录"}\n状态：${run.status}\n执行阶段：${run.run_phase || "未记录"}\n耗时：${elapsed}\n技能：${skills}\n\n推理摘要（已保存）：\n${reasoningText}\n\n计划：${plan.length ? plan.map((step) => `${step.title}（${step.status}）`).join(" → ") : "无"}\n允许工具：${tools}\n工具判断：${context.tool_route_reason || "未记录"}\n工具执行：${trace}\n质量检查：${reflectionText}${run.error ? `\n错误：${run.error}` : ""}`;
    if (artifact) {
      const link = document.createElement("button"); link.type = "button"; link.className = "artifact-link"; link.textContent = `下载文件：${artifact.filename}`;
      link.addEventListener("click", () => onDownload(artifact, link)); els.runDetail.appendChild(link);
    }
    const referencesByDocument = new Map();
    (context.knowledge_refs || []).forEach((reference) => {
      if (reference?.document_id && !referencesByDocument.has(reference.document_id)) referencesByDocument.set(reference.document_id, reference);
    });
    if (referencesByDocument.size) {
      const savedByDocument = new Map(savedCitationItems.map((item) => [item.document_id, item]));
      const feedback = document.createElement("section"); feedback.className = "citation-feedback";
      feedback.append(Object.assign(document.createElement("h3"), { textContent: "引用评价" }));
      feedback.append(Object.assign(document.createElement("p"), { textContent: "逐项标记命中的资料；反馈会用于后续检索质量分析，不会立即改变检索结果。" }));
      const entries = [];
      referencesByDocument.forEach((reference, documentId) => {
        const saved = savedByDocument.get(documentId);
        const entry = document.createElement("div"); entry.className = "citation-feedback-item";
        const name = document.createElement("strong"); name.textContent = reference.filename || "未命名资料";
        const status = document.createElement("select");
        status.setAttribute("aria-label", `评价引用：${name.textContent}`);
        [["", "暂不评价"], ["correct", "引用正确"], ["incorrect", "引用有误"]].forEach(([value, label]) => {
          const option = document.createElement("option"); option.value = value; option.textContent = label; status.appendChild(option);
        });
        status.value = saved ? (saved.citation_correct ? "correct" : "incorrect") : "";
        const reason = document.createElement("select"); reason.className = "hidden";
        reason.setAttribute("aria-label", `选择引用问题：${name.textContent}`);
        [["", "选择问题原因"], ["wrong_document", "文档不相关"], ["wrong_passage", "命中片段不相关"], ["outdated", "资料已过期"], ["answer_misused", "回答误用了资料"], ["missing_evidence", "缺少应有资料"]].forEach(([value, label]) => {
          const option = document.createElement("option"); option.value = value; option.textContent = label; reason.appendChild(option);
        });
        reason.value = saved?.reason_code || "";
        const note = document.createElement("input"); note.type = "text"; note.maxLength = 800; note.placeholder = "备注（可选）"; note.className = "hidden"; note.value = saved?.note || "";
        const sync = () => { const incorrect = status.value === "incorrect"; reason.classList.toggle("hidden", !incorrect); note.classList.toggle("hidden", !incorrect); };
        status.addEventListener("change", sync); sync();
        entry.append(name, status, reason, note); feedback.appendChild(entry);
        entries.push({ documentId, reference, status, reason, note });
      });
      const actions = document.createElement("div"); actions.className = "confirmation-actions";
      const allCorrect = document.createElement("button"); allCorrect.type = "button"; allCorrect.className = "secondary"; allCorrect.textContent = "全部标记为准确";
      allCorrect.addEventListener("click", () => entries.forEach((entry) => { entry.status.value = "correct"; entry.status.dispatchEvent(new Event("change")); }));
      const save = document.createElement("button"); save.type = "button"; save.textContent = savedCitationItems.length ? "更新引用评价" : "保存引用评价";
      save.addEventListener("click", () => {
        const selected = entries.filter((entry) => entry.status.value);
        const invalid = selected.find((entry) => entry.status.value === "incorrect" && !entry.reason.value);
        if (!selected.length) { save.textContent = "请至少评价一份资料"; return; }
        if (invalid) { save.textContent = "请为有误引用选择原因"; invalid.reason.focus(); return; }
        const citationItems = selected.map((entry) => ({
          document_id: entry.documentId,
          citation_correct: entry.status.value === "correct",
          reason_code: entry.status.value === "incorrect" ? entry.reason.value : "",
          note: entry.status.value === "incorrect" ? entry.note.value : "",
        }));
        onFeedback(run.id, {
          rating: citationItems.every((item) => item.citation_correct) ? 1 : -1,
          citation_correct: citationItems.every((item) => item.citation_correct),
          citation_items: citationItems,
        }, feedback, save);
      });
      actions.append(allCorrect, save); feedback.append(actions); els.runDetail.appendChild(feedback);
    }
    if (["running", "awaiting_confirmation"].includes(run.status)) {
      const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "secondary"; cancel.textContent = run.status === "awaiting_confirmation" ? "取消待确认任务" : "取消运行"; cancel.addEventListener("click", () => onCancel(run.id, cancel)); els.runDetail.appendChild(cancel);
    }
  },

  renderRetrievalDiagnostics(els, data, { onSelectRun, governance } = {}) {
    const { sample = {}, metrics = {}, reason_counts: reasonCounts = {}, documents = [], policy_feedback: policyFeedback = [], retrieval_policy: policy = {} } = data;
    const percent = (value) => value == null ? "暂无数据" : `${(value * 100).toFixed(1)}%`;
    const metricLabels = [
      ["检索触发率", metrics.retrieval_trigger_rate, "对话中实际发起知识库检索的比例"],
      ["找到资料比例", metrics.evidence_found_rate, "已发起检索的对话中至少命中一份资料的比例"],
      ["已评价文档相关率", metrics.evaluated_document_relevance_accuracy, "仅基于用户标记过的文档；不把回答误用资料计入此项"],
      ["回答引用准确率", metrics.answer_citation_accuracy, "用户对整次回答引用的评价"],
      ["资料缺失反馈率", metrics.missing_evidence_rate, "用户标记为缺少应有资料的比例"],
    ];
    els.runDetail.replaceChildren();
    const panel = document.createElement("section"); panel.className = "retrieval-diagnostics";
    panel.append(Object.assign(document.createElement("h3"), { textContent: "检索质量诊断" }));
    panel.append(Object.assign(document.createElement("p"), { textContent: sample.message || "正在汇总检索反馈。" }));
    const policyText = document.createElement("small"); policyText.textContent = `当前策略：${policy.version || "未记录"} · 已评价文档 ${sample.document_feedback_count || 0}/${sample.minimum_document_feedback || 20} 条`;
    panel.append(policyText);
    const metricGrid = document.createElement("div"); metricGrid.className = "diagnostic-metrics";
    metricLabels.forEach(([label, value, description]) => {
      const item = document.createElement("div"); item.className = "diagnostic-metric"; item.title = description;
      item.append(Object.assign(document.createElement("span"), { textContent: label }), Object.assign(document.createElement("strong"), { textContent: percent(value) }));
      metricGrid.appendChild(item);
    });
    panel.append(metricGrid);
    const reasonTitle = document.createElement("h4"); reasonTitle.textContent = "问题原因"; panel.append(reasonTitle);
    const reasons = document.createElement("p");
    const reasonLabels = { wrong_document: "文档不相关", wrong_passage: "片段不相关", outdated: "资料已过期", answer_misused: "回答误用资料", missing_evidence: "缺少应有资料" };
    reasons.textContent = Object.keys(reasonCounts).length ? Object.entries(reasonCounts).map(([code, count]) => `${reasonLabels[code] || code}：${count}`).join("；") : "暂无错误原因反馈";
    panel.append(reasons);
    const documentTitle = document.createElement("h4"); documentTitle.textContent = "资料观察"; panel.append(documentTitle);
    if (!documents.length) {
      panel.append(Object.assign(document.createElement("p"), { textContent: "暂无文档级评价。" }));
    } else {
      const list = document.createElement("div"); list.className = "diagnostic-document-list";
      documents.forEach((documentItem) => {
        const item = globalThis.document.createElement(documentItem.reference?.run_id ? "button" : "div"); item.className = "diagnostic-document";
        if (item instanceof HTMLButtonElement) { item.type = "button"; item.title = "查看这份资料对应的运行详情"; item.addEventListener("click", () => onSelectRun?.(documentItem.reference.run_id)); }
        const name = globalThis.document.createElement("strong"); name.textContent = documentItem.filename;
        const detail = globalThis.document.createElement("small"); detail.textContent = `${documentItem.assessed_count} 条评价 · 有误 ${documentItem.incorrect_count} 条 · ${documentItem.risk_level === "high" ? "高风险" : "持续观察"}`;
        const breakdown = documentItem.reference?.score_breakdown || {};
        const score = documentItem.reference?.score;
        const scoreText = typeof score === "number" ? `命中分 ${score.toFixed(2)} · 短语 ${breakdown.phrase ?? 0} / 标题 ${breakdown.title ?? 0} / 词汇 ${breakdown.lexical ?? 0} / 覆盖 ${breakdown.coverage ?? 0}` : "尚无可回看的命中评分";
        const trace = globalThis.document.createElement("small"); trace.textContent = scoreText;
        item.append(name, detail, trace); list.appendChild(item);
      });
      panel.append(list);
    }
    const policyTitle = document.createElement("h4"); policyTitle.textContent = "策略反馈观察"; panel.append(policyTitle);
    const policyObservation = document.createElement("p");
    policyObservation.textContent = policyFeedback.length ? policyFeedback.map((item) => `${item.retrieval_policy_version || "历史未记录"}：${item.assessed_count} 条 · ${percent(item.citation_accuracy)} · ${item.state === "ready" ? "可比较" : "观察中"}`).join("；") : "暂无策略版本反馈。";
    panel.append(policyObservation);
    if (governance) {
      const adminTitle = document.createElement("h4"); adminTitle.textContent = "管理员策略控制"; panel.append(adminTitle);
      const admin = document.createElement("div"); admin.className = "retrieval-governance";
      if (governance.evidence?.source === "trial_feedback_aggregate") {
        admin.append(Object.assign(document.createElement("p"), { textContent: `试用汇总信号：${governance.evidence.document_feedback_count || 0} 条引用评价。仅用于生成离线候选，不展示测试用户或文档内容。` }));
      }
      const suggestions = governance.suggestions || [];
      if (!suggestions.length) {
        admin.append(Object.assign(document.createElement("p"), { textContent: "当前没有满足样本门槛的单变量优化建议。" }));
      }
      suggestions.forEach((suggestion) => {
        const item = document.createElement("div"); item.className = "governance-item";
        item.append(Object.assign(document.createElement("strong"), { textContent: suggestion.title }), Object.assign(document.createElement("small"), { textContent: suggestion.rationale }));
        const button = document.createElement("button"); button.type = "button"; button.className = "secondary"; button.textContent = "创建候选策略";
        button.addEventListener("click", () => governance.onCreateCandidate(suggestion.id, button)); item.append(button); admin.append(item);
      });
      (governance.policies || []).filter((policy) => policy.status !== "retired").forEach((policy) => {
        const item = document.createElement("div"); item.className = "governance-item";
        item.append(Object.assign(document.createElement("strong"), { textContent: `${policy.version} · ${policy.status}` }), Object.assign(document.createElement("small"), { textContent: policy.changed_variable ? `仅调整：${policy.changed_variable}` : "当前或历史基线策略" }));
        if (policy.status === "candidate" || policy.status === "blocked") {
          const button = document.createElement("button"); button.type = "button"; button.className = "secondary"; button.textContent = "运行离线评测";
          button.addEventListener("click", () => governance.onEvaluate(policy.version, button)); item.append(button);
        }
        if (policy.status === "verified") {
          const button = document.createElement("button"); button.type = "button"; button.textContent = "确认发布";
          button.addEventListener("click", () => governance.onPublish(policy.version, button)); item.append(button);
        }
        admin.append(item);
      });
      if ((governance.policies || []).some((policy) => policy.status === "stable")) {
        const rollback = document.createElement("button"); rollback.type = "button"; rollback.className = "secondary"; rollback.textContent = "回滚到上一稳定策略";
        rollback.addEventListener("click", () => governance.onRollback(rollback)); admin.append(rollback);
      }
      panel.append(admin);
    }
    els.runDetail.appendChild(panel);
  },
  renderAgentRollout(els, data) {
    els.runDetail.replaceChildren();
    const { fixed = {}, shadow = {}, recommendation = "shadow", agent_intelligence: intelligence = {} } = data;
    const candidate = shadow.v2 || {};
    const baseline = shadow.v1 || {};
    const labels = { administrator_canary: "可进入管理员灰度", shadow: "继续 Shadow 观察", rollback: "建议回退到 V1" };
    const percent = (value) => value == null ? "暂无数据" : `${(value * 100).toFixed(1)}%`;
    const panel = document.createElement("section"); panel.className = "agent-rollout";
    panel.append(Object.assign(document.createElement("h3"), { textContent: "智能发布" }));
    panel.append(Object.assign(document.createElement("p"), { textContent: labels[recommendation] || recommendation }));
    const status = document.createElement("small");
    status.textContent = `固定评测：${fixed.passed ? "通过" : "未通过"}｜Shadow 样本：${shadow.v2_shadow_runs || 0}/30｜当前开关：${intelligence.enabled ? "已启用" : "关闭"}`;
    panel.append(status);
    const grid = document.createElement("div"); grid.className = "diagnostic-metrics";
    [["V1 完成率", percent(baseline.completion_rate)], ["V2 完成率", percent(candidate.completion_rate)], ["V2 验收失败率", percent(candidate.verification_failure_rate)], ["V2 P95 时延", candidate.p95_seconds == null ? "暂无数据" : `${candidate.p95_seconds} 秒`]].forEach(([label, value]) => {
      const item = document.createElement("div"); item.className = "diagnostic-metric";
      item.append(Object.assign(document.createElement("span"), { textContent: label }), Object.assign(document.createElement("strong"), { textContent: value })); grid.appendChild(item);
    });
    panel.append(grid);
    const modes = document.createElement("p");
    modes.textContent = `Planner：${intelligence.planner || "off"}；证据：${intelligence.evidence || "off"}；编排：${intelligence.orchestrator || "off"}；验收：${intelligence.verifier || "off"}`;
    panel.append(modes);
    panel.append(Object.assign(document.createElement("small"), { textContent: "报告只统计当前账号的运行元数据，不读取对话或资料正文。达到门槛前不会自动开启 Active。" }));
    els.runDetail.append(panel);
  },
  renderTrialMetrics(els, data) {
    const { total = {}, testers = [], citation_issue_reasons: issueReasons = {}, privacy = "" } = data;
    const percent = (value) => value == null ? "暂无数据" : `${(value * 100).toFixed(1)}%`;
    const metric = (value, suffix = "") => value == null ? "暂无数据" : `${value}${suffix}`;
    els.runDetail.replaceChildren();
    const panel = document.createElement("section"); panel.className = "retrieval-diagnostics";
    panel.append(Object.assign(document.createElement("h3"), { textContent: "试用概览" }));
    panel.append(Object.assign(document.createElement("p"), { textContent: "仅管理员可见，用于观察邀请制试用的稳定性和反馈质量。" }));
    const grid = document.createElement("div"); grid.className = "diagnostic-metrics";
    [["测试用户", total.testers || 0], ["Run", total.runs || 0], ["完成率", percent(total.completion_rate)], ["P95 时延", metric(total.p95_seconds, " 秒")], ["有帮助率", percent(total.helpful_rate)], ["引用准确率", percent(total.citation_accuracy)], ["回答反馈", total.feedback_count || 0], ["Token 估算", total.token_estimate || 0]].forEach(([label, value]) => {
      const item = document.createElement("div"); item.className = "diagnostic-metric";
      item.append(Object.assign(document.createElement("span"), { textContent: label }), Object.assign(document.createElement("strong"), { textContent: value })); grid.append(item);
    });
    panel.append(grid);
    const reasonLabels = { wrong_document: "文档不相关", wrong_passage: "命中片段不相关", outdated: "资料已过期", answer_misused: "回答误用了资料", missing_evidence: "缺少应有资料" };
    const reasons = document.createElement("p");
    reasons.textContent = Object.keys(issueReasons).length ? `引用问题：${Object.entries(issueReasons).map(([code, count]) => `${reasonLabels[code] || code} ${count} 条`).join("；")}` : "引用问题：暂无";
    panel.append(reasons);
    const title = document.createElement("h4"); title.textContent = "受邀用户"; panel.append(title);
    if (!testers.length) {
      panel.append(Object.assign(document.createElement("p"), { textContent: "暂时没有完成注册的受邀用户。" }));
    } else {
      const list = document.createElement("div"); list.className = "diagnostic-document-list";
      testers.forEach((tester) => {
        const item = document.createElement("div"); item.className = "diagnostic-document";
        const name = document.createElement("strong"); name.textContent = `${tester.name} · ${tester.email}`;
        const runs = document.createElement("small"); runs.textContent = `Run ${tester.runs} · 完成率 ${percent(tester.completion_rate)} · P95 ${metric(tester.p95_seconds, " 秒")}`;
        const feedback = document.createElement("small"); feedback.textContent = `有帮助率 ${percent(tester.helpful_rate)}（${tester.feedback_count} 条）· 引用准确率 ${percent(tester.citation_accuracy)}（${tester.citation_feedback_count} 条）· Token ${tester.token_estimate}`;
        item.append(name, runs, feedback); list.append(item);
      });
      panel.append(list);
    }
    panel.append(Object.assign(document.createElement("small"), { textContent: privacy }));
    els.runDetail.append(panel);
  },
};
