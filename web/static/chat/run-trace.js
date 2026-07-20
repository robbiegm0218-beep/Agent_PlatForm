window.AgentRunTrace = {
  appendAssistantMessage(els) {
    const wrapper = document.createElement("article");
    wrapper.className = "message assistant";
    wrapper.innerHTML = `
      <div class="message-role">Agent_Platform</div>
      <section class="reasoning-summary hidden">
        <button class="reasoning-summary-toggle" type="button" aria-expanded="false"><span>推理摘要</span><span class="reasoning-summary-chevron">⌄</span></button>
        <div class="reasoning-summary-body hidden"><ul></ul></div>
      </section>
      <section class="execution-trace">
        <button class="execution-trace-toggle" type="button" aria-expanded="true"><span class="execution-trace-title">执行过程</span><span class="execution-trace-time">预计剩余 30 秒</span><span class="execution-trace-chevron">⌃</span></button>
        <div class="execution-trace-body"><ol class="execution-trace-list"><li>正在准备运行</li></ol></div>
      </section>
      <div class="answer-label">最终回答</div>
      <div class="message-content"></div>
    `;
    els.messages.appendChild(wrapper);
    els.messages.scrollTop = els.messages.scrollHeight;
    const traceToggle = wrapper.querySelector(".execution-trace-toggle");
    const traceBody = wrapper.querySelector(".execution-trace-body");
    traceToggle.addEventListener("click", () => {
      const expanded = traceToggle.getAttribute("aria-expanded") === "true";
      traceToggle.setAttribute("aria-expanded", String(!expanded));
      traceBody.classList.toggle("hidden", expanded);
    });
    const reasoning = wrapper.querySelector(".reasoning-summary");
    const reasoningToggle = wrapper.querySelector(".reasoning-summary-toggle");
    const reasoningBody = wrapper.querySelector(".reasoning-summary-body");
    reasoningToggle.addEventListener("click", () => {
      const expanded = reasoningToggle.getAttribute("aria-expanded") === "true";
      reasoningToggle.setAttribute("aria-expanded", String(!expanded));
      reasoningBody.classList.toggle("hidden", expanded);
    });
    return {
      wrapper, traceToggle, traceTitle: wrapper.querySelector(".execution-trace-title"),
      traceTime: wrapper.querySelector(".execution-trace-time"), traceList: wrapper.querySelector(".execution-trace-list"),
      reasoning, reasoningToggle, reasoningBody, reasoningList: reasoning.querySelector("ul"),
      content: wrapper.querySelector(".message-content"),
    };
  },

  renderReasoningSummary(assistant, items) {
    if (!Array.isArray(items) || !items.length) return;
    const existing = new Set([...assistant.reasoningList.children].map((item) => item.textContent));
    items.slice(0, 5).filter((text) => !existing.has(text)).forEach((text) => {
      const item = document.createElement("li");
      item.textContent = text;
      assistant.reasoningList.appendChild(item);
    });
    assistant.reasoning.classList.remove("hidden");
  },

  appendExecutionTrace(els, assistant, summary) {
    const last = assistant.traceList.lastElementChild;
    if (last?.textContent === summary) return;
    const item = document.createElement("li");
    item.textContent = summary;
    assistant.traceList.appendChild(item);
    assistant.traceTitle.textContent = `执行过程 · ${assistant.traceList.children.length} 步`;
    els.messages.scrollTop = els.messages.scrollHeight;
  },

  startCountdown(assistant) {
    const startedAt = Date.now();
    const update = () => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      const remaining = Math.max(0, 30 - elapsed);
      assistant.traceTime.textContent = remaining ? `预计剩余 ${remaining} 秒 · 已用 ${elapsed} 秒` : `正在继续处理 · 已用 ${elapsed} 秒`;
    };
    update();
    const timer = window.setInterval(update, 1000);
    return {
      stop(label = "已完成") {
        window.clearInterval(timer);
        const elapsed = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
        assistant.traceTime.textContent = `${label} · 用时 ${elapsed} 秒`;
      },
      timer,
    };
  },

  appendSavedRunTrace(wrapper, detail) {
    if (wrapper.querySelector(".execution-trace")) return;
    const { run = {}, events = [] } = detail;
    const parse = (value) => { try { return JSON.parse(value || "{}"); } catch (_error) { return {}; } };
    const summaryItems = events
      .filter((event) => event.type === "reasoning_summary")
      .flatMap((event) => parse(event.payload).items || [])
      .filter((item) => typeof item === "string" && item.trim())
      .slice(0, 5);
    events.filter((event) => event.type === "provider_reasoning_available").forEach((event) => {
      const characters = Number(parse(event.payload).characters || 0);
      if (characters) summaryItems.push(`模型本次返回了推理数据（${characters} 字符）；原始内容不展示，仅保留可审计记录。`);
    });
    const labels = {
      skill_routed: (payload) => `技能路由：${(payload.skills || []).join("、") || "未使用技能"}`,
      knowledge_retrieved: (payload) => `本地知识库命中 ${payload.count || 0} 个资料片段`,
      knowledge_no_match: () => "本地知识库未命中，回答已标注为建议或待验证项",
      knowledge_not_needed: () => "本次问题未使用本地资料",
      plan_created: (payload) => `执行计划：${(payload.steps || []).length} 个步骤`,
      task_frame_planned: (payload) => `任务理解：${payload.status === "model" ? "模型已生成" : "已使用安全回退"}`,
      evidence_assessed: (payload) => `资料证据：${payload.summary?.decision === "sufficient" ? "已覆盖当前需求" : "仍有待补充项"}`,
      orchestrator_transition: (payload) => `执行状态：${payload.to || "处理中"}`,
      orchestrator_budget: (payload) => `本轮预算：模型 ${payload.model_calls || 0} 次，工具 ${payload.tool_calls || 0} 次`,
      task_verified: (payload) => `任务验收：${payload.passed ? "通过" : payload.summary || "发现待补充项"}`,
      model_role_selected: (payload) => `模型角色：${payload.role || "executor"} · ${payload.model || "未记录"}`,
      next_action_assessed: (payload) => `下一步建议：${payload.type || "draft_answer"}（已校验）`,
      clarification_requested: (payload) => `等待补充信息：${payload.reason || "任务关键信息不足"}`,
      model_request: (payload) => `已选择模型：${payload.model || run.model || "未记录"}`,
      tool_call: (payload) => `正在调用工具：${payload.tool_name || payload.tool_id || "本地工具"}${payload.purpose ? `（${payload.purpose}）` : ""}`,
      tool_result: (payload) => `工具完成：${payload.tool_name || payload.tool_id || "本地工具"}${payload.evidence_gap_status ? `（${payload.evidence_gap_status}）` : ""}`,
      tool_error: (payload) => `工具失败：${payload.tool_name || payload.tool_id || "本地工具"}`,
      reflection_started: () => "正在进行结果质量检查",
      reflection_revised: () => "已根据质量检查修订回答",
      reflection_completed: (payload) => `质量检查：${payload.summary || "已完成"}`,
      provider_reasoning_available: () => "模型提供了推理数据，已记录可审计摘要",
      completed: () => "已生成最终回答",
      failed: () => "运行失败",
      cancelled: () => "运行已取消",
    };
    const modelEvent = events.find((event) => event.type === "model_request");
    const steps = ["正在准备运行"];
    if (modelEvent || run.model) steps.push(labels.model_request(modelEvent ? parse(modelEvent.payload) : { model: run.model }));
    events
      .filter((event) => labels[event.type] && event.type !== "model_request")
      .map((event) => labels[event.type](parse(event.payload)))
      .forEach((text) => { if (steps.at(-1) !== text) steps.push(text); });
    if (!steps.length) return;

    const insertBefore = wrapper.querySelector(".answer-label");
    const addToggle = (toggle, body) => toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!expanded));
      body.classList.toggle("hidden", expanded);
    });
    const nodes = [];
    const context = parse(run.execution_context);
    const taskFrame = context.task_frame?.frame;
    if (taskFrame) {
      const section = document.createElement("section"); section.className = "run-audit-layer";
      const toggle = document.createElement("button"); toggle.type = "button"; toggle.className = "run-audit-layer-toggle"; toggle.setAttribute("aria-expanded", "false"); toggle.textContent = "任务理解";
      const body = document.createElement("div"); body.className = "run-audit-layer-body hidden";
      const items = [taskFrame.goal, ...(taskFrame.deliverables || []).map((item) => `交付：${item.description}`), ...(taskFrame.constraints || []).map((item) => `约束：${item.description}`)].filter(Boolean);
      body.textContent = items.join("\n"); section.append(toggle, body); addToggle(toggle, body); nodes.push(section);
    }
    const ledger = context.evidence_ledger;
    if (ledger) {
      const section = document.createElement("section"); section.className = "run-audit-layer";
      const toggle = document.createElement("button"); toggle.type = "button"; toggle.className = "run-audit-layer-toggle"; toggle.setAttribute("aria-expanded", "false"); toggle.textContent = ledger.decision === "sufficient" ? "证据与来源：已覆盖" : "证据与缺口：待补充";
      const body = document.createElement("div"); body.className = "run-audit-layer-body hidden";
      const missing = ledger.missing_requirement_ids || []; body.textContent = missing.length ? `待补充：${missing.join("、")}` : `已使用 ${ledger.items?.length || 0} 条授权资料证据`;
      section.append(toggle, body); addToggle(toggle, body); nodes.push(section);
      if (ledger.decision === "clarify") {
        const card = document.createElement("section"); card.className = "run-clarification-card";
        const labels = (ledger.missing_requirement_ids || []).join("、") || "任务范围或关键资料";
        card.textContent = `需要你补充：${labels}。补充后可在当前对话继续，Agent 会基于已保存的运行上下文重新处理。`;
        nodes.push(card);
      }
    }
    const verificationEvent = [...events].reverse().find((event) => event.type === "task_verified");
    if (verificationEvent) {
      const verification = parse(verificationEvent.payload);
      const section = document.createElement("section"); section.className = "run-audit-layer";
      const toggle = document.createElement("button"); toggle.type = "button"; toggle.className = "run-audit-layer-toggle"; toggle.setAttribute("aria-expanded", "false"); toggle.textContent = verification.passed ? "任务验收：通过" : "任务验收：待补充";
      const body = document.createElement("div"); body.className = "run-audit-layer-body hidden";
      const gaps = verification.missing_evidence || [];
      body.textContent = [verification.summary, gaps.length ? `待补充证据：${gaps.join("、")}` : ""].filter(Boolean).join("\n");
      section.append(toggle, body); addToggle(toggle, body); nodes.push(section);
    }
    if (summaryItems.length) {
      const reasoning = document.createElement("section"); reasoning.className = "reasoning-summary";
      const toggle = document.createElement("button"); toggle.type = "button"; toggle.className = "reasoning-summary-toggle"; toggle.setAttribute("aria-expanded", "false"); toggle.innerHTML = "<span>推理摘要（已保存）</span><span class=\"reasoning-summary-chevron\">⌄</span>";
      const body = document.createElement("div"); body.className = "reasoning-summary-body hidden";
      const list = document.createElement("ul"); summaryItems.forEach((item) => list.append(Object.assign(document.createElement("li"), { textContent: item }))); body.append(list);
      reasoning.append(toggle, body); addToggle(toggle, body); nodes.push(reasoning);
    }
    const trace = document.createElement("section"); trace.className = "execution-trace";
    const elapsed = run.completed_at ? Math.max(0, Math.round((run.completed_at - run.started_at) / 1e9)) : 0;
    const toggle = document.createElement("button"); toggle.type = "button"; toggle.className = "execution-trace-toggle"; toggle.setAttribute("aria-expanded", "false"); toggle.innerHTML = `<span class="execution-trace-title">执行过程 · ${steps.length} 步</span><span class="execution-trace-time">${run.completed_at ? `已完成 · 用时 ${elapsed} 秒` : "运行中"}</span><span class="execution-trace-chevron">⌃</span>`;
    const body = document.createElement("div"); body.className = "execution-trace-body hidden";
    const list = document.createElement("ol"); list.className = "execution-trace-list"; steps.forEach((item) => list.append(Object.assign(document.createElement("li"), { textContent: item }))); body.append(list);
    trace.append(toggle, body); addToggle(toggle, body); nodes.push(trace);
    nodes.forEach((node) => insertBefore.before(node));
  },
};
