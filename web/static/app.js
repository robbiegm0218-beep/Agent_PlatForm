const state = {
  token: localStorage.getItem("agent_platform_token") || "",
  user: null,
  threads: [],
  folders: [],
  collapsedFolderIds: new Set(),
  spacesCollapsed: false,
  tasksCollapsed: false,
  demoMembersBySpace: {},
  currentThreadId: "",
  pendingFolderId: "",
  messages: [],
  runs: [],
  threadContext: { sources: [], outputs: [] },
  skills: [],
  models: [],
  artifacts: [],
  tools: [],
  knowledgeDocuments: [],
  memories: [],
  selectedSkillIds: [],
  activeView: "chat",
  streaming: false,
};

const UI_STATE_KEY = "agent_platform_workspace_state";
const VALID_VIEWS = new Set(["chat", "skills", "settings", "knowledge", "memories", "artifacts", "space"]);

const els = {
  loginView: document.querySelector("#loginView"),
  workspaceView: document.querySelector("#workspaceView"),
  loginForm: document.querySelector("#loginForm"),
  loginError: document.querySelector("#loginError"),
  emailInput: document.querySelector("#emailInput"),
  passwordInput: document.querySelector("#passwordInput"),
  threadList: document.querySelector("#threadList"),
  threadSearch: document.querySelector("#threadSearch"),
  newThreadButton: document.querySelector("#newThreadButton"),
  chatPage: document.querySelector("#chatPage"),
  spacePage: document.querySelector("#spacePage"),
  spaceTitle: document.querySelector("#spaceTitle"),
  spaceDetail: document.querySelector("#spaceDetail"),
  skillsPage: document.querySelector("#skillsPage"),
  settingsPage: document.querySelector("#settingsPage"),
  knowledgePage: document.querySelector("#knowledgePage"),
  memoriesPage: document.querySelector("#memoriesPage"),
  messages: document.querySelector("#messages"),
  threadTitle: document.querySelector("#threadTitle"),
  modelStatus: document.querySelector("#modelStatus"),
  runDetailsButton: document.querySelector("#runDetailsButton"),
  runDrawer: document.querySelector("#runDrawer"),
  closeRunDrawer: document.querySelector("#closeRunDrawer"),
  runList: document.querySelector("#runList"),
  viewAllRunsButton: document.querySelector("#viewAllRunsButton"),
  runFilters: document.querySelector("#runFilters"),
  runStatusFilter: document.querySelector("#runStatusFilter"),
  runTierFilter: document.querySelector("#runTierFilter"),
  runKnowledgeFilter: document.querySelector("#runKnowledgeFilter"),
  runDetail: document.querySelector("#runDetail"),
  chatForm: document.querySelector("#chatForm"),
  chatInput: document.querySelector("#chatInput"),
  taskModeSelect: document.querySelector("#taskModeSelect"),
  modelSelect: document.querySelector("#modelSelect"),
  sourceModeSelect: document.querySelector("#sourceModeSelect"),
  knowledgeModeSelect: document.querySelector("#knowledgeModeSelect"),
  webModeSelect: document.querySelector("#webModeSelect"),
  fileModeSelect: document.querySelector("#fileModeSelect"),
  executionModeHint: document.querySelector("#executionModeHint"),
  skillPickerButton: document.querySelector("#skillPickerButton"),
  skillPickerMenu: document.querySelector("#skillPickerMenu"),
  sendButton: document.querySelector("#sendButton"),
  skillsGrid: document.querySelector("#skillsGrid"),
  appsGrid: document.querySelector("#appsGrid"),
  skillFileInput: document.querySelector("#skillFileInput"),
  skillFileName: document.querySelector("#skillFileName"),
  skillDropZone: document.querySelector("#skillDropZone"),
  nameInput: document.querySelector("#nameInput"),
  settingsEmail: document.querySelector("#settingsEmail"),
  settingsForm: document.querySelector("#settingsForm"),
  settingsNotice: document.querySelector("#settingsNotice"),
  logoutButton: document.querySelector("#logoutButton"),
  logoutAllButton: document.querySelector("#logoutAllButton"),
  uploadKnowledgeButton: document.querySelector("#uploadKnowledgeButton"),
  knowledgeFileInput: document.querySelector("#knowledgeFileInput"),
  knowledgeSearch: document.querySelector("#knowledgeSearch"),
  knowledgeList: document.querySelector("#knowledgeList"),
  knowledgeResults: document.querySelector("#knowledgeResults"),
  memoryForm: document.querySelector("#memoryForm"),
  memoryKind: document.querySelector("#memoryKind"),
  memoryScope: document.querySelector("#memoryScope"),
  memoryContent: document.querySelector("#memoryContent"),
  memorySearch: document.querySelector("#memorySearch"),
  memoryNotice: document.querySelector("#memoryNotice"),
  memoryList: document.querySelector("#memoryList"),
  artifactsPage: document.querySelector("#artifactsPage"),
  artifactsGrid: document.querySelector("#artifactsGrid"),
  threadContextPanel: document.querySelector("#threadContextPanel"),
  threadContextCount: document.querySelector("#threadContextCount"),
  threadSources: document.querySelector("#threadSources"),
  threadOutputs: document.querySelector("#threadOutputs"),
  viewKnowledgeButton: document.querySelector("#viewKnowledgeButton"),
  viewArtifactsButton: document.querySelector("#viewArtifactsButton"),
};

function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }
  return fetch(path, {
    ...options,
    headers,
  }).then(async (response) => {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error || "请求失败");
      error.status = response.status;
      throw error;
    }
    return data;
  });
}

async function boot() {
  if (!state.token) {
    showLogin();
    return;
  }
  try {
    const [{ user }, health] = await Promise.all([api("/api/me"), api("/api/health")]);
    state.user = user;
    els.modelStatus.textContent = health.deepseek_configured ? `DeepSeek / ${health.model}` : "DeepSeek / 本地模拟";
    showWorkspace(false);
    try {
      await refreshAll();
      await restoreWorkspaceState();
      revealWorkspace();
    } catch (error) {
      showWorkspaceLoadError(error);
    }
  } catch (error) {
    if (error.status === 401) {
      localStorage.removeItem("agent_platform_token");
      state.token = "";
      showLogin();
      return;
    }
    els.loginError.textContent = `无法连接本地服务：${error.message}`;
    showLogin();
  }
}

function showWorkspaceLoadError(error) {
  revealWorkspace();
  els.messages.innerHTML = "";
  const notice = document.createElement("div");
  notice.className = "empty-state";
  notice.innerHTML = "<h1>工作区暂时无法加载</h1>";
  const detail = document.createElement("p");
  detail.textContent = error.message;
  notice.appendChild(detail);
  els.messages.appendChild(notice);
}

function showLogin() {
  document.body.classList.remove("booting");
  els.loginView.classList.remove("hidden");
  els.workspaceView.classList.add("hidden");
}

function showDirectOpenNotice() {
  document.body.classList.remove("booting");
  document.body.innerHTML = `
    <main class="direct-open-notice">
      <section>
        <div class="brand-mark">Agent_Platform</div>
        <h1>请通过本地服务打开</h1>
        <p>直接打开 HTML 页面无法连接登录、对话和文件生成服务。</p>
        <a href="http://localhost:8765">打开 Agent_Platform</a>
      </section>
    </main>
  `;
}

function revealWorkspace() {
  document.body.classList.remove("booting");
}

function showWorkspace(reveal = true) {
  if (reveal) revealWorkspace();
  els.loginView.classList.add("hidden");
  els.workspaceView.classList.remove("hidden");
  els.nameInput.value = state.user?.name || "";
  els.settingsEmail.value = state.user?.email || "";
  renderThreadContext();
}

async function refreshAll() {
  await Promise.all([loadThreads(), loadFolders(), loadSkills(), loadApps(), loadModels(), loadKnowledge(), loadMemories(), loadArtifacts()]);
  renderThreads();
  renderMessages();
}

function persistWorkspaceState() {
  localStorage.setItem(UI_STATE_KEY, JSON.stringify({
    view: state.activeView,
    threadId: state.currentThreadId,
  }));
}

async function restoreWorkspaceState() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(UI_STATE_KEY) || "{}");
  } catch (_error) {
    localStorage.removeItem(UI_STATE_KEY);
  }
  const view = VALID_VIEWS.has(saved.view) ? saved.view : "chat";
  const thread = state.threads.find((item) => item.id === saved.threadId);
  if (thread) {
    await loadThread(thread.id);
  } else {
    state.currentThreadId = "";
    state.messages = [];
    els.threadTitle.textContent = "新对话";
    renderThreads();
    renderMessages();
  }
  switchView(view);
}

async function loadThreads() {
  const data = await api("/api/threads");
  state.threads = data.threads;
}

async function loadFolders() {
  const data = await api("/api/folders");
  state.folders = data.folders;
  renderMemoryScopes();
}

async function loadThread(threadId) {
  const data = await api(`/api/threads/${threadId}`);
  state.currentThreadId = data.thread.id;
  state.pendingFolderId = "";
  persistWorkspaceState();
  state.messages = data.messages;
  els.threadTitle.textContent = data.thread.title || "新对话";
  renderThreads();
  renderMessages();
  await loadRuns();
  await restorePendingConfirmation();
}

async function loadSkills() {
  const data = await api("/api/skills");
  state.skills = data.skills;
  renderSkills(data.skills);
  renderSkillContext();
}

async function loadModels() {
  const data = await api("/api/models");
  state.models = data.models;
  const previous = els.modelSelect.value;
  els.modelSelect.innerHTML = "";
  state.models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.name;
    option.disabled = !model.configured;
    els.modelSelect.appendChild(option);
  });
  els.modelSelect.value = state.models.some((model) => model.id === previous) ? previous : state.models[0]?.id || "";
}

