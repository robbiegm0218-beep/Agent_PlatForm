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
  renderDocuments(state, els, escape, { onPreview, onEdit, onDelete, onHistory, onStructure, onChunks }) {
    els.knowledgeList.innerHTML = "";
    const scope = els.knowledgeScopeSelect.value;
    const projectId = els.knowledgeProjectSelect.value;
    const filtered = state.knowledgeDocuments.filter((knowledgeDocument) => knowledgeDocument.scope === scope && (scope !== "project" || !projectId || knowledgeDocument.project_space_id === projectId));
    filtered.forEach((knowledgeDocument) => {
      const card = window.document.createElement("article");
      card.className = "capability-card knowledge-card";
      const size = knowledgeDocument.size_bytes < 1024 * 1024 ? `${Math.ceil(knowledgeDocument.size_bytes / 1024)} KB` : `${(knowledgeDocument.size_bytes / 1024 / 1024).toFixed(1)} MB`;
      const statusLabels = { ready: "可用", running: "处理中", partial: "部分可用", failed: "失败" };
      const processingStatus = knowledgeDocument.processing_status || "ready";
      card.innerHTML = `<h3>${escape(knowledgeDocument.filename)}</h3><p>${knowledgeDocument.chunk_count} 个检索片段 · ${knowledgeDocument.parsed_block_count || 0} 个结构块 · ${size}</p><div class="knowledge-card-status"><span class="processing-status processing-status-${escape(processingStatus)}">${escape(statusLabels[processingStatus] || processingStatus)}</span><span class="status-pill">切分 v${knowledgeDocument.active_chunk_version || 1} · ${escape(knowledgeDocument.chunk_preset || "standard")}</span></div><div class="card-footer"><span class="status-pill">${knowledgeDocument.scope === "project" ? `项目专属 · ${escape(knowledgeDocument.project_space_name || "项目空间")}` : "通用知识库"}</span><span class="status-pill">来源：${knowledgeDocument.upload_origin === "project_space" ? "项目空间" : "知识库"}</span><button class="skill-action knowledge-history" type="button">处理记录</button><button class="skill-action knowledge-structure" type="button">解析结果</button><button class="skill-action knowledge-chunks" type="button">切分结果</button><button class="skill-action knowledge-preview" type="button">原文预览</button><button class="skill-action knowledge-edit" type="button">编辑</button><button class="skill-action danger" type="button">删除</button></div>`;
      card.querySelector(".knowledge-history").addEventListener("click", () => onHistory(knowledgeDocument));
      card.querySelector(".knowledge-structure").addEventListener("click", () => onStructure(knowledgeDocument));
      card.querySelector(".knowledge-chunks").addEventListener("click", () => onChunks(knowledgeDocument));
      card.querySelector(".knowledge-preview").addEventListener("click", () => onPreview(knowledgeDocument));
      card.querySelector(".knowledge-edit").addEventListener("click", () => onEdit(knowledgeDocument));
      card.querySelector(".danger").addEventListener("click", () => onDelete(knowledgeDocument));
      els.knowledgeList.appendChild(card);
    });
    if (!filtered.length) els.knowledgeList.innerHTML = '<div class="empty-state"><h2>没有符合当前筛选条件的资料</h2><p>可切换资料类型或所属项目查看。</p></div>';
  },
  renderProcessingRuns(els, runs, escape, title = "最近处理", onRetry = null) {
    const statusLabels = { ready: "可用", running: "处理中", partial: "部分可用", failed: "失败" };
    const stageLabels = { uploaded: "已上传", validating: "校验", parsing: "解析", normalized: "规范化", chunking: "切分", lexical_indexing: "关键词索引", embedding: "向量索引", ready: "完成" };
    els.knowledgeProcessingTitle.textContent = title;
    els.knowledgeProcessingList.innerHTML = "";
    runs.forEach((run) => {
      const item = window.document.createElement("article");
      item.className = `knowledge-processing-run processing-run-${run.status}`;
      const timestamp = Number(run.completed_at || run.updated_at || run.started_at || 0);
      const time = timestamp ? new Date(timestamp / 1e6).toLocaleString() : "";
      const error = run.error_message ? `<p class="knowledge-processing-error">${escape(run.error_message)}</p>` : "";
      const eventList = Array.isArray(run.events) ? `<ol>${run.events.map((event) => `<li><span>${escape(stageLabels[event.stage] || event.stage)}</span><strong>${escape(event.status)}</strong></li>`).join("")}</ol>` : "";
      const retry = run.status === "failed" && onRetry ? '<button class="knowledge-processing-retry" type="button">重新选择文件</button>' : "";
      item.innerHTML = `<div><strong>${escape(run.filename || "知识资料")}</strong><span class="processing-status processing-status-${escape(run.status)}">${escape(statusLabels[run.status] || run.status)}</span></div><p>${escape(stageLabels[run.current_stage] || run.current_stage)} · ${run.chunk_count || 0} 个片段${time ? ` · ${escape(time)}` : ""}</p>${error}${eventList}${retry}`;
      item.querySelector(".knowledge-processing-retry")?.addEventListener("click", () => onRetry(run));
      els.knowledgeProcessingList.appendChild(item);
    });
    if (!runs.length) els.knowledgeProcessingList.textContent = "还没有知识处理记录。";
    els.knowledgeProcessingPanel.classList.remove("hidden");
  },
  renderStructure(els, data, escape) {
    const typeLabels = { heading: "标题", paragraph: "段落", list: "列表", table: "表格", sheet: "工作表", image_ocr: "图片 OCR" };
    const blocks = Array.isArray(data.blocks) ? data.blocks : [];
    els.knowledgeProcessingTitle.textContent = `解析结果：${data.document?.filename || "知识资料"}`;
    els.knowledgeProcessingList.innerHTML = "";
    if (!data.available) {
      els.knowledgeProcessingList.innerHTML = `<div class="knowledge-structure-empty">${escape(data.message || "暂无结构化解析结果。")}</div>`;
      els.knowledgeProcessingPanel.classList.remove("hidden");
      return;
    }
    const layout = window.document.createElement("div");
    layout.className = "knowledge-structure-layout";
    const tree = window.document.createElement("div");
    tree.className = "knowledge-structure-tree";
    tree.innerHTML = `<h4>结构块（${blocks.length}）</h4>`;
    blocks.forEach((block) => {
      const item = window.document.createElement("details");
      item.className = `knowledge-structure-block block-${block.block_type}`;
      const section = Array.isArray(block.section_path) && block.section_path.length ? block.section_path.join(" / ") : "文档根节点";
      const source = Object.entries(block.source_location || {}).map(([key, value]) => `${key}: ${value}`).join(" · ");
      item.innerHTML = `<summary><span>${escape(typeLabels[block.block_type] || block.block_type)}</span><strong>${escape(section)}</strong></summary><p>${escape(block.text)}</p>${source ? `<small>${escape(source)}</small>` : ""}`;
      tree.appendChild(item);
    });
    const markdown = window.document.createElement("div");
    markdown.className = "knowledge-structure-markdown";
    markdown.innerHTML = `<h4>统一 Markdown（预览/调试）</h4><pre>${escape(data.markdown || "")}</pre>`;
    layout.append(tree, markdown);
    els.knowledgeProcessingList.appendChild(layout);
    els.knowledgeProcessingPanel.classList.remove("hidden");
  },
  renderChunks(els, data, escape, { onRechunk, onReprocess, onRollback }) {
    const document = data.document || {};
    const chunks = Array.isArray(data.chunks) ? data.chunks : [];
    const versions = Array.isArray(data.versions) ? data.versions : [];
    els.knowledgeProcessingTitle.textContent = `切分结果：${document.filename || "知识资料"}`;
    els.knowledgeProcessingList.innerHTML = "";
    const toolbar = window.document.createElement("div");
    toolbar.className = "knowledge-chunk-toolbar";
    const presetLabels = { standard: "标准", long_document: "长文档", table_dense: "表格密集" };
    const options = (data.presets || []).map((preset) => `<option value="${escape(preset.id)}"${preset.id === document.chunk_preset ? " selected" : ""}>${escape(presetLabels[preset.id] || preset.id)} · ${preset.target_tokens}/${preset.max_tokens} Token</option>`).join("");
    const archived = versions.filter((version) => version.status === "archived");
    toolbar.innerHTML = `<div><strong>活动版本 v${document.active_chunk_version || 1}</strong><span>${escape(document.chunk_policy_version || "fixed-char-v1")} · ${escape(presetLabels[document.chunk_preset] || document.chunk_preset || "标准")}</span></div>${data.manageable ? `<label>处理预设<select class="knowledge-chunk-preset">${options}</select></label><button class="knowledge-reparse" type="button">重新解析</button>${data.structure_available ? `<button class="knowledge-rechunk" type="button">重新切分</button>` : ""}<button class="knowledge-reindex" type="button">重建索引</button>` : ""}${data.manageable && archived.length ? `<label>历史版本<select class="knowledge-chunk-version">${archived.map((version) => `<option value="${version.version}">v${version.version} · ${escape(presetLabels[version.preset] || version.preset)} · ${version.chunk_count} 片段</option>`).join("")}</select></label><button class="knowledge-chunk-rollback" type="button">回滚</button>` : ""}`;
    toolbar.querySelector(".knowledge-rechunk")?.addEventListener("click", () => onRechunk(toolbar.querySelector(".knowledge-chunk-preset").value));
    toolbar.querySelector(".knowledge-reparse")?.addEventListener("click", () => onReprocess?.("reparse", toolbar.querySelector(".knowledge-chunk-preset").value));
    toolbar.querySelector(".knowledge-reindex")?.addEventListener("click", () => onReprocess?.("reindex", toolbar.querySelector(".knowledge-chunk-preset").value));
    toolbar.querySelector(".knowledge-chunk-rollback")?.addEventListener("click", () => onRollback(Number(toolbar.querySelector(".knowledge-chunk-version").value)));
    els.knowledgeProcessingList.appendChild(toolbar);
    const list = window.document.createElement("div");
    list.className = "knowledge-chunk-list";
    chunks.forEach((chunk) => {
      const item = window.document.createElement("details");
      item.className = "knowledge-chunk-item";
      const section = Array.isArray(chunk.section_path) && chunk.section_path.length ? chunk.section_path.join(" / ") : "文档根节点";
      const source = Object.entries(chunk.source_location || {}).map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : value}`).join(" · ");
      item.innerHTML = `<summary><strong>片段 ${Number(chunk.position) + 1}</strong><span>${chunk.token_count} Token · 重叠 ${chunk.overlap_tokens} · ${escape(section)}</span></summary><p>${escape(chunk.content)}</p><small>${escape(source || "无额外来源位置")} · ${chunk.block_ids.length} 个结构块</small>`;
      list.appendChild(item);
    });
    if (!chunks.length) list.innerHTML = '<div class="knowledge-structure-empty">当前没有可展示的切分结果。</div>';
    els.knowledgeProcessingList.appendChild(list);
    els.knowledgeProcessingPanel.classList.remove("hidden");
  },
  renderSearchResults(els, results, escape, onPreview) {
    els.knowledgeResults.innerHTML = "";
    els.knowledgeResults.classList.remove("hidden");
    results.forEach((result) => {
      const item = window.document.createElement("article");
      item.className = "knowledge-result";
      item.innerHTML = `<button type="button" class="knowledge-result-preview"><strong>${escape(result.filename)}</strong><span>预览文件</span></button><p>${escape(result.excerpt)}</p>`;
      item.querySelector(".knowledge-result-preview").addEventListener("click", () => onPreview(result));
      els.knowledgeResults.appendChild(item);
    });
    if (!results.length) els.knowledgeResults.textContent = "没有匹配资料。";
  },
};
