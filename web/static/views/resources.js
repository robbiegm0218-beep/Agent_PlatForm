window.AgentResourceViews = {
  renderMemories(state, els, escape, { onUpdate, onDelete }) {
    els.memoryList.innerHTML = "";
    if (!state.memories.length) {
      els.memoryList.innerHTML = '<div class="empty-state"><h2>暂无长期记忆</h2><p>明确确认保存的偏好、项目事实和决策会显示在这里。</p></div>';
      return;
    }
    const labels = { preference: "个人偏好", project_fact: "项目事实", decision: "已确认决策" };
    state.memories.forEach((memory) => {
      const card = document.createElement("article");
      const scope = memory.scope_type === "project" ? `项目：${state.folders.find((folder) => folder.id === memory.scope_id)?.name || "已删除项目"}` : "所有对话";
      const status = memory.effective_status === "expired" ? "已过期" : memory.status === "active" ? "使用中" : "已停用";
      card.className = "capability-card memory-card";
      card.innerHTML = `<div><span class="status-pill">${labels[memory.kind] || "长期记忆"}</span></div><h3>${escape(memory.content)}</h3><p>${escape(scope)} · 已使用 ${memory.use_count} 次 · ${status}</p><div class="card-footer memory-actions"><label class="switch"><input type="checkbox" ${memory.status === "active" ? "checked" : ""} ${memory.effective_status === "expired" ? "disabled" : ""}/><span></span></label><div><button class="skill-action memory-edit" type="button">修改</button><button class="skill-action danger memory-delete" type="button">删除</button></div></div>`;
      card.querySelector("input").addEventListener("change", (event) => onUpdate(memory, { status: event.target.checked ? "active" : "disabled" }));
      card.querySelector(".memory-edit").addEventListener("click", () => onUpdate(memory, { prompt: true }));
      card.querySelector(".memory-delete").addEventListener("click", () => onDelete(memory));
      els.memoryList.appendChild(card);
    });
  },
  renderArtifacts(state, els, escape, { onDownload, onDelete }) {
    els.artifactsGrid.innerHTML = "";
    els.artifactsGrid.classList.add("artifacts-grid");
    if (!state.artifacts.length) { els.artifactsGrid.innerHTML = '<div class="empty-state"><h2>暂无产物</h2><p>在对话中启用文件生成技能后，确认生成的文件会出现在这里。</p></div>'; return; }
    state.artifacts.forEach((artifact) => {
      const isExcel = artifact.kind === "xlsx";
      const date = new Date(artifact.created_at / 1e6).toLocaleString("zh-CN");
      const title = artifact.filename.startsWith("artifact_") ? `${isExcel ? "Excel 文件" : "Markdown 文件"} · ${date}` : artifact.filename;
      const card = document.createElement("article");
      card.className = "capability-card artifact-card";
      card.innerHTML = `<div class="artifact-card-header"><span class="artifact-type-icon ${isExcel ? "excel" : "markdown"}">${isExcel ? "▦" : "≡"}</span><div class="artifact-heading"><h3 title="${escape(artifact.filename)}">${escape(title)}</h3><p class="artifact-file-name">${escape(artifact.filename)}</p></div></div><p class="artifact-summary">${escape(artifact.summary || "由对话确认后生成，可随时下载或删除。")}</p><div class="artifact-meta"><span>创建于 ${date}</span><span>已确认生成</span></div><div class="card-footer artifact-footer"><span class="artifact-kind-tag">${isExcel ? "XLSX" : "MD"}</span><div class="artifact-actions"><button class="skill-action artifact-download" type="button">下载</button><button class="skill-action danger artifact-delete" type="button">删除</button></div></div>`;
      card.querySelector(".artifact-download").addEventListener("click", () => onDownload(artifact));
      card.querySelector(".artifact-delete").addEventListener("click", () => onDelete(artifact));
      els.artifactsGrid.appendChild(card);
    });
  },
};