function renderSkillContext() {
  state.selectedSkillIds = state.selectedSkillIds.filter((skillId) => state.skills.some((skill) => skill.id === skillId && skill.enabled));
  renderComposerSkills();
  renderSkillPicker();
}

function getPromptText() {
  return [...els.chatInput.childNodes]
    .filter((node) => !(node.nodeType === Node.ELEMENT_NODE && node.classList.contains("skill-tag")))
    .map((node) => node.textContent)
    .join("")
    .trim();
}

function getChatContent() {
  const selected = state.skills.filter((skill) => state.selectedSkillIds.includes(skill.id) && skill.enabled);
  const tags = selected.map((skill) => `@${skill.name}`).join(" ");
  return [tags, getPromptText()].filter(Boolean).join(" ");
}

function focusChatInput() {
  els.chatInput.focus();
  const range = document.createRange();
  range.selectNodeContents(els.chatInput);
  range.collapse(false);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
}

function renderComposerSkills() {
  const prompt = getPromptText();
  const selected = state.skills.filter((skill) => state.selectedSkillIds.includes(skill.id) && skill.enabled);
  els.chatInput.innerHTML = "";
  selected.forEach((skill) => {
    const tag = document.createElement("span");
    tag.className = "skill-tag";
    tag.dataset.skillId = skill.id;
    tag.setAttribute("contenteditable", "false");
    tag.textContent = `@${skill.name}`;
    els.chatInput.appendChild(tag);
  });
  if (prompt) els.chatInput.appendChild(document.createTextNode(prompt));
  const availableCount = state.skills.filter((skill) => skill.enabled).length;
  els.skillPickerButton.textContent = selected.length
    ? `已选 ${selected.length} · ${availableCount} 项可用`
    : `选择技能 · ${availableCount} 项可用`;
}

function renderSkillPicker() {
  const enabledSkills = state.skills.filter((skill) => skill.enabled);
  els.skillPickerMenu.innerHTML = "";
  if (!enabledSkills.length) {
    const empty = document.createElement("div");
    empty.className = "skill-picker-empty";
    empty.textContent = "暂无已启用技能";
    els.skillPickerMenu.appendChild(empty);
    return;
  }
  enabledSkills.forEach((skill) => {
    const item = document.createElement("label");
    item.className = "skill-picker-item";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = state.selectedSkillIds.includes(skill.id);
    input.addEventListener("change", () => {
      toggleSelectedSkill(skill.id);
      focusChatInput();
    });
    const text = document.createElement("span");
    text.textContent = skill.name;
    item.append(input, text);
    els.skillPickerMenu.appendChild(item);
  });
}

function toggleSelectedSkill(skillId) {
  state.selectedSkillIds = state.selectedSkillIds.includes(skillId)
    ? state.selectedSkillIds.filter((id) => id !== skillId)
    : [...state.selectedSkillIds, skillId];
  renderComposerSkills();
  renderSkillPicker();
}

async function loadApps() {
  const [apps, tools] = await Promise.all([api("/api/apps"), api("/api/tools")]);
  state.tools = tools.tools;
  renderApps(apps.apps, tools.tools);
}

async function loadKnowledge() {
  const data = await api("/api/knowledge");
  state.knowledgeDocuments = data.documents;
  renderKnowledge(data.documents);
}

async function loadMemories() {
  const query = els.memorySearch?.value.trim() || "";
  const data = await api(`/api/memories${query ? `?query=${encodeURIComponent(query)}` : ""}`);
  state.memories = data.memories;
  renderMemoryScopes();
  renderMemories();
}

function renderMemoryScopes() {
  if (!els.memoryScope) return;
  const selected = els.memoryScope.value;
  els.memoryScope.innerHTML = '<option value="global">所有对话</option>';
  state.folders.filter((folder) => folder.section === "project").forEach((folder) => {
    const option = document.createElement("option");
    option.value = `project:${folder.id}`;
    option.textContent = `项目：${folder.name}`;
    els.memoryScope.appendChild(option);
  });
  if ([...els.memoryScope.options].some((option) => option.value === selected)) els.memoryScope.value = selected;
}

function renderMemories() {
  els.memoryList.innerHTML = "";
  if (!state.memories.length) {
    els.memoryList.innerHTML = '<div class="empty-state"><h2>暂无长期记忆</h2><p>明确确认保存的偏好、项目事实和决策会显示在这里。</p></div>';
    return;
  }
  const labels = { preference: "个人偏好", project_fact: "项目事实", decision: "已确认决策" };
  state.memories.forEach((memory) => {
    const card = document.createElement("article");
    card.className = "capability-card memory-card";
    const scope = memory.scope_type === "project"
      ? `项目：${state.folders.find((folder) => folder.id === memory.scope_id)?.name || "已删除项目"}`
      : "所有对话";
    const status = memory.effective_status === "expired" ? "已过期" : memory.status === "active" ? "使用中" : "已停用";
    card.innerHTML = `
      <div><span class="status-pill">${labels[memory.kind] || "长期记忆"}</span></div>
      <h3>${escapeHtml(memory.content)}</h3>
      <p>${escapeHtml(scope)} · 已使用 ${memory.use_count} 次 · ${status}</p>
      <div class="card-footer memory-actions">
        <label class="switch" title="启用或停用"><input type="checkbox" ${memory.status === "active" ? "checked" : ""} ${memory.effective_status === "expired" ? "disabled" : ""} /><span></span></label>
        <div><button class="skill-action" type="button">修改</button> <button class="skill-action danger" type="button">删除</button></div>
      </div>`;
    const toggle = card.querySelector("input");
    const [editButton, deleteButton] = card.querySelectorAll("button");
    toggle.addEventListener("change", async () => {
      await api(`/api/memories/${memory.id}`, { method: "PATCH", body: JSON.stringify({ status: toggle.checked ? "active" : "disabled" }) });
      await loadMemories();
    });
    editButton.addEventListener("click", async () => {
      const content = window.prompt("修改长期记忆", memory.content)?.trim();
      if (!content || content === memory.content) return;
      await api(`/api/memories/${memory.id}`, { method: "PATCH", body: JSON.stringify({ content }) });
      await loadMemories();
    });
    deleteButton.addEventListener("click", async () => {
      if (!window.confirm("删除这条长期记忆？删除后不会再用于任何对话。")) return;
      await api(`/api/memories/${memory.id}`, { method: "DELETE" });
      await loadMemories();
    });
    els.memoryList.appendChild(card);
  });
}

async function loadArtifacts() {
  try {
    const data = await api("/api/artifacts");
    state.artifacts = data.artifacts;
    renderArtifacts();
  } catch (error) {
    // Artifacts page is secondary; failure should not block the workspace.
  }
}

function renderArtifacts() {
  els.artifactsGrid.innerHTML = "";
  els.artifactsGrid.classList.add("artifacts-grid");
  if (!state.artifacts.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<h2>暂无产物</h2><p>在对话中启用文件生成技能后，确认生成的文件会出现在这里。</p>";
    els.artifactsGrid.appendChild(empty);
    return;
  }
  state.artifacts.forEach((artifact) => {
    const card = document.createElement("article");
    card.className = "capability-card artifact-card";
    const isExcel = artifact.kind === "xlsx";
    const kindLabel = isExcel ? "Excel 文件" : "Markdown 文件";
    const extension = isExcel ? ".xlsx" : ".md";
    const icon = isExcel ? "▦" : "≡";
    const date = new Date(artifact.created_at / 1e6).toLocaleString("zh-CN");
    const generatedName = artifact.filename.startsWith("artifact_");
    const title = generatedName ? `${kindLabel} · ${date}` : artifact.filename;
    const summary = artifact.summary || "由对话确认后生成，可随时下载或删除。";
    card.innerHTML = `
      <div class="artifact-card-header">
        <span class="artifact-type-icon ${isExcel ? "excel" : "markdown"}" aria-hidden="true">${icon}</span>
        <div class="artifact-heading">
          <h3 title="${escapeHtml(artifact.filename)}">${escapeHtml(title)}</h3>
          <p class="artifact-file-name" title="${escapeHtml(artifact.filename)}">${escapeHtml(artifact.filename)}</p>
        </div>
      </div>
      <p class="artifact-summary">${escapeHtml(summary)}</p>
      <div class="artifact-meta"><span>创建于 ${date}</span><span>已确认生成</span></div>
      <div class="card-footer artifact-footer">
        <span class="artifact-kind-tag">${escapeHtml(extension.toUpperCase().slice(1))}</span>
        <div class="artifact-actions">
          <button class="skill-action" type="button">下载</button>
          <button class="skill-action danger" type="button">删除</button>
        </div>
      </div>
    `;
    const [downloadButton, deleteButton] = card.querySelectorAll(".skill-action");
    downloadButton.addEventListener("click", () => downloadArtifact(artifact));
    deleteButton.addEventListener("click", () => deleteArtifact(artifact));
    els.artifactsGrid.appendChild(card);
  });
}

async function downloadArtifact(artifact) {
  try {
    const response = await fetch(`/api/artifacts/${artifact.id}/download`, {
      headers: { Authorization: `Bearer ${state.token}` },
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "文件下载失败");
    }
    const url = URL.createObjectURL(await response.blob());
    const download = document.createElement("a");
    download.href = url;
    download.download = artifact.filename;
    document.body.appendChild(download);
    download.click();
    download.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    window.alert(error.message);
  }
}

async function deleteArtifact(artifact) {
  if (!window.confirm(`删除产物"${artifact.filename}"？此操作不可恢复。`)) return;
  await api(`/api/artifacts/${artifact.id}`, { method: "DELETE" });
  await loadArtifacts();
}

