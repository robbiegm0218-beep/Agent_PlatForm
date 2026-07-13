const state = {
  token: localStorage.getItem("agent_platform_token") || "",
  user: null,
  threads: [],
  folders: [],
  collapsedFolderIds: new Set(),
  currentThreadId: "",
  messages: [],
  runs: [],
  skills: [],
  models: [],
  knowledgeDocuments: [],
  selectedSkillIds: [],
  activeView: "chat",
  streaming: false,
};

const els = {
  loginView: document.querySelector("#loginView"),
  workspaceView: document.querySelector("#workspaceView"),
  loginForm: document.querySelector("#loginForm"),
  loginError: document.querySelector("#loginError"),
  emailInput: document.querySelector("#emailInput"),
  passwordInput: document.querySelector("#passwordInput"),
  threadList: document.querySelector("#threadList"),
  threadSearch: document.querySelector("#threadSearch"),
  newFolderButton: document.querySelector("#newFolderButton"),
  newThreadButton: document.querySelector("#newThreadButton"),
  chatPage: document.querySelector("#chatPage"),
  skillsPage: document.querySelector("#skillsPage"),
  settingsPage: document.querySelector("#settingsPage"),
  knowledgePage: document.querySelector("#knowledgePage"),
  messages: document.querySelector("#messages"),
  threadTitle: document.querySelector("#threadTitle"),
  modelStatus: document.querySelector("#modelStatus"),
  runDetailsButton: document.querySelector("#runDetailsButton"),
  runDrawer: document.querySelector("#runDrawer"),
  closeRunDrawer: document.querySelector("#closeRunDrawer"),
  runList: document.querySelector("#runList"),
  runDetail: document.querySelector("#runDetail"),
  chatForm: document.querySelector("#chatForm"),
  chatInput: document.querySelector("#chatInput"),
  taskModeSelect: document.querySelector("#taskModeSelect"),
  modelSelect: document.querySelector("#modelSelect"),
  skillPickerButton: document.querySelector("#skillPickerButton"),
  skillPickerMenu: document.querySelector("#skillPickerMenu"),
  sendButton: document.querySelector("#sendButton"),
  skillsGrid: document.querySelector("#skillsGrid"),
  appsGrid: document.querySelector("#appsGrid"),
  uploadSkillButton: document.querySelector("#uploadSkillButton"),
  skillFileInput: document.querySelector("#skillFileInput"),
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
    showWorkspace();
    try {
      await refreshAll();
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
  els.loginView.classList.remove("hidden");
  els.workspaceView.classList.add("hidden");
}

function showDirectOpenNotice() {
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

function showWorkspace() {
  els.loginView.classList.add("hidden");
  els.workspaceView.classList.remove("hidden");
  els.nameInput.value = state.user?.name || "";
  els.settingsEmail.value = state.user?.email || "";
}

async function refreshAll() {
  await Promise.all([loadThreads(), loadFolders(), loadSkills(), loadApps(), loadModels(), loadKnowledge()]);
  renderThreads();
  renderMessages();
}

async function loadThreads() {
  const data = await api("/api/threads");
  state.threads = data.threads;
}

async function loadFolders() {
  const data = await api("/api/folders");
  state.folders = data.folders;
}

async function loadThread(threadId) {
  const data = await api(`/api/threads/${threadId}`);
  state.currentThreadId = data.thread.id;
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
  renderApps([...apps.apps, ...tools.tools.map((tool) => ({
    name: tool.name,
    description: tool.description,
    status: tool.enabled ? "本地可用" : "未启用",
  }))]);
}

async function loadKnowledge() {
  const data = await api("/api/knowledge");
  state.knowledgeDocuments = data.documents;
  renderKnowledge(data.documents);
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

  if (ungrouped.length || !state.folders.length) renderThreadGroup("未归类", ungrouped);
  state.folders.forEach((folder) => renderThreadGroup(folder.name, grouped.get(folder.id) || [], folder));
}

function renderThreadGroup(title, threads, folder = null) {
  const group = document.createElement("section");
  group.className = `thread-group ${folder ? "thread-folder-group" : "thread-ungrouped-group"}`;
  const collapsed = folder && state.collapsedFolderIds.has(folder.id);
  group.classList.toggle("collapsed", Boolean(collapsed));
  const header = document.createElement("div");
  header.className = "thread-group-header";
  const heading = document.createElement(folder ? "button" : "div");
  heading.className = "thread-group-title";
  if (folder) {
    heading.type = "button";
    heading.classList.add("folder-toggle");
    heading.setAttribute("aria-expanded", String(!collapsed));
    heading.title = collapsed ? `展开文件夹：${folder.name}` : `收起文件夹：${folder.name}`;
    heading.addEventListener("click", () => {
      if (state.collapsedFolderIds.has(folder.id)) state.collapsedFolderIds.delete(folder.id);
      else state.collapsedFolderIds.add(folder.id);
      renderThreads();
    });
    const disclosure = document.createElement("span");
    disclosure.className = "folder-disclosure";
    disclosure.textContent = "›";
    heading.appendChild(disclosure);
    const icon = document.createElement("span");
    icon.className = "folder-icon";
    icon.setAttribute("aria-hidden", "true");
    heading.appendChild(icon);
  }
  const label = document.createElement("span");
  label.className = folder ? "folder-name" : "ungrouped-label";
  label.textContent = title;
  heading.appendChild(label);
  header.appendChild(heading);
  if (folder) {
    const menu = document.createElement("button");
    menu.className = "folder-menu";
    menu.type = "button";
    menu.textContent = "⋯";
    menu.title = `管理文件夹：${folder.name}`;
    menu.setAttribute("aria-label", `管理文件夹：${folder.name}`);
    menu.addEventListener("click", () => manageFolder(folder));
    header.appendChild(menu);
  }
  group.appendChild(header);
  threads.forEach((thread) => {
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
    group.appendChild(row);
  });
  els.threadList.appendChild(group);
}

async function manageThread(thread) {
  const action = window.prompt("输入 r 重命名，输入 m 移动到文件夹，输入 d 删除", "r");
  if (action === "r") {
    const title = window.prompt("输入新的对话名称", thread.title);
    if (!title?.trim()) return;
    await api(`/api/threads/${thread.id}`, { method: "PATCH", body: JSON.stringify({ title }) });
    await refreshThreadList();
    if (thread.id === state.currentThreadId) els.threadTitle.textContent = title.trim();
  }
  if (action === "m") {
    const choices = ["0. 未归类", ...state.folders.map((folder, index) => `${index + 1}. ${folder.name}`)];
    const selected = window.prompt(`输入目标序号：\n${choices.join("\n")}`, "0");
    if (selected === null) return;
    const index = Number.parseInt(selected, 10);
    if (!Number.isInteger(index) || index < 0 || index > state.folders.length) {
      window.alert("请输入有效的文件夹序号。");
      return;
    }
    const folderId = index === 0 ? "" : state.folders[index - 1].id;
    await api(`/api/threads/${thread.id}`, { method: "PATCH", body: JSON.stringify({ folder_id: folderId }) });
    await refreshThreadList();
  }
  if (action === "d" && window.confirm(`删除“${thread.title}”？此操作不可恢复。`)) {
    await api(`/api/threads/${thread.id}`, { method: "DELETE" });
    if (thread.id === state.currentThreadId) {
      state.currentThreadId = "";
      state.messages = [];
      renderMessages();
    }
    await refreshThreadList();
  }
}

async function createFolder() {
  const name = window.prompt("输入文件夹名称");
  if (!name?.trim()) return;
  try {
    await api("/api/folders", { method: "POST", body: JSON.stringify({ name }) });
    await refreshThreadList();
  } catch (error) {
    window.alert(`创建文件夹失败：${error.message}`);
  }
}

async function manageFolder(folder) {
  const action = window.prompt("输入 r 重命名，输入 d 删除文件夹", "r");
  if (action === "r") {
    const name = window.prompt("输入新的文件夹名称", folder.name);
    if (!name?.trim()) return;
    await api(`/api/folders/${folder.id}`, { method: "PATCH", body: JSON.stringify({ name }) });
    await refreshThreadList();
  }
  if (action === "d" && window.confirm(`删除文件夹“${folder.name}”？其中的对话会保留在“未归类”。`)) {
    await api(`/api/folders/${folder.id}`, { method: "DELETE" });
    await refreshThreadList();
  }
}

async function loadRuns() {
  state.runs = [];
  els.runDetailsButton.disabled = !state.currentThreadId;
  if (!state.currentThreadId) return;
  const data = await api(`/api/threads/${state.currentThreadId}/runs`);
  state.runs = data.runs;
  renderRuns();
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
    button.textContent = `${run.status === "completed" ? "已完成" : run.status === "failed" ? "失败" : "运行中"} · ${run.model}`;
    button.addEventListener("click", () => loadRunDetail(run.id));
    els.runList.appendChild(button);
  });
  if (!state.runs.length) els.runDetail.textContent = "当前对话还没有运行记录。";
}

