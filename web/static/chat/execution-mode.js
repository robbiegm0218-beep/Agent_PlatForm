window.AgentExecutionMode = function createExecutionMode({ state, els, api, getChatContent }) {
  let routePreviewTimer;
  let routePreviewSequence = 0;

  function syncEvidenceModeControls() {
    const source = els.sourceModeSelect.value;
    const overrides = {
      local_only: { knowledge: "required", web: "off" },
      web_only: { knowledge: "off", web: "required" },
      mixed: { knowledge: "required", web: "required" },
    };
    const override = overrides[source];
    if (override) {
      els.knowledgeModeSelect.value = override.knowledge;
      els.webModeSelect.value = override.web;
    } else {
      els.knowledgeModeSelect.value = "auto";
      els.webModeSelect.value = "auto";
    }
  }

  function renderModelConfigHint() {
    const modeLabels = { auto: "深度自动", quick: "快速", standard: "标准", deep: "深度" };
    const model = state.models.find((item) => item.id === els.modelSelect.value);
    const modelLabel = model?.id === "auto" || !model ? "智能选择" : model.name;
    els.modelConfigHint.textContent = `${modelLabel} · ${modeLabels[els.taskModeSelect.value] || "自动"}`;
  }

  function renderExecutionModeHint() {
    syncEvidenceModeControls();
    const fileLabels = { off: "不读取工作区", auto: "按需读取文件", required: "优先读取文件" };
    const sourceLabels = { general: "智能选择", local_only: "只用知识库", web_only: "只用网络", mixed: "知识库和网络" };
    els.executionModeHint.textContent = `${sourceLabels[els.sourceModeSelect.value]} · ${fileLabels[els.fileModeSelect.value]}`;
  }

  function scheduleRoutePreview() {
    window.clearTimeout(routePreviewTimer);
    syncEvidenceModeControls();
    const content = getChatContent();
    if (!content || !state.token) {
      renderExecutionModeHint();
      return;
    }
    const sequence = ++routePreviewSequence;
    routePreviewTimer = window.setTimeout(async () => {
      try {
        const preview = await api("/api/route-preview", {
          method: "POST",
          body: JSON.stringify({
            content,
            thread_id: state.currentThreadId,
            model: els.modelSelect.value,
            task_mode: els.taskModeSelect.value,
            source_mode: els.sourceModeSelect.value,
            knowledge_mode: els.knowledgeModeSelect.value,
            web_mode: els.webModeSelect.value,
            file_mode: els.fileModeSelect.value,
            skill_ids: state.selectedSkillIds.length ? state.selectedSkillIds : undefined,
          }),
        });
        if (sequence !== routePreviewSequence || !preview.ready) return;
        const tools = preview.allowed_tools?.map((tool) => tool.name).join("、") || "无工具";
        const errors = preview.required_errors?.length ? `；${preview.required_errors.join("；")}` : "";
        els.executionModeHint.textContent = `${preview.task_tier} · 资料 ${preview.knowledge_matches} 条 · ${tools}${errors}`;
      } catch (_error) {
        if (sequence === routePreviewSequence) renderExecutionModeHint();
      }
    }, 260);
  }

  return { renderModelConfigHint, renderExecutionModeHint, scheduleRoutePreview };
};