function renderKnowledge(documents) {
  els.knowledgeList.innerHTML = "";
  documents.forEach((knowledgeDocument) => {
    const card = document.createElement("article");
    card.className = "capability-card";
    const size = knowledgeDocument.size_bytes < 1024 * 1024 ? `${Math.ceil(knowledgeDocument.size_bytes / 1024)} KB` : `${(knowledgeDocument.size_bytes / 1024 / 1024).toFixed(1)} MB`;
    card.innerHTML = `
      <h3>${escapeHtml(knowledgeDocument.filename)}</h3>
      <p>${knowledgeDocument.chunk_count} 个检索片段 · ${size}</p>
      <div class="card-footer">
        <span class="status-pill">本地资料</span>
        <button class="skill-action danger" type="button">删除</button>
      </div>
    `;
    card.querySelector("button").addEventListener("click", async () => {
      if (!window.confirm(`删除资料“${knowledgeDocument.filename}”？`)) return;
      await api(`/api/knowledge/${knowledgeDocument.id}`, { method: "DELETE" });
      await loadKnowledge();
      await searchKnowledge();
    });
    els.knowledgeList.appendChild(card);
  });
}

async function searchKnowledge() {
  const query = els.knowledgeSearch.value.trim();
  if (!query) {
    els.knowledgeResults.classList.add("hidden");
    els.knowledgeResults.innerHTML = "";
    return;
  }
  const data = await api(`/api/knowledge/search?query=${encodeURIComponent(query)}`);
  els.knowledgeResults.innerHTML = "";
  els.knowledgeResults.classList.remove("hidden");
  data.results.forEach((result) => {
    const item = document.createElement("article");
    item.className = "knowledge-result";
    item.innerHTML = `<strong>${escapeHtml(result.filename)}</strong><p>${escapeHtml(result.excerpt)}</p>`;
    els.knowledgeResults.appendChild(item);
  });
  if (!data.results.length) els.knowledgeResults.textContent = "没有匹配资料。";
}

function renderThreads() {
  els.threadList.innerHTML = "";
  const query = els.threadSearch.value.trim().toLowerCase();
  const threads = state.threads.filter((thread) => thread.title.toLowerCase().includes(query));
  const grouped = new Map(state.folders.map((folder) => [folder.id, []]));
  const ungrouped = [];
  threads.forEach((thread) => {
    const group = grouped.get(thread.folder_id);
    if (group) group.push(thread);
    else ungrouped.push(thread);
  });

  const spaceFolders = state.folders.filter((folder) => folder.section === "project");
  renderThreadSection("空间", "space", spaceFolders, grouped);
  renderTaskSection(ungrouped);
}

function renderThreadSection(title, section, folders, grouped) {
  const container = document.createElement("section");
  container.className = `thread-section thread-section-${section}`;
  const header = document.createElement("div");
  header.className = "thread-section-header";
  const label = document.createElement("h2");
  label.textContent = title;
  const toggle = document.createElement("button");
  toggle.className = "section-toggle";
  const isCollapsed = state.spacesCollapsed;
  toggle.textContent = isCollapsed ? "›" : "⌄";
  toggle.title = isCollapsed ? "展开空间" : "收起空间";
  toggle.setAttribute("aria-expanded", String(!isCollapsed));
  toggle.addEventListener("click", () => {
    state.spacesCollapsed = !state.spacesCollapsed;
    renderThreads();
  });
  const createButton = document.createElement("button");
  createButton.className = "section-add-folder";
  createButton.type = "button";
  createButton.textContent = "+";
  createButton.title = "新建空间";
  createButton.setAttribute("aria-label", "新建空间");
  createButton.addEventListener("click", () => createFolder("project"));
  const titleGroup = document.createElement("div");
  titleGroup.className = "section-title-group";
  titleGroup.append(label, toggle);
  header.append(titleGroup, createButton);
  container.appendChild(header);
  if (!isCollapsed) folders.forEach((folder) => container.appendChild(createThreadGroup(folder.name, grouped.get(folder.id) || [], folder)));
  if (!isCollapsed && section === "space" && !folders.length) {
    const empty = document.createElement("p");
    empty.className = "section-empty";
    empty.textContent = "创建空间以归纳相关任务";
    container.appendChild(empty);
  }
  els.threadList.appendChild(container);
}

function renderTaskSection(tasks) {
  const container = document.createElement("section");
  container.className = "thread-section thread-section-task";
  const header = document.createElement("div");
  header.className = "thread-section-header";
  const label = document.createElement("h2");
  label.textContent = "任务";
  const toggle = document.createElement("button");
  toggle.className = "section-toggle";
  toggle.textContent = state.tasksCollapsed ? "›" : "⌄";
  toggle.title = state.tasksCollapsed ? "展开任务" : "收起任务";
  toggle.setAttribute("aria-expanded", String(!state.tasksCollapsed));
  toggle.addEventListener("click", () => { state.tasksCollapsed = !state.tasksCollapsed; renderThreads(); });
  const titleGroup = document.createElement("div");
  titleGroup.className = "section-title-group";
  titleGroup.append(label, toggle);
  header.appendChild(titleGroup);
  container.appendChild(header);
  if (!state.tasksCollapsed) tasks.forEach((task) => container.appendChild(createThreadRow(task)));
  els.threadList.appendChild(container);
}

function createThreadGroup(title, threads, folder = null) {
  const group = document.createElement("section");
  group.className = `thread-group ${folder ? "thread-folder-group" : "thread-ungrouped-group"}`;
  const collapsed = folder && state.collapsedFolderIds.has(folder.id);
  group.classList.toggle("collapsed", Boolean(collapsed));
  const header = document.createElement("div");
  header.className = "thread-group-header";
  const heading = document.createElement("div");
  heading.className = "thread-group-title";
  if (folder) {
    heading.classList.add("folder-toggle");
    const icon = document.createElement("span");
    icon.className = "space-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.innerHTML = '<svg viewBox="0 0 24 24" focusable="false"><path d="m12 3.8 7 4v8.1l-7 4.3-7-4.3V7.8z"></path><path d="m5 7.8 7 4.2 7-4.2M12 12v8.2"></path></svg>';
    const openButton = document.createElement("button");
    openButton.className = "space-open-button";
    openButton.type = "button";
    openButton.title = `打开空间：${folder.name}`;
    openButton.addEventListener("click", () => openSpace(folder.id));
    openButton.appendChild(icon);
    heading.appendChild(openButton);
  }
  const label = document.createElement("span");
  label.className = folder ? "folder-name" : "ungrouped-label";
  label.textContent = title;
  if (folder) {
    const openName = document.createElement("button");
    openName.className = "space-open-button folder-name";
    openName.type = "button";
    openName.textContent = title;
    openName.addEventListener("click", () => openSpace(folder.id));
    heading.appendChild(openName);
  } else heading.appendChild(label);
  header.appendChild(heading);
  if (folder) {
    const controls = document.createElement("div");
    controls.className = "folder-controls";
    const newThread = document.createElement("button");
    newThread.className = "folder-new-thread";
    newThread.type = "button";
    newThread.textContent = "+";
    newThread.title = `在“${folder.name}”中新建任务`;
    newThread.setAttribute("aria-label", `在“${folder.name}”中新建任务`);
    newThread.addEventListener("click", () => startThreadInFolder(folder));
    const sectionFolders = state.folders.filter((item) => item.section === folder.section);
    const currentIndex = sectionFolders.findIndex((item) => item.id === folder.id);
    const up = document.createElement("button");
    up.className = "folder-order";
    up.type = "button";
    up.textContent = "↑";
    up.title = "上移文件夹";
    up.disabled = currentIndex <= 0;
    up.addEventListener("click", () => moveFolder(folder, currentIndex - 1));
    const down = document.createElement("button");
    down.className = "folder-order";
    down.type = "button";
    down.textContent = "↓";
    down.title = "下移文件夹";
    down.disabled = currentIndex < 0 || currentIndex >= sectionFolders.length - 1;
    down.addEventListener("click", () => moveFolder(folder, currentIndex + 1));
    const menu = document.createElement("button");
    menu.className = "folder-menu";
    menu.type = "button";
    menu.textContent = "⋯";
    menu.title = `管理空间：${folder.name}`;
    menu.setAttribute("aria-label", `管理空间：${folder.name}`);
    menu.addEventListener("click", () => manageFolder(folder));
    const disclosure = document.createElement("button");
    disclosure.className = "folder-disclosure";
    disclosure.type = "button";
    disclosure.textContent = "›";
    disclosure.title = collapsed ? `展开空间：${folder.name}` : `收起空间：${folder.name}`;
    disclosure.setAttribute("aria-expanded", String(!collapsed));
    disclosure.addEventListener("click", () => {
      if (state.collapsedFolderIds.has(folder.id)) state.collapsedFolderIds.delete(folder.id);
      else state.collapsedFolderIds.add(folder.id);
      renderThreads();
    });
    heading.appendChild(disclosure);
    controls.append(newThread, menu);
    header.appendChild(controls);
  }
  group.appendChild(header);
  threads.forEach((thread) => group.appendChild(createThreadRow(thread)));
  return group;
}

function createThreadRow(thread) {
    const row = document.createElement("div");
    row.className = "thread-row";
    const button = document.createElement("button");
    button.className = `thread-item ${thread.id === state.currentThreadId ? "active" : ""}`;
    button.textContent = thread.title;
    button.title = thread.title;
    button.addEventListener("click", () => {
      switchView("chat");
      loadThread(thread.id);
    });
    const menu = document.createElement("button");
    menu.className = "thread-menu";
    menu.type = "button";
    menu.textContent = "⋯";
    menu.setAttribute("aria-label", `管理对话：${thread.title}`);
    menu.addEventListener("click", () => manageThread(thread));
    row.append(button, menu);
    return row;
}