async function loadRunDetail(runId) {
  const data = await api(`/api/runs/${runId}`);
  const { run, events, steps } = data;
  const elapsed = run.completed_at ? `${Math.max(0, Math.round((run.completed_at - run.started_at) / 1e9 * 10) / 10)} 秒` : "运行中";
  const skills = JSON.parse(run.skill_snapshot || "[]").map((skill) => skill.name).join("、") || "无";
  const plan = steps?.length ? steps : safeJson(run.plan_snapshot, []);
  const context = safeJson(run.execution_context, {});
  const reflection = safeJson(run.reflection_snapshot, {});
  const toolEvents = events.filter((event) => ["tool_call", "tool_result", "tool_error"].includes(event.type));
  const planText = plan.length ? plan.map((step) => `${step.title}（${step.status}）`).join(" → ") : "无";
  const tools = context.tools?.map((tool) => tool.name).join("、") || "无";
  const route = context.model_route_reason || "未记录";
  const tier = context.task_tier || "standard";
  const toolTrace = toolEvents.length ? toolEvents.map((event) => event.type).join(" → ") : "未调用工具";
  const reflectionText = reflection.applied
    ? `${reflection.summary || "已完成"}${reflection.revision_count ? `，已修订 ${reflection.revision_count} 次` : ""}`
    : "未触发";
  els.runDetail.textContent = `模型：${run.model}\n任务档位：${tier}\n路由：${route}\n输出预算：${context.max_output_tokens || "未记录"}\n状态：${run.status}\n耗时：${elapsed}\n技能：${skills}\n计划：${planText}\n允许工具：${tools}\n工具执行：${toolTrace}\n质量检查：${reflectionText}${run.error ? `\n错误：${run.error}` : ""}`;
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
    const filename = sourceLabel.replace(/（片段\s*\d+）$/, "");
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
      <p>${escapeHtml(skill.prompt || skill.description)}</p>
      <div class="card-footer">
        <span class="status-pill">${skill.enabled ? "已启用" : "未启用"}</span>
        <label class="switch" title="启用或禁用技能">
          <input type="checkbox" ${skill.enabled ? "checked" : ""} />
          <span></span>
        </label>
        <button class="skill-action" type="button" title="编辑技能">编辑</button>
        <button class="skill-action danger" type="button" title="删除技能">删除</button>
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
    const [editButton, deleteButton] = card.querySelectorAll(".skill-action");
    editButton.addEventListener("click", () => editSkill(skill));
    deleteButton.addEventListener("click", () => deleteSkill(skill));
    els.skillsGrid.appendChild(card);
  });
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

