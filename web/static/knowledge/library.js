window.AgentKnowledgeLibrary = {
  renderProjectOptions(state, els, escape) {
    const spaces = state.folders.filter((folder) => folder.section === "project");
    const previous = els.knowledgeProjectSelect.value;
    els.knowledgeProjectSelect.innerHTML = `<option value="">全部项目</option>${spaces.map((space) => `<option value="${escape(space.id)}">${escape(space.name)}</option>`).join("")}`;
    els.knowledgeProjectSelect.value = spaces.some((space) => space.id === previous) ? previous : "";
    els.knowledgeProjectSelect.disabled = !spaces.length;
    return spaces;
  },
  syncScope(els) {
    const project = els.knowledgeScopeSelect.value === "project";
    els.knowledgeProjectSelect.classList.toggle("hidden", !project);
    els.knowledgeProjectSelect.required = false;
  },
  renderDocuments(state, els, escape, { onEdit, onDelete }) {
    els.knowledgeList.innerHTML = "";
    const scope = els.knowledgeScopeSelect.value;
    const projectId = els.knowledgeProjectSelect.value;
    const filtered = state.knowledgeDocuments.filter((knowledgeDocument) => knowledgeDocument.scope === scope && (scope !== "project" || !projectId || knowledgeDocument.project_space_id === projectId));
    filtered.forEach((knowledgeDocument) => {
      const card = window.document.createElement("article");
      card.className = "capability-card knowledge-card";
      const size = knowledgeDocument.size_bytes < 1024 * 1024 ? `${Math.ceil(knowledgeDocument.size_bytes / 1024)} KB` : `${(knowledgeDocument.size_bytes / 1024 / 1024).toFixed(1)} MB`;
      card.innerHTML = `<h3>${escape(knowledgeDocument.filename)}</h3><p>${knowledgeDocument.chunk_count} 个检索片段 · ${size}</p><div class="card-footer"><span class="status-pill">${knowledgeDocument.scope === "project" ? `项目专属 · ${escape(knowledgeDocument.project_space_name || "项目空间")}` : "通用知识库"}</span><span class="status-pill">来源：${knowledgeDocument.upload_origin === "project_space" ? "项目空间" : "知识库"}</span><button class="skill-action knowledge-edit" type="button">编辑</button><button class="skill-action danger" type="button">删除</button></div>`;
      card.querySelector(".knowledge-edit").addEventListener("click", () => onEdit(knowledgeDocument));
      card.querySelector(".danger").addEventListener("click", () => onDelete(knowledgeDocument));
      els.knowledgeList.appendChild(card);
    });
    if (!filtered.length) els.knowledgeList.innerHTML = '<div class="empty-state"><h2>没有符合当前筛选条件的资料</h2><p>可切换资料类型或所属项目查看。</p></div>';
  },
  renderSearchResults(els, results, escape) {
    els.knowledgeResults.innerHTML = "";
    els.knowledgeResults.classList.remove("hidden");
    results.forEach((result) => {
      const item = window.document.createElement("article");
      item.className = "knowledge-result";
      item.innerHTML = `<strong>${escape(result.filename)}</strong><p>${escape(result.excerpt)}</p>`;
      els.knowledgeResults.appendChild(item);
    });
    if (!results.length) els.knowledgeResults.textContent = "没有匹配资料。";
  },
};