async function openSpace(spaceId) {
  const data = await api(`/api/folders/${spaceId}`);
  els.spaceTitle.textContent = data.space.name;
  const empty = (text) => `<p class="space-empty">${text}</p>`;
  const tasks = data.tasks.map((item) => `<button class="space-list-item space-task-link" data-thread-id="${escapeHtml(item.id)}"><span>${escapeHtml(item.title)}</span><small>打开任务</small></button>`).join("") || empty("该空间暂时没有任务");
  const artifacts = data.artifacts.map((item) => `<button class="space-list-item space-artifact-link" data-artifact-id="${escapeHtml(item.id)}"><span>${escapeHtml(item.filename)}</span><small>${escapeHtml(item.kind.toUpperCase())} · 关联任务：${escapeHtml(item.task_title || "未命名任务")}</small></button>`).join("") || empty("该空间暂时没有产物");
  const sources = data.sources.map((item) => `<div class="space-list-item space-source"><span>${escapeHtml(item.title)}</span><small>${item.kind === "web" ? "网页" : "本地资料"} · 关联任务：${escapeHtml(item.task_title)}</small>${item.excerpt ? `<em>${escapeHtml(item.excerpt)}</em>` : ""}</div>`).join("") || empty("空间内任务尚未引用资料或网页来源");
  if (!state.demoMembersBySpace[spaceId]) state.demoMembersBySpace[spaceId] = [{ id: "demo-linran", name: "林然", role: "member", demo: true }, { id: "demo-zhouning", name: "周宁", role: "member", demo: true }];
  const demoMembers = data.members.length <= 1 ? state.demoMembersBySpace[spaceId] : [];
  const members = [...data.members, ...demoMembers].map((item) => {
    const name = item.name || item.email;
    const initial = escapeHtml(name.slice(0, 1).toUpperCase());
    const removable = item.role !== "owner";
    return `<div class="space-member"><span class="member-avatar" aria-hidden="true">${initial}</span><span class="member-name">${escapeHtml(name)}${item.demo ? '<small>演示成员</small>' : ""}</span><span class="member-role">${escapeHtml(item.role === "owner" ? "所有者" : "成员")}</span>${removable ? `<button class="remove-space-member" data-member-id="${escapeHtml(item.id)}" data-demo="${item.demo ? "true" : "false"}" type="button" aria-label="移除 ${escapeHtml(name)}">×</button>` : '<span class="member-lock" title="空间所有者不可移除">•</span>'}</div>`;
  }).join("") || empty("暂未添加成员");
  const pending = data.invitations.filter((item) => item.status === "pending").map((item) => `<div class="space-invitation">已邀请 ${escapeHtml(item.email)} · 待加入</div>`).join("");
  els.spaceDetail.innerHTML = `<div class="space-layout"><div class="space-overview"><section class="space-card"><div class="space-card-heading"><h3>任务</h3><span>${data.tasks.length}</span></div>${tasks}</section><section class="space-card"><div class="space-card-heading"><h3>产物</h3><span>${data.artifacts.length}</span></div>${artifacts}</section><section class="space-card space-card-wide"><div class="space-card-heading"><h3>来源</h3><span>${data.sources.length}</span></div>${sources}</section></div><aside class="space-members-panel"><div class="space-card-heading"><h3>成员</h3><button id="inviteSpaceMember" type="button">邀请成员</button></div>${members}${pending}</aside></div>`;
  els.spaceDetail.querySelectorAll(".space-task-link").forEach((button) => button.addEventListener("click", () => { switchView("chat"); loadThread(button.dataset.threadId); }));
  els.spaceDetail.querySelectorAll(".space-artifact-link").forEach((button) => button.addEventListener("click", () => downloadArtifact({ id: button.dataset.artifactId })));
  els.spaceDetail.querySelectorAll(".remove-space-member").forEach((button) => button.addEventListener("click", async () => {
    if (!window.confirm("移除该成员？")) return;
    if (button.dataset.demo === "true") state.demoMembersBySpace[spaceId] = state.demoMembersBySpace[spaceId].filter((member) => member.id !== button.dataset.memberId);
    else await api(`/api/folders/${spaceId}/members/${button.dataset.memberId}`, { method: "DELETE" });
    await openSpace(spaceId);
  }));
  document.querySelector("#inviteSpaceMember").addEventListener("click", async () => {
    const email = window.prompt("输入成员邮箱");
    if (!email?.trim()) return;
    await api(`/api/folders/${spaceId}/invitations`, { method: "POST", body: JSON.stringify({ email }) });
    await openSpace(spaceId);
  });
  switchView("space");
}

async function manageThread(thread) {
  const action = window.prompt("输入 r 重命名，输入 m 移动到空间，输入 d 删除", "r");
  if (action === "r") {
    const title = window.prompt("输入新的对话名称", thread.title);
    if (!title?.trim()) return;
    await api(`/api/threads/${thread.id}`, { method: "PATCH", body: JSON.stringify({ title }) });
    await refreshThreadList();
    if (thread.id === state.currentThreadId) els.threadTitle.textContent = title.trim();
  }
  if (action === "m") {
    const spaces = state.folders.filter((folder) => folder.section === "project");
    const choices = ["0. 任务", ...spaces.map((folder, index) => `${index + 1}. [空间] ${folder.name}`)];
    const selected = window.prompt(`输入目标序号：\n${choices.join("\n")}`, "0");
    if (selected === null) return;
    const index = Number.parseInt(selected, 10);
    if (!Number.isInteger(index) || index < 0 || index > spaces.length) {
      window.alert("请输入有效的空间序号。");
      return;
    }
    const folderId = index === 0 ? "" : spaces[index - 1].id;
    await api(`/api/threads/${thread.id}`, { method: "PATCH", body: JSON.stringify({ folder_id: folderId }) });
    await refreshThreadList();
  }
  if (action === "d" && window.confirm(`删除“${thread.title}”？此操作不可恢复。`)) {
    await api(`/api/threads/${thread.id}`, { method: "DELETE" });
    if (thread.id === state.currentThreadId) {
      state.currentThreadId = "";
      state.messages = [];
      persistWorkspaceState();
      renderMessages();
    }
    await refreshThreadList();
  }
}

async function createFolder(section) {
  const name = window.prompt("输入空间名称");
  if (!name?.trim()) return;
  try {
    await api("/api/folders", { method: "POST", body: JSON.stringify({ name, section }) });
    await refreshThreadList();
  } catch (error) {
    window.alert(`创建空间失败：${error.message}`);
  }
}

async function startThreadInFolder(folder) {
  state.pendingFolderId = folder.id;
  state.currentThreadId = "";
  state.messages = [];
  state.runs = [];
  state.threadContext = { sources: [], outputs: [] };
  state.selectedSkillIds = [];
  renderComposerSkills();
  renderSkillPicker();
  els.threadTitle.textContent = `新建任务 · ${folder.name}`;
  switchView("chat");
  renderThreads();
  renderMessages();
  renderThreadContext();
  els.runDetailsButton.disabled = true;
  els.runDrawer.classList.add("hidden");
  focusChatInput();
}

async function manageFolder(folder) {
  const action = window.prompt("输入 r 重命名，输入 u 上移，输入 n 下移，输入 d 删除空间", "r");
  if (action === "r") {
    const name = window.prompt("输入新的空间名称", folder.name);
    if (!name?.trim()) return;
    await api(`/api/folders/${folder.id}`, { method: "PATCH", body: JSON.stringify({ name }) });
    await refreshThreadList();
  }
  if (action === "d" && window.confirm(`删除空间“${folder.name}”？其中的任务会移入“任务”。`)) {
    await api(`/api/folders/${folder.id}`, { method: "DELETE" });
    await refreshThreadList();
  }
  if (action === "u" || action === "n") {
    const spaces = state.folders.filter((item) => item.section === "project");
    const index = spaces.findIndex((item) => item.id === folder.id);
    await moveFolder(folder, action === "u" ? index - 1 : index + 1);
  }
}

async function moveFolder(folder, position) {
  try {
    await api(`/api/folders/${folder.id}`, { method: "PATCH", body: JSON.stringify({ position }) });
    await refreshThreadList();
  } catch (error) {
    window.alert(`调整文件夹位置失败：${error.message}`);
  }
}

async function loadRuns() {
  state.runs = [];
  els.runDetailsButton.disabled = !state.currentThreadId;
  if (!state.currentThreadId) {
    state.threadContext = { sources: [], outputs: [] };
    renderThreadContext();
    return;
  }
  const data = await api(`/api/threads/${state.currentThreadId}/runs`);
  state.runs = data.runs;
  renderRuns();
  await loadThreadContext();
}

async function loadAuditRuns() {
  const params = new URLSearchParams();
  if (els.runStatusFilter.value) params.set("status", els.runStatusFilter.value);
  if (els.runTierFilter.value) params.set("tier", els.runTierFilter.value);
  if (els.runKnowledgeFilter.value) params.set("knowledge", els.runKnowledgeFilter.value);
  const data = await api(`/api/runs?${params.toString()}`);
  state.runs = data.runs;
  renderRuns();
  els.runDetail.textContent = "已按筛选条件显示最近 200 条运行。选择一条查看可审计详情。";
}

async function loadThreadContext() {
  if (!state.currentThreadId) return;
  const data = await api(`/api/threads/${state.currentThreadId}/context`);
  state.threadContext = {
    sources: Array.isArray(data.sources) ? data.sources : [],
    outputs: Array.isArray(data.outputs) ? data.outputs : [],
  };
  renderThreadContext();
}

