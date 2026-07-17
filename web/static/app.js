const state = window.AgentState;
const UI_STATE_KEY = window.AgentUiState.key;
const VALID_VIEWS = window.AgentUiState.validViews;
const els = window.AgentElements;
const storage = window.AgentStorage;
const composer = window.AgentChatComposer;
const chatStream = window.AgentChatStream;
const markdown = window.AgentMarkdown;
const chatInteractions = window.AgentChatInteractions;
const runTrace = window.AgentRunTrace;
const knowledgeLibrary = window.AgentKnowledgeLibrary;
const spaceWorkspace = window.AgentSpaceWorkspace;
const resourceViews = window.AgentResourceViews;
const capabilityViews = window.AgentCapabilityViews;
const settingsView = window.AgentSettingsView;
const auditView = window.AgentAuditView;
const executionMode = window.AgentExecutionMode({ state, els, api: window.AgentApi, getChatContent });

const api = window.AgentApi;

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
      storage.clearToken();
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
  storage.saveWorkspace(UI_STATE_KEY, {
    view: state.activeView,
    threadId: state.currentThreadId,
  });
}

async function restoreWorkspaceState() {
  const saved = storage.loadWorkspace(UI_STATE_KEY);
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
  renderKnowledgeProjectOptions();
}

function renderKnowledgeProjectOptions() {
  knowledgeLibrary.renderProjectOptions(state, els, escapeHtml);
  syncKnowledgeScopeControls();
}

function syncKnowledgeScopeControls() {
  knowledgeLibrary.syncScope(els);
  renderKnowledge(state.knowledgeDocuments);
}

async function loadThread(threadId) {
  const data = await api(`/api/threads/${threadId}`);
  state.currentThreadId = data.thread.id;
  state.pendingFolderId = "";
  persistWorkspaceState();
  state.messages = data.messages;
  state.currentThreadEditable = data.thread.user_id === state.user?.id;
  els.threadTitle.textContent = data.thread.title || "新对话";
  if (!state.currentThreadEditable && data.thread.author_name) els.threadTitle.textContent += ` · ${data.thread.author_name}`;
  els.chatInput.contentEditable = String(state.currentThreadEditable);
  els.sendButton.disabled = !state.currentThreadEditable;
  els.chatInput.dataset.placeholder = state.currentThreadEditable ? "给 Agent_Platform 发送消息" : "此对话由其他项目成员创建，仅可查看";
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
  renderModelConfigHint();
}

function renderModelConfigHint() {
  executionMode.renderModelConfigHint();
}

function renderSkillContext() {
  state.selectedSkillIds = state.selectedSkillIds.filter((skillId) => state.skills.some((skill) => skill.id === skillId && skill.enabled));
  renderComposerSkills();
  renderSkillPicker();
}

function getPromptText() {
  return composer.getPromptText(els);
}

function getChatContent() {
  return composer.getChatContent(state, els);
}

function focusChatInput() {
  composer.focus(els);
}

function renderComposerSkills() {
  composer.renderSkills(state, els);
}

function renderSkillPicker() {
  composer.renderPicker(state, els, (skillId) => {
    toggleSelectedSkill(skillId);
    focusChatInput();
  });
}

