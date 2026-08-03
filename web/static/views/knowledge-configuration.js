(function () {
  const TAB_DEFINITIONS = [
    { id: "overview", label: "概览" },
    { id: "personal", label: "我的检索", capability: "user_retrieval_profile" },
    { id: "processing", label: "处理预设", capability: "processing_presets" },
    { id: "retrieval", label: "检索策略", capability: "retrieval_policy" },
    { id: "index", label: "索引与迁移" },
  ];
  const ROLE_LABELS = {
    user: "普通用户",
    knowledge_admin: "知识库管理员",
    platform_admin: "平台管理员",
  };
  const PROFILE_LABELS = {
    precise: "精准",
    balanced: "均衡",
    high_recall: "高召回",
  };
  const SCOPE_LABELS = {
    auto: "自动",
    general: "仅通用库",
    current_project: "当前项目",
  };
  const PROFILE_EFFECTS = {
    precise: ["候选较少", "不做查询改写", "不补相邻片段", "上下文更精简"],
    balanced: ["候选适中", "遵循活动策略改写", "按策略补相邻片段", "上下文均衡"],
    high_recall: ["候选更多", "允许受限查询改写", "补充相邻片段", "上下文更充分"],
  };
  const PRESET_LABELS = { standard: "标准", long_document: "长文档", table_dense: "表格密集" };
  const POLICY_FIELD_LABELS = {
    limit: "最终片段数量", max_excerpt_chars: "单片段长度", max_total_chars: "总上下文预算",
    neighbor_radius: "相邻片段半径", hybrid_enabled: "启用混合检索", vector_min_score: "向量相似度门槛",
    rrf_k: "RRF k", candidate_limit: "候选数量", rewrite_enabled: "启用查询改写",
  };
  const POLICY_STATUS_LABELS = { active: "活动", stable: "稳定", candidate: "待评测", verified: "已通过", blocked: "未通过", retired: "已退役" };
  const MIGRATION_STATUS_LABELS = { queued: "待执行", running: "暂存中", partial: "部分失败", staged: "已暂存", verified: "门禁通过", canary: "灰度中", active: "已全量", rolled_back: "已回滚" };

  function capabilities(configuration) {
    return new Map((configuration?.capabilities || []).map((item) => [item.capability_id, item]));
  }

  function visibleTabs(configuration) {
    const available = capabilities(configuration);
    return TAB_DEFINITIONS.filter((tab) => !tab.capability || available.has(tab.capability));
  }

  function card(title, value, detail, escape) {
    return `<article class="configuration-summary-card"><span>${escape(title)}</span><strong>${escape(String(value ?? "—"))}</strong><p>${escape(detail || "")}</p></article>`;
  }

  function renderOverview(configuration, processingRuns, escape) {
    const preferences = configuration.user_preferences || {};
    const retrieval = configuration.retrieval || {};
    const fts = configuration.index?.fts || {};
    const embedding = configuration.index?.embedding || {};
    const migration = configuration.migrations || {};
    const recentFailure = (processingRuns || []).find((run) => run.status === "failed");
    return `<section class="configuration-panel" aria-labelledby="configurationOverviewTitle">
      <div class="configuration-section-heading"><div><h3 id="configurationOverviewTitle">当前配置概览</h3><p>以下内容来自个人偏好、活动策略和本地运行状态。</p></div><span class="configuration-source">统一快照 v${Number(configuration.schema_version || 1)}</span></div>
      <div class="configuration-summary-grid">
        ${card("个人检索", PROFILE_LABELS[preferences.retrieval_profile] || preferences.retrieval_profile, `资料范围：${SCOPE_LABELS[preferences.default_scope] || preferences.default_scope || "自动"}`, escape)}
        ${card("处理预设", preferences.default_upload_preset || "standard", `${configuration.processing?.presets?.length || 0} 个活动预设`, escape)}
        ${card("检索策略", retrieval.active_version || "未启用", retrieval.summary?.hybrid_enabled ? "FTS/BM25 + 向量混合" : "FTS/BM25", escape)}
        ${card("词法索引", fts.backend || "未就绪", `${fts.indexed_chunk_count || 0} 个活动片段`, escape)}
        ${card("向量索引", embedding.enabled ? embedding.model || "已配置" : "未配置", embedding.enabled ? `${embedding.dimensions || 0} 维 · 可回退到 FTS` : "当前使用 FTS/BM25", escape)}
        ${card("历史迁移", migration.visible ? `${migration.active_count || 0} 个进行中` : "按权限隐藏", migration.visible ? `${migration.eligible_document_count || 0} 份资料待迁移` : "普通用户无需管理全局迁移", escape)}
      </div>
      <div class="configuration-health-row ${recentFailure ? "is-warning" : ""}">
        <strong>${recentFailure ? "最近处理存在失败" : "最近处理状态正常"}</strong>
        <span>${escape(recentFailure ? `${recentFailure.filename || "资料"}：${recentFailure.error_message || "处理失败，可返回知识库重试"}` : "没有检测到待处理的失败记录。")}</span>
      </div>
    </section>`;
  }

  function renderPersonal(configuration, escape) {
    const preferences = configuration.user_preferences || {};
    return `<section class="configuration-panel" aria-labelledby="configurationPersonalTitle">
      <div class="configuration-section-heading"><div><h3 id="configurationPersonalTitle">我的检索</h3><p>默认值用于后续对话与上传；对话或上传时的本次覆盖不会反写这里。</p></div><span class="configuration-source">偏好 v${Number(preferences.version || 0)}</span></div>
      <form id="knowledgePreferencesForm" class="knowledge-preferences-form">
        <fieldset><legend>检索预设</legend><div class="retrieval-profile-options">
          ${Object.entries(PROFILE_LABELS).map(([id, label]) => `<label class="retrieval-profile-option"><input type="radio" name="retrieval_profile" value="${id}" ${preferences.retrieval_profile === id ? "checked" : ""}><span class="retrieval-profile-indicator" aria-hidden="true"></span><span class="retrieval-profile-copy"><strong>${label}</strong><small>${PROFILE_EFFECTS[id].map(escape).join(" · ")}</small></span></label>`).join("")}
        </div></fieldset>
        <div class="knowledge-preference-selects">
          <label><span class="configuration-field-title">默认资料范围<small>用于新对话</small></span><select name="default_scope">${Object.entries(SCOPE_LABELS).map(([id, label]) => `<option value="${id}" ${preferences.default_scope === id ? "selected" : ""}>${label}</option>`).join("")}</select><small>“当前项目”只在你有权限且对话位于项目空间时生效，否则安全回退到通用库。</small></label>
          <label><span class="configuration-field-title">新上传默认切分<small>用于新文件</small></span><select name="default_upload_preset">${(configuration.processing?.presets || []).map((preset) => `<option value="${escape(preset.id)}" ${preferences.default_upload_preset === preset.id ? "selected" : ""}>${escape(PRESET_LABELS[preset.id] || preset.label)}</option>`).join("")}</select><small>只影响后续上传，不重新切分已有资料。</small></label>
        </div>
        <div class="configuration-form-actions configuration-form-footer"><span>安全默认：均衡 · 自动 · 标准</span><div><button type="button" class="secondary" data-reset-preferences>恢复安全默认</button><button type="submit">保存更改</button></div></div>
      </form>
    </section>`;
  }

  function renderProcessing(configuration, escape, handlers = {}) {
    const presets = configuration.processing?.presets || [];
    const capability = capabilities(configuration).get("processing_presets");
    const manageable = capability?.writable_roles?.includes(configuration.role);
    const ranges = configuration.processing?.ranges || {};
    const runtime = configuration.processing?.runtime || {};
    const documents = handlers.documents || [];
    const batches = handlers.reprocessingBatches || [];
    if (!presets.length) return '<div class="configuration-state"><strong>暂无处理预设</strong><span>服务端没有返回可用的知识处理预设。</span></div>';
    return `<section class="configuration-panel" aria-labelledby="configurationProcessingTitle">
      <div class="configuration-section-heading"><div><h3 id="configurationProcessingTitle">处理预设</h3><p>修订只影响后续上传或显式重新处理，不覆盖历史片段。</p></div><span class="configuration-source">${manageable ? "可管理" : "只读"}</span></div>
      <div class="configuration-preset-grid">${presets.map((preset) => `<form class="configuration-preset-card" data-preset-form="${escape(preset.id)}">
        <div><strong>${escape(preset.label)}</strong><span>r${Number(preset.revision || 1)}</span></div>
        <p>${escape(preset.description)}</p>
        <label>解析模式<select name="parser_profile" ${manageable ? "" : "disabled"}>${(configuration.processing?.parser_profiles || ["structure_preserving", "auto"]).map((profile) => `<option value="${escape(profile)}" ${profile === preset.parser_profile ? "selected" : ""}>${escape(profile)}</option>`).join("")}</select></label>
        <label>目标 Token<input name="target_tokens" type="number" min="${Number(ranges.target_tokens?.min || 200)}" max="${Number(ranges.target_tokens?.max || 1800)}" value="${Number(preset.chunk_config?.target_tokens || 0)}" ${manageable ? "required" : "disabled"}></label>
        <label>最大 Token<input name="max_tokens" type="number" min="${Number(ranges.max_tokens?.min || 200)}" max="${Number(ranges.max_tokens?.max || 2400)}" value="${Number(preset.chunk_config?.max_tokens || 0)}" ${manageable ? "required" : "disabled"}></label>
        <label>重叠 Token<input name="overlap_tokens" type="number" min="${Number(ranges.overlap_tokens?.min || 0)}" max="${Number(ranges.overlap_tokens?.max || 400)}" value="${Number(preset.chunk_config?.overlap_tokens || 0)}" ${manageable ? "required" : "disabled"}></label>
        <button type="submit" ${manageable ? "" : "disabled"}>${manageable ? "保存为新修订" : "仅管理员可修改"}</button>
        <small>最近修订：${(preset.revisions || []).slice(0, 3).map((item) => `r${Number(item.revision)}`).join("、") || `r${Number(preset.revision || 1)}`}</small>
      </form>`).join("")}</div>
      <div class="configuration-security-boundary"><strong>OCR / 表格运行能力（只读）</strong><span>OCR：${escape(runtime.ocr_engine || "未配置")} · 语言：${escape(runtime.ocr_languages || "—")} · 表格：${escape(runtime.table_parser || "—")}</span></div>
      ${manageable ? `<section class="configuration-batch-panel"><h4>批量重新处理</h4><p>单批最多 20 个文件，每次只执行一个文件；失败不会替换原活动版本，可单独重试。</p>
        <form data-reprocessing-batch-form>
          <label>处理方式<select name="mode"><option value="rechunk">重新切分</option><option value="reparse">重新解析并切分</option><option value="reindex">仅重建倒排索引</option></select></label>
          <label>处理预设<select name="preset">${presets.map((preset) => `<option value="${escape(preset.id)}">${escape(preset.label)}</option>`).join("")}</select></label>
          <label>文件（可多选）<select name="document_ids" multiple size="5">${documents.map((document) => `<option value="${escape(document.id)}">${escape(document.filename)}</option>`).join("")}</select></label>
          <button type="submit" ${documents.length ? "" : "disabled"}>创建受限批任务</button>
        </form>
        <div class="configuration-batch-list">${batches.length ? batches.map((batch) => `<article><strong>${escape(batch.mode)} · ${escape(batch.preset)}</strong><span>${escape(batch.status)} · ${Number(batch.processed_count || 0)}/${Number(batch.total_count || 0)}</span>${["queued", "running", "partial"].includes(batch.status) ? `<button type="button" data-run-reprocessing="${escape(batch.id)}">执行下一项</button>` : ""}${(batch.items || []).filter((item) => item.status === "failed").map((item) => `<button type="button" data-retry-reprocessing="${escape(batch.id)}" data-item-id="${escape(item.id)}">重试 ${escape(item.filename)}</button>`).join("")}</article>`).join("") : "<p>暂无批任务。</p>"}</div>
      </section>` : ""}
    </section>`;
  }

  function renderRetrieval(configuration, escape, handlers = {}) {
    const capability = capabilities(configuration).get("retrieval_policy");
    if (!capability) return '<div class="configuration-state configuration-forbidden"><strong>无权查看检索策略</strong><span>该区域仅对知识库管理员和平台管理员开放。</span></div>';
    const retrieval = configuration.retrieval || {};
    const full = retrieval.active_config || {};
    const writable = capability.writable_roles?.includes(configuration.role);
    const governance = handlers.retrievalGovernance || {};
    const policies = governance.policies || [];
    const ranges = governance.ranges || retrieval.ranges || {};
    const weights = governance.fts_weights || retrieval.fts_weights || {};
    const activeVersion = governance.active?.version || retrieval.active_version;
    const stableAvailable = policies.some((policy) => policy.status === "stable");
    const labResult = governance.lab_result;
    const projectSpaces = (handlers.spaces || []).filter((space) => space.section === "project");
    const labStrategy = (side) => {
      if (!side) return "";
      const stages = side.stages || {};
      const final = stages.final_context || [];
      return `<article class="configuration-lab-strategy"><div><strong>${escape(side.version)}</strong><span>${Number(side.result_count || 0)} 个结果</span></div><dl><div><dt>查询改写</dt><dd>${stages.rewrite?.applied ? "已触发" : "未触发"}</dd></div><div><dt>BM25 候选</dt><dd>${Number(stages.lexical_candidates?.length || 0)}</dd></div><div><dt>向量候选</dt><dd>${Number(stages.vector_candidates?.length || 0)}</dd></div><div><dt>RRF 融合</dt><dd>${Number(stages.fusion?.length || 0)}</dd></div><div><dt>重排</dt><dd>${Number(stages.rerank?.length || 0)}</dd></div><div><dt>最终上下文</dt><dd>${final.length}</dd></div></dl>${final.slice(0, 3).map((item) => `<p><strong>${escape(item.filename || item.document_id)}</strong> · 片段 ${Number(item.position || 0)}<br>${escape(item.excerpt || "")}</p>`).join("") || "<p>没有最终上下文。</p>"}</article>`;
    };
    const numberField = (key, step = "1") => `<label>${escape(POLICY_FIELD_LABELS[key])}<input name="${key}" type="number" min="${Number(ranges[key]?.min ?? 0)}" max="${Number(ranges[key]?.max ?? 999999)}" step="${step}" value="${escape(String(full[key] ?? ""))}" required><small>${Number(ranges[key]?.min ?? 0)}–${Number(ranges[key]?.max ?? 0)}</small></label>`;
    return `<section class="configuration-panel" aria-labelledby="configurationRetrievalTitle">
      <div class="configuration-section-heading"><div><h3 id="configurationRetrievalTitle">检索策略</h3><p>当前活动版本只能通过候选评测、发布和回滚流程变更。</p></div><span class="configuration-source">${writable ? "平台治理" : "只读摘要"}</span></div>
      <div class="configuration-policy-banner"><div><span>活动版本</span><strong>${escape(activeVersion || "未启用")}</strong></div><div><span>检索方式</span><strong>${retrieval.summary?.hybrid_enabled ? "混合检索" : "词法检索"}</strong></div><div><span>查询改写</span><strong>${retrieval.summary?.rewrite_enabled ? "已启用" : "未启用"}</strong></div></div>
      ${writable && Object.keys(full).length ? `<form class="configuration-policy-form" data-retrieval-candidate-form>
        <div class="configuration-section-heading compact"><div><h4>基于活动版本创建候选</h4><p>保存只创建候选，不修改生产；候选必须通过固定集和混合检索门禁。</p></div></div>
        <div class="configuration-policy-fields">
          ${numberField("limit")}${numberField("max_excerpt_chars")}${numberField("max_total_chars")}${numberField("neighbor_radius")}
          ${numberField("vector_min_score", "0.01")}${numberField("rrf_k")}${numberField("candidate_limit")}
        </div>
        <div class="configuration-policy-toggles">
          <label class="configuration-toggle"><span><strong>${POLICY_FIELD_LABELS.hybrid_enabled}</strong><small>融合词法与向量候选</small></span><input name="hybrid_enabled" type="checkbox" ${full.hybrid_enabled ? "checked" : ""}><i aria-hidden="true"></i></label>
          <label class="configuration-toggle"><span><strong>${POLICY_FIELD_LABELS.rewrite_enabled}</strong><small>按需扩展和规范问题</small></span><input name="rewrite_enabled" type="checkbox" ${full.rewrite_enabled ? "checked" : ""}><i aria-hidden="true"></i></label>
        </div>
        <div class="configuration-form-actions configuration-form-footer"><span>越界、无变化和关系不合法的参数会被前后端拒绝。</span><button type="submit">创建候选并查看差异</button></div>
      </form>` : '<p class="configuration-readonly-note">完整参数与候选操作仅平台管理员可见。</p>'}
      ${writable && policies.length >= 2 ? `<section class="configuration-governance-section configuration-lab"><div class="configuration-section-heading compact"><div><h4>双策略检索实验室</h4><p>逐阶段比较查询改写、BM25、向量、RRF、重排和最终上下文；不会写入生产 Trace 或修改活动策略。</p></div></div><form data-retrieval-lab-form><label>实验问题<input name="query" maxlength="300" required placeholder="输入仅用于本次实验"></label><label>左侧策略<select name="left_version">${policies.map((policy) => `<option value="${escape(policy.version)}">${escape(policy.version)}</option>`).join("")}</select></label><label>右侧策略<select name="right_version">${policies.map((policy, index) => `<option value="${escape(policy.version)}" ${index === 1 ? "selected" : ""}>${escape(policy.version)}</option>`).join("")}</select></label><label>资料范围<select name="scope"><option value="general">通用知识库</option><option value="all_projects">全部有权项目</option>${projectSpaces.map((space) => `<option value="project:${escape(space.id)}">项目：${escape(space.name)}</option>`).join("")}</select></label><button type="submit">运行双策略实验</button></form>${labResult ? `<div class="configuration-lab-difference"><strong>${labResult.differences?.same_top_document ? "首位文档一致" : "首位文档不同"}</strong><span>结果差：${Number(labResult.differences?.result_count_delta || 0)} · 配置差异：${(labResult.differences?.changed_config || []).map((key) => escape(POLICY_FIELD_LABELS[key] || key)).join("、") || "无"}</span></div><div class="configuration-lab-results">${labStrategy(labResult.left)}${labStrategy(labResult.right)}</div>` : ""}<div class="configuration-lab-history"><h5>最近实验（仅内容安全摘要）</h5>${(governance.lab_experiments || []).slice(0, 8).map((item) => `<article><code>${escape(String(item.query_sha256 || "").slice(0, 12))}…</code><span>${escape(item.left_policy_version)} ↔ ${escape(item.right_policy_version)}</span><small>${Number(item.summary?.left_result_count || 0)} / ${Number(item.summary?.right_result_count || 0)} 个结果</small></article>`).join("") || "<p>暂无实验记录。</p>"}</div></section>` : ""}
      ${writable ? `<section class="configuration-governance-section"><div class="configuration-section-heading compact"><div><h4>策略版本与门禁</h4><p>发布前必须确认父版本、变更字段和回滚目标。</p></div>${stableAvailable ? `<button type="button" class="secondary" data-rollback-retrieval>回滚活动策略</button>` : ""}</div>
        <div class="configuration-policy-list">${policies.length ? policies.map((policy) => {
          const experiment = policy.experiment || {};
          const gates = experiment.hybrid_targeted_gates || {};
          const passedGates = Object.values(gates).filter(Boolean).length;
          const totalGates = Object.keys(gates).length;
          const changed = String(policy.changed_variable || "").split(",").filter(Boolean);
          return `<article class="configuration-policy-version is-${escape(policy.status)}"><div><strong>${escape(policy.version)}</strong><span>${escape(POLICY_STATUS_LABELS[policy.status] || policy.status)}</span></div><p>父版本：${escape(policy.parent_version || "基线")} · 变更：${changed.map((key) => escape(POLICY_FIELD_LABELS[key] || key)).join("、") || "基线"}</p>${Object.keys(experiment).length ? `<div class="configuration-gate-summary"><span>固定集：${experiment.failures?.length ? `${experiment.failures.length} 项失败` : "通过"}</span><span>混合门禁：${passedGates}/${totalGates}</span><span>结论：${experiment.decision === "promote" ? "可发布" : "阻止发布"}</span></div>` : ""}<div class="configuration-policy-actions">${["candidate", "blocked"].includes(policy.status) ? `<button type="button" data-evaluate-policy="${escape(policy.version)}">${policy.status === "blocked" ? "重新评测" : "运行质量门禁"}</button>` : ""}${policy.status === "verified" ? `<button type="button" data-publish-policy="${escape(policy.version)}" data-parent-version="${escape(policy.parent_version)}">确认发布</button>` : ""}</div></article>`;
        }).join("") : "<p>暂无策略版本。</p>"}</div>
      </section>
      <section class="configuration-governance-section"><h4>反馈驱动的单变量建议</h4><p>建议与手工候选进入相同版本、评测、发布和回滚流程。</p><div class="configuration-suggestion-list">${(governance.suggestions || []).length ? governance.suggestions.map((suggestion) => `<article><strong>${escape(suggestion.title)}</strong><p>${escape(suggestion.rationale)}</p><small>${escape(suggestion.risk)}</small><button type="button" data-suggestion-candidate="${escape(suggestion.id)}">创建单变量候选</button></article>`).join("") : `<p>当前没有达到样本门槛的建议（${Number(governance.suggestion_evidence?.document_feedback_count || 0)} 条文档反馈）。</p>`}</div></section>
      <div class="configuration-security-boundary"><strong>FTS/BM25 字段权重（只读）</strong><span>文件名 ${Number(weights.filename || 0)} · 标题 ${Number(weights.heading || 0)} · 正文 ${Number(weights.content || 0)} · 标签 ${Number(weights.tag || 0)} · ${escape(weights.policy_version || "")}</span></div>` : ""}
    </section>`;
  }

  function renderIndex(configuration, escape, handlers = {}) {
    const fts = configuration.index?.fts || {};
    const embedding = configuration.index?.embedding || {};
    const migration = configuration.migrations || {};
    const security = configuration.security || {};
    const governance = handlers.embeddingGovernance || {};
    const migrationGovernance = handlers.migrationGovernance || {};
    const migrationBatches = migrationGovernance.batches || [];
    const migrationLimits = migrationGovernance.limits || { minimum: 1, maximum: 50, default: 10 };
    const inventory = governance.inventory || {};
    const models = governance.models || [];
    const recentJobs = governance.jobs || [];
    const recentErrors = governance.recent_errors || [];
    const rollbackTargets = governance.rollback_targets || [];
    const jobs = embedding.jobs || {};
    const platformAdmin = configuration.role === "platform_admin";
    const config = embedding.configuration || {};
    const statusLabel = { queued: "等待", running: "运行中", ready: "成功", partial: "部分失败", failed: "失败" };
    return `<section class="configuration-panel" aria-labelledby="configurationIndexTitle">
      <div class="configuration-section-heading"><div><h3 id="configurationIndexTitle">索引与迁移</h3><p>向量失败或未配置时继续使用 FTS5/BM25；环境配置和安全硬限制保持只读。</p></div><span class="configuration-source">${platformAdmin ? "平台运维" : "运行状态"}</span></div>
      <div class="configuration-summary-grid">
        ${card("FTS/BM25", fts.backend || "未就绪", `${fts.indexed_chunk_count || 0} 个已索引片段`, escape)}
        ${card("Embedding Provider", embedding.enabled ? embedding.provider || "已配置" : "未配置", embedding.enabled ? `${embedding.model || "—"} · ${embedding.dimensions || 0} 维` : "不会发起向量网络请求", escape)}
        ${card("活动模型版本", embedding.model_version || "无", embedding.enabled ? "由环境配置生成并版本化" : `回退：${embedding.fallback || "fts5-bm25"}`, escape)}
        ${card("向量队列", `${jobs.queued || 0} 等待 / ${jobs.running || 0} 运行`, `${jobs.failed || 0} 个失败`, escape)}
        ${card("任务结果", `${jobs.ready || 0} 成功 / ${jobs.partial || 0} 部分失败`, `${inventory.ready_document_count || 0} 份资料索引就绪`, escape)}
        ${card("迁移批次", migration.visible ? migration.batch_count || 0 : "按权限隐藏", migration.visible ? `${migration.active_count || 0} 个进行中` : "平台管理员可管理", escape)}
      </div>
      <div class="configuration-health-row ${embedding.enabled ? "" : "is-warning"}"><strong>${embedding.enabled ? "混合检索可用" : "当前处于词法回退"}</strong><span>${embedding.enabled ? "向量失败时自动回退 FTS5/BM25，不阻断关键词检索。" : "Provider 未配置；后台不会调用外部向量服务，FTS5/BM25 保持可用。"}</span></div>
      ${platformAdmin ? `<section class="configuration-index-section"><div class="configuration-section-heading compact"><div><h4>向量索引运维</h4><p>全库重建先按当前 ${Number(inventory.document_count || 0)} 份资料确认影响范围；后台任务可逐项处理。</p></div><div class="configuration-index-actions"><button type="button" data-rebuild-embedding ${embedding.enabled ? "" : "disabled"}>全库重建</button><button type="button" class="secondary" data-run-embedding ${embedding.enabled && Number(jobs.queued || 0) ? "" : "disabled"}>处理下一任务</button></div></div>
        <div class="configuration-index-progress">${recentJobs.length ? recentJobs.slice(0, 8).map((job) => `<article><div><strong>${escape(statusLabel[job.status] || job.status)}</strong><span>${escape(job.model_version || "—")}</span></div><progress max="${Math.max(1, Number(job.total_count || 0))}" value="${Number(job.succeeded_count || 0) + Number(job.failed_count || 0)}"></progress><small>${Number(job.succeeded_count || 0)} 成功 · ${Number(job.failed_count || 0)} 失败 · ${Number(job.reused_count || 0)} 复用</small></article>`).join("") : "<p>暂无向量任务。</p>"}</div>
      </section>
      <section class="configuration-index-section"><h4>模型版本与文档回滚</h4><p>仅完整覆盖当前切分版本的模型可作为回滚目标；回滚只切换活动模型，不重新上传资料。</p>
        <div class="configuration-model-list">${models.length ? models.map((model) => `<article><strong>${escape(model.model || model.version)}</strong><span>${escape(model.status)} · ${Number(model.dimensions || 0)} 维</span><small>${escape(model.version)}</small></article>`).join("") : "<p>暂无已登记模型版本。</p>"}</div>
        <div class="configuration-rollback-list">${rollbackTargets.length ? rollbackTargets.map((target) => { const alternatives = (target.available_model_versions || []).filter((version) => version !== target.active_model_version); return `<form data-embedding-rollback="${escape(target.document_id)}"><div><strong>${escape(target.filename)}</strong><small>当前：${escape(target.active_model_version || "未激活")}</small></div><select name="model_version" aria-label="${escape(target.filename)} 回滚版本" ${alternatives.length ? "" : "disabled"}>${alternatives.length ? alternatives.map((version) => `<option value="${escape(version)}">${escape(version)}</option>`).join("") : '<option value="">没有其他完整版本</option>'}</select><button type="submit" ${alternatives.length ? "" : "disabled"}>回滚</button></form>`; }).join("") : "<p>当前没有可回滚的完整文档模型版本。</p>"}</div>
      </section>
      <section class="configuration-index-section"><h4>环境配置（只读）</h4><p>Provider、服务地址、凭证、模型、维度和超时均由环境变量管理；修改后需重启本地服务。</p><dl class="configuration-definition-list compact">
        <div><dt>服务地址</dt><dd>${config.endpoint_configured ? "已配置（值已隐藏）" : "未配置"}</dd></div><div><dt>访问凭证</dt><dd>${config.credential_configured ? "已配置（值已隐藏）" : "未配置"}</dd></div><div><dt>模型 / 维度</dt><dd>${config.model_configured ? `${escape(embedding.model || "已配置")} / ${Number(embedding.dimensions || 0)}` : "未配置"}</dd></div><div><dt>请求超时</dt><dd>${Number(config.timeout_seconds || 0)} 秒</dd></div>
      </dl></section>
      <section class="configuration-index-section"><h4>最近安全错误</h4><div class="configuration-error-list">${recentErrors.length ? recentErrors.map((item) => `<article><strong>${escape(statusLabel[item.status] || item.status)}</strong><span>${escape(item.message || "向量任务失败")}</span></article>`).join("") : "<p>没有向量任务错误。</p>"}</div></section>` : '<p class="configuration-readonly-note">完整向量任务、模型版本和运维操作仅平台管理员可见。</p>'}
      ${platformAdmin ? `<section class="configuration-index-section configuration-migration"><div class="configuration-section-heading compact"><div><h4>历史资料迁移</h4><p>同一时间只允许一个未结束批次；暂存、Shadow 门禁、25% 灰度、全量与回滚按状态推进。</p></div><span>${Number(migrationGovernance.eligible_count || 0)} 份待迁移</span></div><ol class="configuration-migration-flow">${(migrationGovernance.state_machine || []).map((status) => `<li>${escape(MIGRATION_STATUS_LABELS[status] || status)}</li>`).join("")}</ol><form data-migration-batch-form><label>迁移预设<select name="preset">${(migrationGovernance.presets || []).map((preset) => `<option value="${escape(preset.id)}">${escape(preset.label)}</option>`).join("")}</select></label><label>单批上限<input type="number" name="limit" min="${Number(migrationLimits.minimum)}" max="${Number(migrationLimits.maximum)}" value="${Number(migrationLimits.default)}" required></label><button type="submit" ${migrationGovernance.can_create_batch && Number(migrationGovernance.eligible_count || 0) ? "" : "disabled"}>创建迁移批次</button></form>${migrationGovernance.active_batch_id ? `<p class="configuration-readonly-note">活动批次：${escape(migrationGovernance.active_batch_id)}。结束或回滚前不能创建新批次。</p>` : ""}<div class="configuration-migration-list">${migrationBatches.length ? migrationBatches.map((batch) => { const evaluation = batch.evaluation || {}; const gates = evaluation.gates || {}; return `<article><div><strong>${escape(batch.preset)} · ${escape(MIGRATION_STATUS_LABELS[batch.status] || batch.status)}</strong><span>${Number(batch.processed_count || 0)}/${Number(batch.total_count || 0)} · 灰度 ${Number(batch.rollout_percentage || 0)}%</span></div>${Object.keys(gates).length ? `<div class="configuration-gate-summary">${Object.entries(gates).map(([key, passed]) => `<span class="${passed ? "is-pass" : "is-fail"}">${escape(key)}：${passed ? "通过" : "阻止"}</span>`).join("")}</div>` : ""}<div class="configuration-policy-actions">${["queued", "running"].includes(batch.status) ? `<button type="button" data-run-migration="${escape(batch.id)}">生成暂存版本</button>` : ""}${batch.status === "staged" ? `<button type="button" data-evaluate-migration="${escape(batch.id)}">运行 Shadow 门禁</button>` : ""}${["verified", "rolled_back"].includes(batch.status) ? `<button type="button" data-promote-migration="${escape(batch.id)}" data-percentage="25">发布 25%</button>` : ""}${["verified", "canary", "rolled_back"].includes(batch.status) ? `<button type="button" data-promote-migration="${escape(batch.id)}" data-percentage="100">发布 100%</button>` : ""}${["canary", "active"].includes(batch.status) ? `<button type="button" class="secondary" data-rollback-migration="${escape(batch.id)}">回滚</button>` : ""}</div>${(batch.items || []).filter((item) => item.status === "failed").map((item) => `<div class="configuration-migration-error"><span>${escape(item.filename)}：${escape(item.error_message || "迁移失败")}</span><button type="button" data-retry-migration="${escape(batch.id)}" data-item-id="${escape(item.id)}">重试该项</button></div>`).join("")}</article>`; }).join("") : "<p>暂无迁移批次。</p>"}</div><div class="configuration-security-boundary"><strong>迁移隐私边界</strong><span>${escape(migrationGovernance.privacy || "只保存查询哈希和结果摘要，不保存问题与知识正文。")}</span></div></section>` : ""}
      <section class="configuration-index-section"><h4>知识文件安全限制（只读）</h4><dl class="configuration-definition-list compact"><div><dt>单文件 / 解压总量</dt><dd>${Math.round(Number(security.upload_bytes || 0) / 1024 / 1024)} MB / ${Math.round(Number(security.archive_bytes || 0) / 1024 / 1024)} MB</dd></div><div><dt>压缩包条目</dt><dd>${Number(security.archive_files || 0)}</dd></div><div><dt>解析字符 / PDF 页数</dt><dd>${Number(security.extracted_chars || 0)} / ${Number(security.pdf_pages || 0)}</dd></div><div><dt>ACL / 路径</dt><dd>${security.acl_enforced ? "已强制" : "未知"} / ${security.storage_root_enforced ? "限定存储根" : "未知"}</dd></div></dl><div class="configuration-security-boundary"><strong>配置来源：环境变量与固定安全边界</strong><span>不返回凭证、服务地址、绝对路径、向量或知识正文；修改限制后需要重启。</span></div></section>
    </section>`;
  }

  function render(els, configuration, activeTab, escape, handlers = {}) {
    const tabs = visibleTabs(configuration);
    const selected = tabs.some((tab) => tab.id === activeTab) ? activeTab : tabs[0]?.id || "overview";
    els.knowledgeConfigurationRole.textContent = ROLE_LABELS[configuration.role] || configuration.role || "未知角色";
    els.knowledgeConfigurationTabs.innerHTML = tabs.map((tab) => `<button type="button" role="tab" data-configuration-tab="${tab.id}" aria-selected="${tab.id === selected}" class="${tab.id === selected ? "active" : ""}">${tab.label}</button>`).join("");
    els.knowledgeConfigurationTabs.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => handlers.onTab?.(button.dataset.configurationTab)));
    const renderers = { personal: renderPersonal, processing: renderProcessing, retrieval: renderRetrieval, index: renderIndex };
    els.knowledgeConfigurationContent.innerHTML = selected === "overview"
      ? renderOverview(configuration, handlers.processingRuns || [], escape)
      : renderers[selected](configuration, escape, handlers);
    if (selected === "personal") {
      const form = els.knowledgeConfigurationContent.querySelector("#knowledgePreferencesForm");
      form?.addEventListener("submit", (event) => {
        event.preventDefault();
        const data = new FormData(form);
        handlers.onSavePreferences?.({
          retrieval_profile: data.get("retrieval_profile"),
          default_scope: data.get("default_scope"),
          default_upload_preset: data.get("default_upload_preset"),
        });
      });
      form?.querySelector("[data-reset-preferences]")?.addEventListener("click", () => handlers.onSavePreferences?.({ retrieval_profile: "balanced", default_scope: "auto", default_upload_preset: "standard" }));
    }
    if (selected === "processing") {
      els.knowledgeConfigurationContent.querySelectorAll("[data-preset-form]").forEach((form) => form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!form.reportValidity()) return;
        const data = new FormData(form);
        const chunkConfig = {
          target_tokens: Number(data.get("target_tokens")),
          max_tokens: Number(data.get("max_tokens")),
          overlap_tokens: Number(data.get("overlap_tokens")),
        };
        if (chunkConfig.max_tokens < chunkConfig.target_tokens) {
          form.querySelector('[name="max_tokens"]').setCustomValidity("最大 Token 不能小于目标 Token");
          form.reportValidity();
          form.querySelector('[name="max_tokens"]').setCustomValidity("");
          return;
        }
        if (chunkConfig.overlap_tokens >= chunkConfig.target_tokens) {
          form.querySelector('[name="overlap_tokens"]').setCustomValidity("重叠 Token 必须小于目标 Token");
          form.reportValidity();
          form.querySelector('[name="overlap_tokens"]').setCustomValidity("");
          return;
        }
        handlers.onSavePreset?.(form.dataset.presetForm, {
          parser_profile: data.get("parser_profile"),
          chunk_config: chunkConfig,
        });
      }));
      const batchForm = els.knowledgeConfigurationContent.querySelector("[data-reprocessing-batch-form]");
      batchForm?.addEventListener("submit", (event) => {
        event.preventDefault();
        const data = new FormData(batchForm);
        handlers.onCreateReprocessingBatch?.({ mode: data.get("mode"), preset: data.get("preset"), document_ids: data.getAll("document_ids") });
      });
      els.knowledgeConfigurationContent.querySelectorAll("[data-run-reprocessing]").forEach((button) => button.addEventListener("click", () => handlers.onRunReprocessingBatch?.(button.dataset.runReprocessing)));
      els.knowledgeConfigurationContent.querySelectorAll("[data-retry-reprocessing]").forEach((button) => button.addEventListener("click", () => handlers.onRetryReprocessingItem?.(button.dataset.retryReprocessing, button.dataset.itemId)));
    }
    if (selected === "retrieval") {
      const candidateForm = els.knowledgeConfigurationContent.querySelector("[data-retrieval-candidate-form]");
      candidateForm?.addEventListener("submit", (event) => {
        event.preventDefault();
        if (!candidateForm.reportValidity()) return;
        const data = new FormData(candidateForm);
        const config = {
          limit: Number(data.get("limit")),
          max_excerpt_chars: Number(data.get("max_excerpt_chars")),
          max_total_chars: Number(data.get("max_total_chars")),
          neighbor_radius: Number(data.get("neighbor_radius")),
          hybrid_enabled: data.has("hybrid_enabled"),
          vector_min_score: Number(data.get("vector_min_score")),
          rrf_k: Number(data.get("rrf_k")),
          candidate_limit: Number(data.get("candidate_limit")),
          rewrite_enabled: data.has("rewrite_enabled"),
        };
        if (config.max_total_chars < config.max_excerpt_chars) {
          const input = candidateForm.querySelector('[name="max_total_chars"]');
          input.setCustomValidity("总上下文预算不能小于单片段长度"); input.reportValidity(); input.setCustomValidity(""); return;
        }
        if (config.candidate_limit < config.limit) {
          const input = candidateForm.querySelector('[name="candidate_limit"]');
          input.setCustomValidity("候选数量不能小于最终片段数量"); input.reportValidity(); input.setCustomValidity(""); return;
        }
        handlers.onCreateRetrievalCandidate?.(config);
      });
      els.knowledgeConfigurationContent.querySelectorAll("[data-evaluate-policy]").forEach((button) => button.addEventListener("click", () => handlers.onEvaluateRetrievalPolicy?.(button.dataset.evaluatePolicy)));
      els.knowledgeConfigurationContent.querySelectorAll("[data-publish-policy]").forEach((button) => button.addEventListener("click", () => handlers.onPublishRetrievalPolicy?.(button.dataset.publishPolicy, button.dataset.parentVersion)));
      els.knowledgeConfigurationContent.querySelector("[data-rollback-retrieval]")?.addEventListener("click", () => handlers.onRollbackRetrievalPolicy?.());
      els.knowledgeConfigurationContent.querySelectorAll("[data-suggestion-candidate]").forEach((button) => button.addEventListener("click", () => handlers.onCreateSuggestionCandidate?.(button.dataset.suggestionCandidate)));
      const labForm = els.knowledgeConfigurationContent.querySelector("[data-retrieval-lab-form]");
      labForm?.addEventListener("submit", (event) => { event.preventDefault(); if (!labForm.reportValidity()) return; const data = new FormData(labForm); const scope = String(data.get("scope") || "general"); handlers.onCompareRetrievalPolicies?.({ query: data.get("query"), left_version: data.get("left_version"), right_version: data.get("right_version"), include_all_projects: scope === "all_projects", project_space_id: scope.startsWith("project:") ? scope.slice(8) : "" }); });
    }
    if (selected === "index") {
      els.knowledgeConfigurationContent.querySelector("[data-rebuild-embedding]")?.addEventListener("click", () => handlers.onRebuildEmbeddingIndex?.());
      els.knowledgeConfigurationContent.querySelector("[data-run-embedding]")?.addEventListener("click", () => handlers.onRunEmbeddingIndex?.());
      els.knowledgeConfigurationContent.querySelectorAll("[data-embedding-rollback]").forEach((form) => form.addEventListener("submit", (event) => {
        event.preventDefault();
        handlers.onRollbackEmbeddingDocument?.(form.dataset.embeddingRollback, new FormData(form).get("model_version"));
      }));
      const migrationForm = els.knowledgeConfigurationContent.querySelector("[data-migration-batch-form]");
      migrationForm?.addEventListener("submit", (event) => { event.preventDefault(); if (!migrationForm.reportValidity()) return; const data = new FormData(migrationForm); handlers.onCreateMigrationBatch?.({ preset: data.get("preset"), limit: Number(data.get("limit")) }); });
      els.knowledgeConfigurationContent.querySelectorAll("[data-run-migration]").forEach((button) => button.addEventListener("click", () => handlers.onRunMigrationBatch?.(button.dataset.runMigration)));
      els.knowledgeConfigurationContent.querySelectorAll("[data-evaluate-migration]").forEach((button) => button.addEventListener("click", () => handlers.onEvaluateMigrationBatch?.(button.dataset.evaluateMigration)));
      els.knowledgeConfigurationContent.querySelectorAll("[data-promote-migration]").forEach((button) => button.addEventListener("click", () => handlers.onPromoteMigrationBatch?.(button.dataset.promoteMigration, Number(button.dataset.percentage))));
      els.knowledgeConfigurationContent.querySelectorAll("[data-rollback-migration]").forEach((button) => button.addEventListener("click", () => handlers.onRollbackMigrationBatch?.(button.dataset.rollbackMigration)));
      els.knowledgeConfigurationContent.querySelectorAll("[data-retry-migration]").forEach((button) => button.addEventListener("click", () => handlers.onRetryMigrationItem?.(button.dataset.retryMigration, button.dataset.itemId)));
    }
    els.knowledgeConfigurationContent.focus({ preventScroll: true });
    return selected;
  }

  function renderLoading(els) {
    els.knowledgeConfigurationRole.textContent = "正在确认权限";
    els.knowledgeConfigurationTabs.innerHTML = "";
    els.knowledgeConfigurationNotice.textContent = "";
    els.knowledgeConfigurationContent.innerHTML = '<div class="configuration-state configuration-loading" role="status"><strong>正在加载知识库配置</strong><span>正在合并个人偏好、处理预设和索引状态…</span></div>';
  }

  function renderError(els, message, onRetry) {
    els.knowledgeConfigurationRole.textContent = "配置未启用";
    els.knowledgeConfigurationTabs.innerHTML = "";
    els.knowledgeConfigurationContent.innerHTML = '<div class="configuration-state configuration-error" role="alert"><strong>知识库配置暂时无法加载</strong><span></span><button type="button">重新加载</button></div>';
    els.knowledgeConfigurationContent.querySelector("span").textContent = String(message || "请稍后重试。");
    els.knowledgeConfigurationContent.querySelector("button")?.addEventListener("click", onRetry);
  }

  function showSaveError(els, message) {
    els.knowledgeConfigurationNotice.textContent = `保存失败：${String(message || "请检查配置后重试")}`;
    els.knowledgeConfigurationNotice.classList.add("is-error");
  }

  function showSaveSuccess(els, message) {
    els.knowledgeConfigurationNotice.textContent = String(message || "默认值已保存");
    els.knowledgeConfigurationNotice.classList.remove("is-error");
  }

  window.AgentKnowledgeConfigurationView = { render, renderLoading, renderError, showSaveError, showSaveSuccess, visibleTabs };
})();