function renderThreadContext() {
  const { sources = [], outputs = [] } = state.threadContext;
  const hasThread = Boolean(state.currentThreadId);
  els.threadContextCount.textContent = hasThread ? `${sources.length + outputs.length} 项` : "新对话";
  renderContextList(els.threadOutputs, outputs, "暂无文件输出", (artifact) => {
    const kind = artifact.kind === "xlsx" ? "Excel 文件" : "Markdown 文件";
    return {
      icon: "↧",
      title: artifact.filename,
      detail: `${kind}${artifact.summary ? ` · ${artifact.summary}` : ""}`,
      onClick: () => downloadArtifact(artifact),
      titleAttr: "下载此对话生成的文件",
    };
  });
  renderContextList(els.threadSources, sources, "本次对话尚未命中资料或网页来源", (source) => {
    if (source.kind === "web") {
      return {
        icon: "◌",
        title: source.title || "网页来源",
        detail: source.excerpt || source.url,
        onClick: () => window.open(source.url, "_blank", "noopener,noreferrer"),
        titleAttr: "打开网页来源",
      };
    }
    return {
      icon: "⌕",
      title: source.filename,
      detail: `片段 ${source.position + 1}${source.excerpt ? ` · ${source.excerpt}` : ""}`,
      onClick: async () => {
        switchView("knowledge");
        els.knowledgeSearch.value = source.filename;
        await searchKnowledge();
      },
      titleAttr: "在知识库中查看此来源",
    };
  });
}

function renderContextList(container, items, emptyText, createItem) {
  container.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "context-empty";
    empty.textContent = emptyText;
    container.appendChild(empty);
    return;
  }
  items.slice(0, 4).forEach((item) => {
    const definition = createItem(item);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "context-item";
    button.title = definition.titleAttr;
    const icon = document.createElement("span");
    icon.className = "context-item-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = definition.icon;
    const text = document.createElement("span");
    text.className = "context-item-text";
    const title = document.createElement("strong");
    title.textContent = definition.title;
    const detail = document.createElement("small");
    detail.textContent = definition.detail;
    text.append(title, detail);
    button.append(icon, text);
    button.addEventListener("click", definition.onClick);
    container.appendChild(button);
  });
}

async function restorePendingConfirmation() {
  const pending = state.runs.find((run) => run.status === "awaiting_confirmation");
  if (!pending || els.messages.querySelector(".confirmation-actions")) return;
  const detail = await api(`/api/runs/${pending.id}`);
  if (!detail.confirmation || detail.confirmation.status !== "pending") return;
  const assistant = appendAssistantMessage();
  assistant.status.textContent = "处理状态 · 等待你的确认";
  assistant.content.textContent = detail.confirmation.request;
  const context = safeJson(detail.run.execution_context, {});
  appendConfirmationActions(assistant, {
    run_id: pending.id,
    request: detail.confirmation.request,
    kind: context.artifact_request?.kind || "",
  }, "");
}

function renderRuns() {
  els.runList.innerHTML = "";
  state.runs.forEach((run) => {
    const button = document.createElement("button");
    button.className = `run-item ${run.status}`;
    const statusLabel = run.status === "completed" ? "已完成"
      : run.status === "failed" ? "失败"
        : run.status === "cancelled" ? "已取消"
          : run.status === "awaiting_confirmation" ? "待确认"
            : "运行中";
    button.textContent = `${statusLabel} · ${run.model}`;
    button.addEventListener("click", () => loadRunDetail(run.id));
    els.runList.appendChild(button);
  });
  if (!state.runs.length) els.runDetail.textContent = "当前对话还没有运行记录。";
}

async function loadRunDetail(runId) {
  const data = await api(`/api/runs/${runId}`);
  const { run, events, steps, artifact } = data;
  const elapsed = run.completed_at ? `${Math.max(0, Math.round((run.completed_at - run.started_at) / 1e9 * 10) / 10)} 秒` : "运行中";
  const skills = JSON.parse(run.skill_snapshot || "[]").map((skill) => skill.name).join("、") || "无";
  const plan = steps?.length ? steps : safeJson(run.plan_snapshot, []);
  const context = safeJson(run.execution_context, {});
  const reflection = safeJson(run.reflection_snapshot, {});
  const toolEvents = events.filter((event) => ["tool_call", "tool_result", "tool_error"].includes(event.type));
  const planText = plan.length ? plan.map((step) => `${step.title}（${step.status}）`).join(" → ") : "无";
  const tools = context.tools?.map((tool) => tool.name).join("、") || "无";
  const toolRoute = context.tool_route_reason || "未记录";
  const route = context.model_route_reason || "未记录";
  const tier = context.task_tier || "standard";
  const toolTrace = toolEvents.length ? toolEvents.map((event) => event.type).join(" → ") : "未调用工具";
  const reflectionText = reflection.applied
    ? `${reflection.summary || "已完成"}${reflection.revision_count ? `，已修订 ${reflection.revision_count} 次` : ""}`
    : "未触发";
  const modes = context.execution_modes || {};
  const routeSummary = context.route_summary || {};
  const modesText = `资料：${modes.source || "general"}｜知识库：${modes.knowledge || "auto"}（${routeSummary.knowledge_matches ?? context.knowledge_match_count ?? 0} 条）｜网络：${modes.web || "auto"}｜文件：${modes.file || "auto"}｜记忆：${routeSummary.memory_count ?? context.memories?.length ?? 0} 条`;
  const requiredErrors = context.required_tool_errors?.length ? `\n必需能力：${context.required_tool_errors.join("；")}` : "";
  els.runDetail.textContent = `模型：${run.model}\n任务档位：${tier}\n路由：${route}\n执行方式：${modesText}\n输出预算：${context.max_output_tokens || "未记录"}\n状态：${run.status}\n执行阶段：${run.run_phase || "未记录"}\n耗时：${elapsed}\n技能：${skills}\n计划：${planText}\n允许工具：${tools}\n工具判断：${toolRoute}\n工具执行：${toolTrace}\n质量检查：${reflectionText}${requiredErrors}${run.error ? `\n错误：${run.error}` : ""}`;

  if (artifact) {
    const artifactBlock = document.createElement("div");
    artifactBlock.style.cssText = "margin-top:14px;padding-top:14px;border-top:1px solid var(--line)";
    const link = document.createElement("a");
    link.className = "artifact-link";
    link.href = "#";
    link.textContent = `下载文件：${artifact.filename}`;
    link.title = artifact.summary || "下载生成的文件";
    link.addEventListener("click", async (event) => {
      event.preventDefault();
      link.setAttribute("aria-busy", "true");
      const originalText = link.textContent;
      link.textContent = "正在下载文件...";
      try {
        const response = await fetch(`/api/artifacts/${artifact.id}/download`, {
          headers: { Authorization: `Bearer ${state.token}` },
        });
        if (!response.ok) {
          const errData = await response.json().catch(() => ({}));
          throw new Error(errData.error || "文件下载失败");
        }
        const url = URL.createObjectURL(await response.blob());
        const download = document.createElement("a");
        download.href = url;
        download.download = artifact.filename;
        document.body.appendChild(download);
        download.click();
        download.remove();
        URL.revokeObjectURL(url);
        link.textContent = originalText;
      } catch (error) {
        link.textContent = error.message || "文件下载失败";
        window.setTimeout(() => { link.textContent = originalText; }, 2500);
      } finally {
        link.removeAttribute("aria-busy");
      }
    });
    artifactBlock.appendChild(link);
    els.runDetail.appendChild(artifactBlock);
  }

  if (context.knowledge_refs?.length) {
    const feedback = document.createElement("div");
    feedback.className = "confirmation-actions run-feedback";
    const label = document.createElement("span");
    label.textContent = "本次引用是否准确？";
    feedback.append(label);
    [[true, "引用准确"], [false, "引用有误"]].forEach(([citationCorrect, text]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = text;
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await api(`/api/runs/${run.id}/feedback`, { method: "POST", body: JSON.stringify({ rating: citationCorrect ? 1 : -1, citation_correct: citationCorrect }) });
          feedback.replaceChildren(Object.assign(document.createElement("span"), { textContent: "已记录引用评价" }));
        } catch (error) {
          button.disabled = false;
          button.textContent = error.message || "提交失败";
        }
      });
      feedback.append(button);
    });
    els.runDetail.appendChild(feedback);
  }

  if (["running", "awaiting_confirmation"].includes(run.status)) {
    const actions = document.createElement("div");
    actions.className = "confirmation-actions";
    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.className = "secondary";
    cancelButton.textContent = run.status === "awaiting_confirmation" ? "取消待确认任务" : "取消运行";
    cancelButton.addEventListener("click", async () => {
      cancelButton.disabled = true;
      try {
        await api(`/api/runs/${run.id}/cancel`, { method: "POST", body: "{}" });
        await loadRuns();
        await loadRunDetail(run.id);
      } catch (error) {
        cancelButton.disabled = false;
        cancelButton.textContent = error.message || "取消失败";
      }
    });
    actions.appendChild(cancelButton);
    els.runDetail.appendChild(actions);
  }
}

function safeJson(value, fallback) {
  try {
    return JSON.parse(value || "");
  } catch (error) {
    return fallback;
  }
}

function renderMessages() {
  els.messages.innerHTML = "";
  if (!state.messages.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = "<h1>今天要完成什么？</h1><p>输入任务后，Agent 会根据已启用的技能回复。</p>";
    els.messages.appendChild(empty);
    els.threadTitle.textContent = state.currentThreadId ? els.threadTitle.textContent : "新对话";
    return;
  }
  state.messages.forEach((message) => {
    appendMessage(message.role, message.content);
  });
}

function appendMessage(role, content) {
  const wrapper = document.createElement("article");
  wrapper.className = `message ${role}`;
  const label = role === "user" ? "你" : "Agent_Platform";
  wrapper.innerHTML = `
    <div class="message-role">${label}</div>
    ${role === "assistant" ? '<div class="answer-label">最终回答</div>' : ""}
    <div class="message-content"></div>
  `;
  renderMessageContent(wrapper.querySelector(".message-content"), content, role);
  els.messages.appendChild(wrapper);
  els.messages.scrollTop = els.messages.scrollHeight;
  return wrapper.querySelector(".message-content");
}