function toggleSelectedSkill(skillId) {
  composer.toggleSkill(state, skillId);
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
  resourceViews.renderMemories(state, els, escapeHtml, {
    onUpdate: async (memory, update) => {
      if (update.prompt) {
        const content = window.prompt("修改长期记忆", memory.content)?.trim();
        if (!content || content === memory.content) return;
        update = { content };
      }
      await api(`/api/memories/${memory.id}`, { method: "PATCH", body: JSON.stringify(update) });
      await loadMemories();
    },
    onDelete: async (memory) => { if (window.confirm("删除这条长期记忆？删除后不会再用于任何对话。")) { await api(`/api/memories/${memory.id}`, { method: "DELETE" }); await loadMemories(); } },
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
  resourceViews.renderArtifacts(state, els, escapeHtml, { onDownload: downloadArtifact, onDelete: deleteArtifact });
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
  state.knowledgeDocuments = documents;
  knowledgeLibrary.renderDocuments(state, els, escapeHtml, {
    onEdit: editKnowledge,
    onDelete: async (document) => {
      if (!window.confirm(`删除资料“${document.filename}”？`)) return;
      await api(`/api/knowledge/${document.id}`, { method: "DELETE" });
      await refreshKnowledgeViews();
      await searchKnowledge();
    },
  });
}

async function refreshKnowledgeViews() {
  await loadKnowledge();
  if (state.activeView === "space" && state.currentSpaceId) await openSpace(state.currentSpaceId);
}

async function editKnowledge(document) {
  const filename = window.prompt("资料名称", document.filename);
  if (!filename?.trim()) return;
  const scope = window.prompt("输入 general（通用知识库）或 project（项目专属）", document.scope || "general");
  if (!scope || !["general", "project"].includes(scope)) return window.alert("请输入 general 或 project");
  let projectSpaceId = "";
  if (scope === "project") {
    const spaces = state.folders.filter((folder) => folder.section === "project");
    const options = spaces.map((space) => `${space.name} (${space.id})`).join("\n");
    const selected = window.prompt(`输入目标项目空间 ID：\n${options}`, document.project_space_id || "");
    if (!selected?.trim()) return;
    projectSpaceId = selected.trim();
  }
  try {
    await api(`/api/knowledge/${document.id}`, { method: "PATCH", body: JSON.stringify({ filename, scope, project_space_id: projectSpaceId }) });
    await refreshKnowledgeViews();
  } catch (error) {
    window.alert(error.message);
  }
}

async function searchKnowledge() {
  const query = els.knowledgeSearch.value.trim();
  if (!query) {
    els.knowledgeResults.classList.add("hidden");
    els.knowledgeResults.innerHTML = "";
    return;
  }
  const data = await api(`/api/knowledge/search?query=${encodeURIComponent(query)}`);
  knowledgeLibrary.renderSearchResults(els, data.results, escapeHtml);
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
    controls.append(newThread);
    if (folder.user_id === state.user?.id) controls.append(menu);
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
    if (thread.user_id === state.user?.id) row.append(button, menu);
    else {
      const author = document.createElement("span");
      author.className = "thread-author";
      author.textContent = thread.author_name || "成员";
      author.title = `创建者：${thread.author_name || "成员"}`;
      row.append(button, author);
    }
    return row;
}

async function openSpace(spaceId) {
  state.currentSpaceId = spaceId;
  const data = await api(`/api/folders/${spaceId}`);
  els.spaceTitle.textContent = data.space.name;
  spaceWorkspace.render({ data, state, spaceId, userId: state.user?.id, escape: escapeHtml, detail: els.spaceDetail });
  mountSpaceComposer(data.space);
  els.spaceDetail.querySelectorAll(".space-task-link").forEach((button) => button.addEventListener("click", () => { switchView("chat"); loadThread(button.dataset.threadId); }));
  els.spaceDetail.querySelectorAll(".space-artifact-link").forEach((button) => button.addEventListener("click", () => downloadArtifact({ id: button.dataset.artifactId })));
  els.spaceDetail.querySelectorAll(".remove-space-member").forEach((button) => button.addEventListener("click", async () => {
    if (!window.confirm("移除该成员？")) return;
    if (button.dataset.demo === "true") state.demoMembersBySpace[spaceId] = state.demoMembersBySpace[spaceId].filter((member) => member.id !== button.dataset.memberId);
    else await api(`/api/folders/${spaceId}/members/${button.dataset.memberId}`, { method: "DELETE" });
    await openSpace(spaceId);
  }));
  els.spaceDetail.querySelector("#inviteSpaceMember")?.addEventListener("click", async () => {
    const email = window.prompt("输入成员邮箱");
    if (!email?.trim()) return;
    await api(`/api/folders/${spaceId}/invitations`, { method: "POST", body: JSON.stringify({ email }) });
    await openSpace(spaceId);
  });
  els.spaceDetail.querySelector("#uploadSpaceKnowledge")?.addEventListener("click", () => {
    state.knowledgeUploadSpaceId = spaceId;
    els.knowledgeFileInput.click();
  });
  els.spaceDetail.querySelector("#spaceKnowledgeSearch")?.addEventListener("input", (event) => {
    const query = event.target.value.trim().toLowerCase();
    els.spaceDetail.querySelectorAll(".space-knowledge-item").forEach((item) => { item.hidden = Boolean(query && !item.textContent.toLowerCase().includes(query)); });
  });
  els.spaceDetail.querySelectorAll(".space-knowledge-delete").forEach((button) => button.addEventListener("click", async () => {
    if (!window.confirm("删除该项目资料？资料会同步从知识库移除。")) return;
    await api(`/api/knowledge/${button.closest(".space-knowledge-item").dataset.knowledgeId}`, { method: "DELETE" });
    await loadKnowledge();
    await openSpace(spaceId);
  }));
  els.spaceDetail.querySelectorAll(".space-knowledge-edit").forEach((button) => button.addEventListener("click", () => {
    const document = (data.knowledge_documents || []).find((item) => item.id === button.closest(".space-knowledge-item").dataset.knowledgeId);
    if (document) editKnowledge({ ...document, scope: "project", project_space_id: spaceId });
  }));
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

async function startThreadInFolder(folder, { preserveComposer = false } = {}) {
  state.pendingFolderId = folder.id;
  state.currentThreadId = "";
  state.messages = [];
  state.runs = [];
  state.threadContext = { sources: [], outputs: [] };
  if (!preserveComposer) state.selectedSkillIds = [];
  state.currentThreadEditable = true;
  els.chatInput.contentEditable = "true";
  els.chatInput.dataset.placeholder = "给 Agent_Platform 发送消息";
  els.sendButton.disabled = false;
  if (!preserveComposer) {
    renderComposerSkills();
    renderSkillPicker();
  }
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
  appendExecutionTrace(assistant, "等待你的确认");
  assistant.content.textContent = detail.confirmation.request;
  const context = safeJson(detail.run.execution_context, {});
  appendConfirmationActions(assistant, {
    run_id: pending.id,
    request: detail.confirmation.request,
    kind: context.artifact_request?.kind || "",
  }, "");
}

function renderRuns() {
  auditView.renderRunList(state, els, loadRunDetail);
}

async function loadRunDetail(runId) {
  const data = await api(`/api/runs/${runId}`);
  auditView.renderDetail(els, data, {
    onDownload: async (artifact, link) => {
      link.disabled = true;
      try { await downloadArtifact(artifact); } finally { link.disabled = false; }
    },
    onFeedback: async (id, citationCorrect, feedback, button) => {
      button.disabled = true;
      try {
        await api(`/api/runs/${id}/feedback`, { method: "POST", body: JSON.stringify({ rating: citationCorrect ? 1 : -1, citation_correct: citationCorrect }) });
        feedback.replaceChildren(Object.assign(document.createElement("span"), { textContent: "已记录引用评价" }));
      } catch (error) { button.disabled = false; button.textContent = error.message || "提交失败"; }
    },
    onCancel: async (id, button) => {
      button.disabled = true;
      try { await api(`/api/runs/${id}/cancel`, { method: "POST", body: "{}" }); await loadRuns(); await loadRunDetail(id); }
      catch (error) { button.disabled = false; button.textContent = error.message || "取消失败"; }
    },
  });
  return;
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
  return window.AgentMarkdown.render(markdown);
}

function renderInline(element, text) {
  return markdown.renderInline(element, text);
}

function appendAssistantMessage() {
  return runTrace.appendAssistantMessage(els);
}

function renderReasoningSummary(assistant, items) {
  runTrace.renderReasoningSummary(assistant, items);
}

function appendExecutionTrace(assistant, summary) {
  runTrace.appendExecutionTrace(els, assistant, summary);
}

function startExecutionCountdown(assistant) {
  return runTrace.startCountdown(assistant);
}

function renderSkills(skills) {
  capabilityViews.renderSkills(els, skills, escapeHtml, {
    onToggle: async (skill, enabled) => { await api(`/api/skills/${skill.id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }); skill.enabled = enabled; renderSkillContext(); },
    onEdit: editSkill, onVersion: restoreSkillVersion, onDelete: deleteSkill,
  });
}

function skillSummary(skill) {
  return capabilityViews.skillSummary(skill);
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
  capabilityViews.renderApps(els, apps, tools, escapeHtml, {
    onExecute: async (tool, args) => (await api(`/api/tools/${tool.id}/execute`, { method: "POST", body: JSON.stringify({ arguments: args }) })).result,
  });
}

function switchView(view) {
  if (view !== "space") restoreChatComposer();
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

function restoreChatComposer() {
  if (els.chatForm.parentElement === els.chatPage) return;
  els.messages.insertAdjacentElement("afterend", els.chatForm);
  els.chatForm.classList.remove("space-composer");
  els.chatInput.dataset.placeholder = "给 Agent_Platform 发送消息";
  state.spaceComposerFolder = null;
}

function mountSpaceComposer(space) {
  const mount = els.spaceDetail.querySelector("#spaceComposerMount");
  if (!mount) return;
  state.spaceComposerFolder = space;
  els.chatForm.classList.add("space-composer");
  els.chatInput.dataset.placeholder = "给项目空间发送消息";
  mount.appendChild(els.chatForm);
}

async function sendMessage(content, { retry = false } = {}) {
  if (state.streaming) return;
  state.streaming = true;
  els.sendButton.disabled = true;
  els.sendButton.textContent = "发送中";

  let assistant;
  let executionTimer;
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
    executionTimer = startExecutionCountdown(assistant);

    const chatPayload = chatStream.buildPayload(state, els, content, retry);
    const response = await chatStream.open(state, chatPayload);
    await chatStream.consume(response, (event) => {
        if (event.event === "meta") {
          state.currentThreadId = event.data.thread_id;
          state.pendingFolderId = "";
          persistWorkspaceState();
          appendExecutionTrace(assistant, `已选择模型：${event.data.model}`);
        }
        if (event.event === "reasoning_summary") {
          renderReasoningSummary(assistant, event.data.items);
        }
        if (event.event === "status") {
          appendExecutionTrace(assistant, event.data.summary || "正在执行");
        }
        if (event.event === "delta") {
          assistantContent += event.data.content;
          assistant.content.textContent = assistantContent;
          els.messages.scrollTop = els.messages.scrollHeight;
        }
        if (event.event === "confirmation") {
          awaitingConfirmation = true;
          appendExecutionTrace(assistant, "等待你的确认");
          executionTimer.stop("等待确认");
          assistant.content.textContent = event.data.request || "此操作需要确认后才能执行。";
          appendConfirmationActions(assistant, event.data, content);
        }
        if (event.event === "cancelled") {
          cancelled = true;
          appendExecutionTrace(assistant, "运行已取消");
          executionTimer.stop("已取消");
          assistant.content.textContent = "本次运行已取消，未保存后续回答。";
        }
        if (event.event === "error") {
          throw new Error(event.data.error || "运行失败");
        }
    });
    if (cancelled || awaitingConfirmation) return;
    if (!assistantContent && !awaitingConfirmation) {
      throw new Error("模型未返回内容");
    }
    appendExecutionTrace(assistant, "已生成最终回答");
    executionTimer.stop("已完成");
    renderMessageContent(assistant.content, assistantContent);
    state.messages.push({ role: "assistant", content: assistantContent });
  } catch (error) {
    const message = error.message || "发送失败";
    if (assistant) {
      appendExecutionTrace(assistant, "运行失败");
      executionTimer?.stop("运行失败");
      assistant.content.textContent = message;
      appendRetryButton(assistant.wrapper, content);
    } else {
      appendMessage("assistant", message);
    }
  } finally {
    if (cancelled) executionTimer?.stop("已取消");
    state.streaming = false;
    els.sendButton.disabled = false;
    els.sendButton.textContent = "发送";
    await refreshThreadList();
    await loadRuns();
  }
}

function appendConfirmationActions(assistant, confirmation, sourceContent) {
  chatInteractions.appendConfirmationActions({
    assistant, confirmation, api, state,
    appendTrace: appendExecutionTrace,
    renderContent: renderMessageContent,
    appendArtifact: appendArtifactLink,
    refreshThreads: refreshThreadList,
    loadRuns,
  });
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
  chatInteractions.appendRetryButton(wrapper, content, (retryContent) => sendMessage(retryContent, { retry: true }));
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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderExecutionModeHint() {
  executionMode.renderExecutionModeHint();
}

function scheduleRoutePreview() {
  executionMode.scheduleRoutePreview();
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
    storage.setToken(state.token);
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
  const space = state.activeView === "space" ? state.spaceComposerFolder : null;
  els.chatInput.innerHTML = "";
  try {
    if (space) {
      await startThreadInFolder(space, { preserveComposer: true });
    }
    await sendMessage(content);
  } catch (error) {
    appendMessage("assistant", error.message);
  }
});

[els.sourceModeSelect, els.knowledgeModeSelect, els.webModeSelect, els.fileModeSelect]
  .forEach((select) => select.addEventListener("change", scheduleRoutePreview));

[els.modelSelect, els.taskModeSelect].forEach((select) => select.addEventListener("change", () => {
  renderModelConfigHint();
  scheduleRoutePreview();
}));

const modelConfigPicker = document.querySelector(".model-config-picker");
const executionModePicker = document.querySelector(".execution-mode-picker");
[modelConfigPicker, executionModePicker].forEach((picker) => picker?.addEventListener("toggle", () => {
  if (!picker.open) return;
  [modelConfigPicker, executionModePicker].filter((other) => other && other !== picker).forEach((other) => { other.open = false; });
}));

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
  if (!composer.removeSkillBeforeCaret(state, els)) return false;
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

els.uploadKnowledgeButton.addEventListener("click", () => {
  state.knowledgeUploadSpaceId = "";
  els.knowledgeFileInput.click();
});
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
    const projectSpaceId = state.knowledgeUploadSpaceId || (els.knowledgeScopeSelect.value === "project" ? els.knowledgeProjectSelect.value : "");
    if (els.knowledgeScopeSelect.value === "project" && !projectSpaceId) throw new Error("请先选择项目空间");
    await api(state.knowledgeUploadSpaceId ? `/api/folders/${state.knowledgeUploadSpaceId}/knowledge` : "/api/knowledge", {
      method: "POST",
      body: JSON.stringify({ filename: file.name, mime_type: file.type, content_base64: contentBase64, scope: projectSpaceId ? "project" : "general", project_space_id: projectSpaceId }),
    });
    await loadKnowledge();
    if (state.knowledgeUploadSpaceId) await openSpace(state.knowledgeUploadSpaceId);
  } catch (error) {
    window.alert(error.message);
  } finally {
    els.knowledgeFileInput.value = "";
    state.knowledgeUploadSpaceId = "";
  }
});

els.knowledgeScopeSelect.addEventListener("change", syncKnowledgeScopeControls);
els.knowledgeProjectSelect.addEventListener("change", () => renderKnowledge(state.knowledgeDocuments));

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
  const data = await settingsView.save(api, els.nameInput.value);
  state.user = data.user;
  els.settingsNotice.textContent = "已保存";
});

els.logoutButton.addEventListener("click", async () => {
  await settingsView.logout(api);
  storage.clearToken();
  state.token = "";
  state.user = null;
  showLogin();
});

els.logoutAllButton.addEventListener("click", async () => {
  if (!window.confirm("将退出所有已登录设备，是否继续？")) return;
  await settingsView.logout(api, true);
  storage.clearToken();
  state.token = "";
  state.user = null;
  showLogin();
});

if (window.location.protocol === "file:") {
  showDirectOpenNotice();
} else {
  boot();
}
