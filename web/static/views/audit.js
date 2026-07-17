window.AgentAuditView = {
  renderRunList(state, els, onSelect) {
    els.runList.innerHTML = "";
    const labels = { completed: "已完成", failed: "失败", cancelled: "已取消", awaiting_confirmation: "待确认", running: "运行中" };
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
    const { run, events, steps, artifact } = data;
    const parse = (value, fallback) => { try { return JSON.parse(value || ""); } catch (_error) { return fallback; } };
    const context = parse(run.execution_context, {});
    const reflection = parse(run.reflection_snapshot, {});
    const plan = steps?.length ? steps : parse(run.plan_snapshot, []);
    const modes = context.execution_modes || {};
    const routeSummary = context.route_summary || {};
    const elapsed = run.completed_at ? `${Math.max(0, Math.round((run.completed_at - run.started_at) / 1e9 * 10) / 10)} 秒` : "运行中";
    const skills = parse(run.skill_snapshot, []).map((skill) => skill.name).join("、") || "无";
    const tools = context.tools?.map((tool) => tool.name).join("、") || "无";
    const trace = events.filter((event) => ["tool_call", "tool_result", "tool_error"].includes(event.type)).map((event) => event.type).join(" → ") || "未调用工具";
    const reflectionText = reflection.applied ? `${reflection.summary || "已完成"}${reflection.revision_count ? `，已修订 ${reflection.revision_count} 次` : ""}` : "未触发";
    const modesText = `资料：${modes.source || "general"}｜知识库：${modes.knowledge || "auto"}（${routeSummary.knowledge_matches ?? context.knowledge_match_count ?? 0} 条）｜网络：${modes.web || "auto"}｜文件：${modes.file || "auto"}｜记忆：${routeSummary.memory_count ?? context.memories?.length ?? 0} 条`;
    els.runDetail.textContent = `模型：${run.model}\n任务档位：${context.task_tier || "standard"}\n路由：${context.model_route_reason || "未记录"}\n执行方式：${modesText}\n输出预算：${context.max_output_tokens || "未记录"}\n状态：${run.status}\n执行阶段：${run.run_phase || "未记录"}\n耗时：${elapsed}\n技能：${skills}\n计划：${plan.length ? plan.map((step) => `${step.title}（${step.status}）`).join(" → ") : "无"}\n允许工具：${tools}\n工具判断：${context.tool_route_reason || "未记录"}\n工具执行：${trace}\n质量检查：${reflectionText}${run.error ? `\n错误：${run.error}` : ""}`;
    if (artifact) {
      const link = document.createElement("button"); link.type = "button"; link.className = "artifact-link"; link.textContent = `下载文件：${artifact.filename}`;
      link.addEventListener("click", () => onDownload(artifact, link)); els.runDetail.appendChild(link);
    }
    if (context.knowledge_refs?.length) {
      const feedback = document.createElement("div"); feedback.className = "confirmation-actions run-feedback"; feedback.append(Object.assign(document.createElement("span"), { textContent: "本次引用是否准确？" }));
      [[true, "引用准确"], [false, "引用有误"]].forEach(([correct, text]) => { const button = document.createElement("button"); button.type = "button"; button.className = "secondary"; button.textContent = text; button.addEventListener("click", () => onFeedback(run.id, correct, feedback, button)); feedback.append(button); });
      els.runDetail.appendChild(feedback);
    }
    if (["running", "awaiting_confirmation"].includes(run.status)) {
      const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "secondary"; cancel.textContent = run.status === "awaiting_confirmation" ? "取消待确认任务" : "取消运行"; cancel.addEventListener("click", () => onCancel(run.id, cancel)); els.runDetail.appendChild(cancel);
    }
  },
};