function renderMessageContent(element, content, role = "assistant") {
  element.textContent = "";
  if (role !== "assistant") {
    element.textContent = content;
    return;
  }
  const marker = "\n\n参考资料：";
  const markerIndex = content.lastIndexOf(marker);
  const answer = markerIndex === -1 ? content : content.slice(0, markerIndex);
  element.appendChild(renderMarkdown(answer));
  if (markerIndex === -1) return;

  const references = document.createElement("div");
  references.className = "message-sources";
  const label = document.createElement("span");
  label.className = "message-sources-label";
  label.textContent = "本地资料命中";
  references.append(label);
  content.slice(markerIndex + marker.length).split("、").filter(Boolean).forEach((sourceLabel) => {
    const source = document.createElement("button");
    source.type = "button";
    source.className = "knowledge-source-link";
    const filename = sourceLabel.replace(/（片段\s*\d+(?:\s*·\s*摘录：[\s\S]*)?）$/, "");
    source.textContent = sourceLabel;
    source.title = `查看本地资料：${filename}`;
    source.addEventListener("click", async () => {
      switchView("knowledge");
      els.knowledgeSearch.value = filename;
      await searchKnowledge();
    });
    references.append(source);
  });
  element.append(references);
}

function renderMarkdown(markdown) {
  const root = document.createElement("div");
  root.className = "markdown-body";
  const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (line.startsWith("```")) {
      const language = line.slice(3).trim();
      const codeLines = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      if (language) code.dataset.language = language;
      code.textContent = codeLines.join("\n");
      pre.appendChild(code);
      root.appendChild(pre);
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      const level = String(heading[1].length + 2);
      const title = document.createElement(`h${level}`);
      renderInline(title, heading[2].trim());
      root.appendChild(title);
      index += 1;
      continue;
    }

    if (/^>\s?/.test(line)) {
      const quote = document.createElement("blockquote");
      const quoteLines = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      renderInline(quote, quoteLines.join("\n"));
      root.appendChild(quote);
      continue;
    }

    const listMatch = /^(\s*)([-*]|\d+\.)\s+(.+)$/.exec(line);
    if (listMatch) {
      const ordered = /\d+\./.test(listMatch[2]);
      const list = document.createElement(ordered ? "ol" : "ul");
      while (index < lines.length) {
        const itemMatch = /^(\s*)([-*]|\d+\.)\s+(.+)$/.exec(lines[index]);
        if (!itemMatch || (/\d+\./.test(itemMatch[2]) !== ordered)) break;
        const item = document.createElement("li");
        renderInline(item, itemMatch[3].trim());
        list.appendChild(item);
        index += 1;
      }
      root.appendChild(list);
      continue;
    }

    const paragraphLines = [line.trim()];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !lines[index].startsWith("```") &&
      !/^(#{1,3})\s+/.test(lines[index]) &&
      !/^>\s?/.test(lines[index]) &&
      !/^(\s*)([-*]|\d+\.)\s+/.test(lines[index])
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    const paragraph = document.createElement("p");
    renderInline(paragraph, paragraphLines.join("\n"));
    root.appendChild(paragraph);
  }

  return root;
}

function renderInline(element, text) {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
  let lastIndex = 0;
  for (const match of String(text).matchAll(pattern)) {
    if (match.index > lastIndex) {
      element.append(document.createTextNode(text.slice(lastIndex, match.index)));
    }
    const token = match[0];
    if (token.startsWith("`")) {
      const code = document.createElement("code");
      code.textContent = token.slice(1, -1);
      element.appendChild(code);
    } else if (token.startsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = token.slice(2, -2);
      element.appendChild(strong);
    } else if (token.startsWith("*")) {
      const emphasis = document.createElement("em");
      emphasis.textContent = token.slice(1, -1);
      element.appendChild(emphasis);
    } else {
      const linkMatch = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(token);
      const link = document.createElement("a");
      link.href = linkMatch[2];
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = linkMatch[1];
      element.appendChild(link);
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) {
    element.append(document.createTextNode(text.slice(lastIndex)));
  }
}

function appendAssistantMessage() {
  const wrapper = document.createElement("article");
  wrapper.className = "message assistant";
  wrapper.innerHTML = `
    <div class="message-role">Agent_Platform</div>
    <div class="assistant-status">处理状态 · 正在准备运行</div>
    <div class="answer-label">最终回答</div>
    <div class="message-content"></div>
  `;
  els.messages.appendChild(wrapper);
  els.messages.scrollTop = els.messages.scrollHeight;
  return {
    wrapper,
    status: wrapper.querySelector(".assistant-status"),
    content: wrapper.querySelector(".message-content"),
  };
}

function renderSkills(skills) {
  els.skillsGrid.innerHTML = "";
  skills.forEach((skill) => {
    const card = document.createElement("article");
    card.className = "capability-card";
    card.innerHTML = `
      <h3>${escapeHtml(skill.name)}</h3>
      <p class="skill-description" title="${escapeHtml(skill.description || skill.prompt || "")}">${escapeHtml(skillSummary(skill))}</p>
      <div class="card-footer">
        <div class="skill-state">
          <span class="status-pill">${skill.enabled ? "已启用" : "未启用"}</span>
          <label class="switch" title="启用或禁用技能">
            <input type="checkbox" ${skill.enabled ? "checked" : ""} />
            <span></span>
          </label>
        </div>
        <div class="skill-actions">
          <button class="skill-action" type="button" title="编辑技能">编辑</button>
          <button class="skill-action" type="button" title="查看或回滚历史版本">版本</button>
          <button class="skill-action danger" type="button" title="删除技能">删除</button>
        </div>
      </div>
    `;
    const input = card.querySelector("input");
    const pill = card.querySelector(".status-pill");
    input.addEventListener("change", async () => {
      try {
        await api(`/api/skills/${skill.id}`, {
          method: "PATCH",
          body: JSON.stringify({ enabled: input.checked }),
        });
        pill.textContent = input.checked ? "已启用" : "未启用";
        skill.enabled = input.checked;
        renderSkillContext();
      } catch (error) {
        input.checked = !input.checked;
        window.alert(error.message);
      }
    });
    const [editButton, versionButton, deleteButton] = card.querySelectorAll(".skill-action");
    editButton.addEventListener("click", () => editSkill(skill));
    versionButton.addEventListener("click", () => restoreSkillVersion(skill));
    deleteButton.addEventListener("click", () => deleteSkill(skill));
    els.skillsGrid.appendChild(card);
  });
}

function skillSummary(skill) {
  const source = String(skill.description || skill.prompt || "暂无技能说明");
  const normalized = source
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/[`*_]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return normalized.length > 150 ? `${normalized.slice(0, 147).trimEnd()}…` : normalized;
}

async function editSkill(skill) {
  const full = (await api(`/api/skills/${skill.id}`)).skill;
  const name = window.prompt("技能标题", full.name);
  if (!name?.trim()) return;
  const prompt = window.prompt("技能内容", full.prompt || "");
  if (prompt === null || !prompt.trim()) return;
  const updated = { ...full, prompt, description: prompt, id: skill.id, name: name.trim() };
  await api(`/api/skills/${skill.id}`, { method: "PATCH", body: JSON.stringify({ skill: updated }) });
  await loadSkills();
}

async function deleteSkill(skill) {
  if (!window.confirm(`删除技能“${skill.name}”？已有运行记录不会受影响。`)) return;
  await api(`/api/skills/${skill.id}`, { method: "DELETE" });
  await loadSkills();
}

async function restoreSkillVersion(skill) {
  const { versions } = await api(`/api/skills/${skill.id}/versions`);
  if (!versions.length) {
    window.alert("当前技能还没有可回滚的历史版本。");
    return;
  }
  const choices = versions.map((version, index) => `${index + 1}. ${version.version}`).join("\n");
  const selected = Number(window.prompt(`选择要恢复的版本：\n${choices}`, "1"));
  if (!Number.isInteger(selected) || selected < 1 || selected > versions.length) return;
  if (!window.confirm(`恢复“${skill.name}”到 ${versions[selected - 1].version}？`)) return;
  await api(`/api/skills/${skill.id}/restore`, {
    method: "POST",
    body: JSON.stringify({ archive: versions[selected - 1].archive }),
  });
  await loadSkills();
}

function renderApps(apps, tools = []) {
  els.appsGrid.innerHTML = "";
  apps.forEach((app) => {
    const card = document.createElement("article");
    card.className = "capability-card";
    card.innerHTML = `
      <h3>${escapeHtml(app.name)}</h3>
      <p>${escapeHtml(app.description)}</p>
      <div class="card-footer">
        <span class="status-pill">${escapeHtml(app.status)}</span>
      </div>
    `;
    els.appsGrid.appendChild(card);
  });
  tools.forEach((tool) => {
    const card = document.createElement("article");
    card.className = "capability-card tool-card";
    const heading = document.createElement("h3");
    heading.textContent = tool.name;
    const description = document.createElement("p");
    description.textContent = tool.description;
    const form = document.createElement("form");
    form.className = "tool-form";
    const properties = tool.input_schema?.properties || {};
    Object.entries(properties).forEach(([key, definition]) => {
      const label = document.createElement("label");
      label.textContent = definition.description || key;
      const input = document.createElement("input");
      input.name = key;
      input.type = definition.type === "integer" ? "number" : "text";
      input.required = (tool.input_schema?.required || []).includes(key);
      if (definition.type === "integer") input.min = key === "limit" ? "1" : "";
      label.appendChild(input);
      form.appendChild(label);
    });
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.textContent = tool.enabled ? "执行" : "未启用";
    submit.disabled = !tool.enabled;
    const result = document.createElement("pre");
    result.className = "tool-result hidden";
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const argumentsValue = {};
      Object.entries(properties).forEach(([key, definition]) => {
        const raw = form.elements[key]?.value.trim();
        if (raw !== "") argumentsValue[key] = definition.type === "integer" ? Number(raw) : raw;
      });
      submit.disabled = true;
      result.classList.remove("hidden");
      result.textContent = "正在执行…";
      try {
        const response = await api(`/api/tools/${tool.id}/execute`, { method: "POST", body: JSON.stringify({ arguments: argumentsValue }) });
        result.textContent = JSON.stringify(response.result, null, 2);
      } catch (error) {
        result.textContent = `执行失败：${error.message}\n修改参数后可再次执行。`;
      } finally {
        submit.disabled = !tool.enabled;
      }
    });
    form.append(submit, result);
    const footer = document.createElement("div");
    footer.className = "card-footer";
    footer.innerHTML = `<span class="status-pill">${tool.enabled ? "本地只读工具" : "未启用"}</span>`;
    card.append(heading, description, form, footer);
    els.appsGrid.appendChild(card);
  });
}

function switchView(view) {
  state.activeView = view;
  persistWorkspaceState();
  els.chatPage.classList.toggle("hidden", view !== "chat");
  els.spacePage.classList.toggle("hidden", view !== "space");
  els.skillsPage.classList.toggle("hidden", view !== "skills");
  els.settingsPage.classList.toggle("hidden", view !== "settings");
  els.knowledgePage.classList.toggle("hidden", view !== "knowledge");
  els.memoriesPage.classList.toggle("hidden", view !== "memories");
  els.artifactsPage.classList.toggle("hidden", view !== "artifacts");
  els.threadContextPanel.classList.toggle("hidden", view !== "chat");
  if (view === "artifacts") loadArtifacts();
  if (view === "memories") loadMemories();
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
}

async function sendMessage(content, { retry = false } = {}) {
  if (state.streaming) return;
  state.streaming = true;
  els.sendButton.disabled = true;
  els.sendButton.textContent = "发送中";

  let assistant;
  let assistantContent = "";
  let awaitingConfirmation = false;
  let cancelled = false;
  try {
    if (!state.messages.length && !retry) {
      els.messages.innerHTML = "";
    }
    if (!retry) {
      state.messages.push({ role: "user", content });
      appendMessage("user", content);
    }
    assistant = appendAssistantMessage();

    const chatPayload = {
      thread_id: state.currentThreadId,
      content,
      retry,
      model: els.modelSelect.value,
      task_mode: els.taskModeSelect.value,
      source_mode: els.sourceModeSelect.value,
      knowledge_mode: els.knowledgeModeSelect.value,
      web_mode: els.webModeSelect.value,
      file_mode: els.fileModeSelect.value,
    };
    if (!state.currentThreadId && state.pendingFolderId) chatPayload.folder_id = state.pendingFolderId;
    if (state.selectedSkillIds.length) chatPayload.skill_ids = state.selectedSkillIds;
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${state.token}`,
      },
      body: JSON.stringify(chatPayload),
    });

    if (!response.ok || !response.body) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "发送失败");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";
      for (const eventText of events) {
        const event = parseSse(eventText);
        if (event.event === "meta") {
          state.currentThreadId = event.data.thread_id;
          state.pendingFolderId = "";
          persistWorkspaceState();
          assistant.status.textContent = `处理状态 · 正在调用 ${event.data.model}`;
        }
        if (event.event === "status") {
          assistant.status.textContent = `处理状态 · ${event.data.summary || "正在执行"}`;
        }
        if (event.event === "delta") {
          assistantContent += event.data.content;
          assistant.content.textContent = assistantContent;
          els.messages.scrollTop = els.messages.scrollHeight;
        }
        if (event.event === "confirmation") {
          awaitingConfirmation = true;
          assistant.status.textContent = "处理状态 · 等待你的确认";
          assistant.content.textContent = event.data.request || "此操作需要确认后才能执行。";
          appendConfirmationActions(assistant, event.data, content);
        }
        if (event.event === "cancelled") {
          cancelled = true;
          assistant.status.textContent = "处理状态 · 已取消";
          assistant.content.textContent = "本次运行已取消，未保存后续回答。";
        }
        if (event.event === "error") {
          throw new Error(event.data.error || "运行失败");
        }
      }
    }
    if (cancelled) return;
    if (!assistantContent && !awaitingConfirmation) {
      throw new Error("模型未返回内容");
    }
    assistant.status.textContent = "处理状态 · 已完成";
    renderMessageContent(assistant.content, assistantContent);
    state.messages.push({ role: "assistant", content: assistantContent });
  } catch (error) {
    const message = error.message || "发送失败";
    if (assistant) {
      assistant.status.textContent = "处理状态 · 运行失败";
      assistant.content.textContent = message;
      appendRetryButton(assistant.wrapper, content);
    } else {
      appendMessage("assistant", message);
    }
  } finally {
    state.streaming = false;
    els.sendButton.disabled = false;
    els.sendButton.textContent = "发送";
    await refreshThreadList();
    await loadRuns();
  }
}