function renderApps(apps) {
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
}

function switchView(view) {
  state.activeView = view;
  els.chatPage.classList.toggle("hidden", view !== "chat");
  els.skillsPage.classList.toggle("hidden", view !== "skills");
  els.settingsPage.classList.toggle("hidden", view !== "settings");
  els.knowledgePage.classList.toggle("hidden", view !== "knowledge");
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
    };
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
        if (event.event === "error") {
          throw new Error(event.data.error || "运行失败");
        }
      }
    }
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
    showWorkspace();
    try {
      await refreshAll();
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

els.chatInput.addEventListener("input", () => {
  // The contenteditable surface grows within its bounded height.
});

els.chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Backspace" && removeSkillBeforeCaret()) {
    event.preventDefault();
    return;
  }
  if (event.key === "Enter" && !event.shiftKey) {
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
  state.messages = [];
  state.selectedSkillIds = [];
  renderComposerSkills();
  renderSkillPicker();
  els.threadTitle.textContent = "新对话";
  switchView("chat");
  renderThreads();
  renderMessages();
  state.runs = [];
  els.runDetailsButton.disabled = true;
  els.runDrawer.classList.add("hidden");
});

els.threadSearch.addEventListener("input", renderThreads);
els.newFolderButton.addEventListener("click", createFolder);

els.runDetailsButton.addEventListener("click", () => {
  els.runDrawer.classList.remove("hidden");
  renderRuns();
  if (state.runs[0]) loadRunDetail(state.runs[0].id);
});

els.closeRunDrawer.addEventListener("click", () => els.runDrawer.classList.add("hidden"));

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

els.uploadSkillButton.addEventListener("click", () => els.skillFileInput.click());
els.skillFileInput.addEventListener("change", async () => {
  const [file] = els.skillFileInput.files;
  if (!file) return;
  try {
    const content = await file.text();
    const payload = file.name.toLowerCase().endsWith(".md")
      ? { markdown: content, filename: file.name }
      : { skill: JSON.parse(content) };
    await api("/api/skills", { method: "POST", body: JSON.stringify(payload) });
    await loadSkills();
  } catch (error) {
    window.alert(error.message);
  } finally {
    els.skillFileInput.value = "";
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