function appendConfirmationActions(assistant, confirmation, sourceContent) {
  if (assistant.wrapper.querySelector(".confirmation-actions")) return;
  const actions = document.createElement("div");
  actions.className = "confirmation-actions";
  const approveButton = document.createElement("button");
  approveButton.type = "button";
  approveButton.textContent = "确认执行";
  const rejectButton = document.createElement("button");
  rejectButton.type = "button";
  rejectButton.className = "secondary";
  rejectButton.textContent = "取消";
  const setBusy = (busy) => {
    approveButton.disabled = busy;
    rejectButton.disabled = busy;
  };
  approveButton.addEventListener("click", async () => {
    setBusy(true);
    assistant.status.textContent = "处理状态 · 正在继续运行";
    try {
      const result = await api(`/api/runs/${confirmation.run_id}/confirmation`, {
        method: "POST",
        body: JSON.stringify({ approved: true }),
      });
      assistant.status.textContent = "处理状态 · 已完成";
      renderMessageContent(assistant.content, result.content || "");
      if (result.content) state.messages.push({ role: "assistant", content: result.content });
      actions.remove();
      if (result.artifact) appendArtifactLink(assistant.wrapper, result.artifact);
      await Promise.all([refreshThreadList(), loadRuns()]);
    } catch (error) {
      assistant.status.textContent = "处理状态 · 运行失败";
      assistant.content.textContent = error.message || "文件生成失败";
      setBusy(false);
    }
  });
  rejectButton.addEventListener("click", async () => {
    setBusy(true);
    try {
      await api(`/api/runs/${confirmation.run_id}/confirmation`, {
        method: "POST",
        body: JSON.stringify({ approved: false }),
      });
      assistant.status.textContent = "处理状态 · 已取消";
      assistant.content.textContent = "已取消本次文件生成，未创建任何文件。";
      actions.remove();
      await loadRuns();
    } catch (error) {
      assistant.status.textContent = "处理状态 · 取消失败";
      assistant.content.textContent = error.message || "取消失败";
      setBusy(false);
    }
  });
  actions.append(approveButton, rejectButton);
  assistant.wrapper.appendChild(actions);
}

function appendArtifactLink(wrapper, artifact) {
  const link = document.createElement("a");
  link.className = "artifact-link";
  link.href = "#";
  link.textContent = `下载文件：${artifact.filename}`;
  link.title = artifact.summary || "下载本次生成的文件";
  link.addEventListener("click", async (event) => {
    event.preventDefault();
    link.setAttribute("aria-busy", "true");
    const originalText = link.textContent;
    link.textContent = "正在下载文件...";
    try {
      const response = await fetch(`/api/artifacts/${artifact.id}/download`, {
        headers: { Authorization: `Bearer ${state.token}` },
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "文件下载失败");
      }
      const url = URL.createObjectURL(await response.blob());
      const download = document.createElement("a");
      download.href = url;
      download.download = artifact.filename;
      document.body.appendChild(download);
      download.click();
      download.remove();
      URL.revokeObjectURL(url);
      link.textContent = originalText;
    } catch (error) {
      link.textContent = error.message || "文件下载失败";
      window.setTimeout(() => { link.textContent = originalText; }, 2500);
    } finally {
      link.removeAttribute("aria-busy");
    }
  });
  wrapper.appendChild(link);
}

function appendRetryButton(wrapper, content) {
  if (wrapper.querySelector(".retry-button")) return;
  const retryButton = document.createElement("button");
  retryButton.className = "retry-button";
  retryButton.type = "button";
  retryButton.textContent = "重试";
  retryButton.addEventListener("click", () => sendMessage(content, { retry: true }));
  wrapper.appendChild(retryButton);
}

async function refreshThreadList() {
  try {
    await Promise.all([loadThreads(), loadFolders()]);
    renderThreads();
    const active = state.threads.find((thread) => thread.id === state.currentThreadId);
    if (active) els.threadTitle.textContent = active.title;
  } catch (error) {
    // The current response remains visible when the sidebar refresh fails.
  }
}

function parseSse(text) {
  const lines = text.split("\n");
  const eventLine = lines.find((line) => line.startsWith("event: "));
  const dataLine = lines.find((line) => line.startsWith("data: "));
  return {
    event: eventLine ? eventLine.slice(7) : "message",
    data: dataLine ? JSON.parse(dataLine.slice(6)) : {},
  };
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

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
  }
  els.knowledgeModeSelect.disabled = Boolean(override);
  els.webModeSelect.disabled = Boolean(override);
}

let routePreviewTimer;
let routePreviewSequence = 0;

function renderExecutionModeHint() {
  syncEvidenceModeControls();
  const labels = { off: "关闭", auto: "自动", required: "必须" };
  const sourceLabels = { general: "通用", local_only: "仅本地资料", web_only: "仅联网资料", mixed: "混合资料" };
  els.executionModeHint.textContent = `${sourceLabels[els.sourceModeSelect.value]} · 知识库${labels[els.knowledgeModeSelect.value]} · 网络${labels[els.webModeSelect.value]}`;
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

els.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  els.loginError.textContent = "";
  try {
    const data = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({
        email: els.emailInput.value,
        password: els.passwordInput.value,
      }),
    });
    state.token = data.token;
    state.user = data.user;
    localStorage.setItem("agent_platform_token", state.token);
    showWorkspace(false);
    try {
      await refreshAll();
      await restoreWorkspaceState();
      revealWorkspace();
    } catch (error) {
      showWorkspaceLoadError(error);
    }
  } catch (error) {
    els.loginError.textContent = error.message;
  }
});

els.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = getChatContent();
  if (!content) return;
  els.chatInput.innerHTML = "";
  try {
    await sendMessage(content);
  } catch (error) {
    appendMessage("assistant", error.message);
  }
});

[els.sourceModeSelect, els.knowledgeModeSelect, els.webModeSelect, els.fileModeSelect]
  .forEach((select) => select.addEventListener("change", scheduleRoutePreview));

renderExecutionModeHint();

els.chatInput.addEventListener("input", () => {
  scheduleRoutePreview();
});

els.chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Backspace" && removeSkillBeforeCaret()) {
    event.preventDefault();
    return;
  }
  if (event.key === "Enter" && event.shiftKey) {
    event.preventDefault();
    els.chatForm.requestSubmit();
  }
});

function removeSkillBeforeCaret() {
  const selection = window.getSelection();
  if (!selection.rangeCount || !selection.isCollapsed) return false;
  const range = selection.getRangeAt(0);
  const container = range.startContainer;
  const offset = range.startOffset;
  let previous = null;

  if (container === els.chatInput && offset > 0) {
    previous = els.chatInput.childNodes[offset - 1];
  } else if (container.nodeType === Node.TEXT_NODE && offset === 0) {
    previous = container.previousSibling;
  }
  if (previous?.nodeType === Node.TEXT_NODE && !previous.textContent) previous = previous.previousSibling;
  if (!(previous instanceof HTMLElement) || !previous.classList.contains("skill-tag")) return false;

  state.selectedSkillIds = state.selectedSkillIds.filter((skillId) => skillId !== previous.dataset.skillId);
  renderComposerSkills();
  renderSkillPicker();
  focusChatInput();
  return true;
}

els.newThreadButton.addEventListener("click", () => {
  state.currentThreadId = "";
  state.pendingFolderId = "";
  persistWorkspaceState();
  state.messages = [];
  state.selectedSkillIds = [];
  renderComposerSkills();
  renderSkillPicker();
  els.threadTitle.textContent = "新对话";
  switchView("chat");
  renderThreads();
  renderMessages();
  state.runs = [];
  state.threadContext = { sources: [], outputs: [] };
  renderThreadContext();
  els.runDetailsButton.disabled = true;
  els.runDrawer.classList.add("hidden");
});

els.threadSearch.addEventListener("input", renderThreads);

els.runDetailsButton.addEventListener("click", () => {
  els.runDrawer.classList.remove("hidden");
  els.runFilters.classList.add("hidden");
  renderRuns();
  if (state.runs[0]) loadRunDetail(state.runs[0].id);
});

els.closeRunDrawer.addEventListener("click", () => els.runDrawer.classList.add("hidden"));
els.viewAllRunsButton.addEventListener("click", async () => {
  els.runDrawer.classList.remove("hidden");
  els.runFilters.classList.remove("hidden");
  await loadAuditRuns();
});
[els.runStatusFilter, els.runTierFilter, els.runKnowledgeFilter].forEach((select) => {
  select.addEventListener("change", () => loadAuditRuns().catch((error) => { els.runDetail.textContent = error.message; }));
});

els.viewKnowledgeButton.addEventListener("click", () => switchView("knowledge"));
els.viewArtifactsButton.addEventListener("click", () => switchView("artifacts"));

els.skillPickerButton.addEventListener("click", () => {
  const isHidden = els.skillPickerMenu.classList.toggle("hidden");
  els.skillPickerButton.setAttribute("aria-expanded", String(!isHidden));
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".skill-picker-wrap")) {
    els.skillPickerMenu.classList.add("hidden");
    els.skillPickerButton.setAttribute("aria-expanded", "false");
  }
});

async function uploadSkillFile(file) {
  try {
    const lowerName = file.name.toLowerCase();
    let payload;
    const isZip = lowerName.endsWith(".zip") || /zip|compressed/i.test(file.type || "");
    const isMarkdown = lowerName.endsWith(".md") || /markdown/i.test(file.type || "");
    const isJson = lowerName.endsWith(".json") || /json/i.test(file.type || "");
    if (!isZip && !isMarkdown && !isJson) {
      throw new Error("请选择 JSON、Markdown 或 ZIP 格式的技能包");
    }
    if (isZip) {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
      payload = { bundle_base64: btoa(binary) };
    } else {
      const content = await file.text();
      payload = isMarkdown
        ? { markdown: content, filename: file.name }
        : { skill: JSON.parse(content) };
    }
    await api("/api/skills", { method: "POST", body: JSON.stringify(payload) });
    await loadSkills();
    return true;
  } catch (error) {
    window.alert(error.message);
    return false;
  }
}

function setSkillFileStatus(message, ready = false) {
  els.skillFileName.textContent = message;
  els.skillFileName.classList.toggle("ready", ready);
}

els.skillFileInput.addEventListener("change", async () => {
  const [file] = els.skillFileInput.files;
  if (file) {
    setSkillFileStatus(`正在导入：${file.name}`);
    const imported = await uploadSkillFile(file);
    setSkillFileStatus(imported ? `已导入：${file.name}` : `导入失败：${file.name}`, imported);
  }
  els.skillFileInput.value = "";
});

["dragenter", "dragover"].forEach((eventName) => {
  els.skillDropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    els.skillDropZone.classList.add("drag-active");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  els.skillDropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    els.skillDropZone.classList.remove("drag-active");
  });
});

els.skillDropZone.addEventListener("drop", async (event) => {
  const [file] = event.dataTransfer?.files || [];
  if (file) {
    setSkillFileStatus(`正在导入：${file.name}`);
    const imported = await uploadSkillFile(file);
    setSkillFileStatus(imported ? `已导入：${file.name}` : `导入失败：${file.name}`, imported);
  }
});

els.uploadKnowledgeButton.addEventListener("click", () => els.knowledgeFileInput.click());
els.knowledgeFileInput.addEventListener("change", async () => {
  const [file] = els.knowledgeFileInput.files;
  if (!file) return;
  if (file.size > 8 * 1024 * 1024) {
    window.alert("资料不能超过 8 MB");
    els.knowledgeFileInput.value = "";
    return;
  }
  try {
    const contentBase64 = await fileAsBase64(file);
    await api("/api/knowledge", {
      method: "POST",
      body: JSON.stringify({ filename: file.name, mime_type: file.type, content_base64: contentBase64 }),
    });
    await loadKnowledge();
  } catch (error) {
    window.alert(error.message);
  } finally {
    els.knowledgeFileInput.value = "";
  }
});

function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("读取资料失败"));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.readAsDataURL(file);
  });
}

let knowledgeSearchTimer;
els.knowledgeSearch.addEventListener("input", () => {
  window.clearTimeout(knowledgeSearchTimer);
  knowledgeSearchTimer = window.setTimeout(() => searchKnowledge(), 180);
});

let memorySearchTimer;
els.memorySearch.addEventListener("input", () => {
  window.clearTimeout(memorySearchTimer);
  memorySearchTimer = window.setTimeout(() => loadMemories().catch((error) => {
    els.memoryNotice.textContent = error.message;
  }), 180);
});

els.memoryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = els.memoryContent.value.trim();
  if (!content || !window.confirm(`确认将“${content}”保存为长期记忆？`)) return;
  const scopeValue = els.memoryScope.value;
  const projectScope = scopeValue.startsWith("project:");
  try {
    await api("/api/memories", {
      method: "POST",
      body: JSON.stringify({
        kind: els.memoryKind.value,
        content,
        scope_type: projectScope ? "project" : "global",
        scope_id: projectScope ? scopeValue.slice(8) : "",
        confirmed: true,
      }),
    });
    els.memoryContent.value = "";
    els.memoryNotice.textContent = "长期记忆已保存";
    await loadMemories();
  } catch (error) {
    els.memoryNotice.textContent = error.message;
  }
});

document.querySelectorAll(".nav-button[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    if (button === els.newThreadButton) return;
    switchView(button.dataset.view);
  });
});

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
    button.classList.add("active");
    const tab = button.dataset.tab;
    els.skillsGrid.classList.toggle("hidden", tab !== "skills");
    els.appsGrid.classList.toggle("hidden", tab !== "apps");
  });
});

els.settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  els.settingsNotice.textContent = "";
  const data = await api("/api/me", {
    method: "PATCH",
    body: JSON.stringify({ name: els.nameInput.value }),
  });
  state.user = data.user;
  els.settingsNotice.textContent = "已保存";
});

els.logoutButton.addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" }).catch(() => {});
  localStorage.removeItem("agent_platform_token");
  state.token = "";
  state.user = null;
  showLogin();
});

els.logoutAllButton.addEventListener("click", async () => {
  if (!window.confirm("将退出所有已登录设备，是否继续？")) return;
  await api("/api/logout-all", { method: "POST" });
  localStorage.removeItem("agent_platform_token");
  state.token = "";
  state.user = null;
  showLogin();
});

if (window.location.protocol === "file:") {
  showDirectOpenNotice();
} else {
  boot();
}
