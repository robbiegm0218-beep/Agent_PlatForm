import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const storage = new Map();
const localStorage = {
  getItem(key) { return storage.has(key) ? storage.get(key) : null; },
  setItem(key, value) { storage.set(key, String(value)); },
  removeItem(key) { storage.delete(key); },
};
const elements = new Map();
const context = vm.createContext({
  window: {},
  CSSStyleSheet: class {
    replaceSync(content) { this.content = content; }
  },
  DOMParser: class {
    parseFromString() {
      return {
        body: { childNodes: [{ nodeName: "MAIN" }] },
        querySelector: () => null,
        querySelectorAll: () => [],
      };
    }
  },
  localStorage,
  document: {
    createDocumentFragment: () => ({ children: [], appendChild(node) { this.children.push(node); } }),
    importNode: (node) => node,
    querySelector: (selector) => {
      if (!elements.has(selector)) elements.set(selector, { selector });
      return elements.get(selector);
    },
  },
  TextDecoder,
  TextEncoder,
  fetch: async () => ({ ok: true, json: async () => ({ ok: true }) }),
});
context.window = context;

vm.runInContext(readFileSync(new URL("../web/static/core/storage.js", import.meta.url), "utf8"), context);
assert.equal(context.AgentStorage.getToken(), "");
context.AgentStorage.setToken("token-1");
for (const file of ["state.js", "dom.js", "api.js"]) {
  vm.runInContext(readFileSync(new URL(`../web/static/core/${file}`, import.meta.url), "utf8"), context);
}
vm.runInContext(readFileSync(new URL("../web/static/views/knowledge-configuration.js", import.meta.url), "utf8"), context);

assert.equal(context.AgentState.token, "token-1");
context.AgentStorage.saveWorkspace("workspace", { view: "knowledge" });
assert.equal(context.AgentStorage.loadWorkspace("workspace").view, "knowledge");
assert.equal(context.AgentElements.modelStatus.selector, "#modelStatus");
assert.ok(context.AgentUiState.validViews.has("knowledge-configuration"));
assert.deepEqual(
  Array.from(context.AgentKnowledgeConfigurationView.visibleTabs({ capabilities: [] }), (tab) => tab.id),
  ["overview", "index"],
);
assert.deepEqual(
  Array.from(context.AgentKnowledgeConfigurationView.visibleTabs({ capabilities: [{ capability_id: "retrieval_policy" }] }), (tab) => tab.id),
  ["overview", "retrieval", "index"],
);

let request;
context.fetch = async (path, options) => {
  request = { path, options };
  return { ok: true, json: async () => ({ ok: true }) };
};
await context.AgentApi("/api/me", { method: "GET" });
assert.equal(request.options.headers.Authorization, "Bearer token-1");

context.fetch = async () => ({ ok: false, status: 401, json: async () => ({ error: "未授权" }) });
await assert.rejects(() => context.AgentApi("/api/me"), (error) => error.status === 401 && error.message === "未授权");
context.fetch = async () => { throw new TypeError("Failed to fetch"); };
await assert.rejects(
  () => context.AgentApi("/api/health"),
  (error) => error.message === "无法连接本地服务，请确认服务已启动后重试。",
);

const app = readFileSync(new URL("../web/static/app.js", import.meta.url), "utf8");
const loginPage = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
const composer = readFileSync(new URL("../web/static/chat/composer.js", import.meta.url), "utf8");
const stream = readFileSync(new URL("../web/static/chat/stream.js", import.meta.url), "utf8");
const executionMode = readFileSync(new URL("../web/static/chat/execution-mode.js", import.meta.url), "utf8");
const markdown = readFileSync(new URL("../web/static/chat/markdown.js", import.meta.url), "utf8");
const interactions = readFileSync(new URL("../web/static/chat/interactions.js", import.meta.url), "utf8");
const runTrace = readFileSync(new URL("../web/static/chat/run-trace.js", import.meta.url), "utf8");
const artifactPreview = readFileSync(new URL("../web/static/chat/artifact-preview.js", import.meta.url), "utf8");
const knowledgeLibrary = readFileSync(new URL("../web/static/knowledge/library.js", import.meta.url), "utf8");
const spaceWorkspace = readFileSync(new URL("../web/static/space/workspace.js", import.meta.url), "utf8");
const resourceViews = readFileSync(new URL("../web/static/views/resources.js", import.meta.url), "utf8");
const capabilityViews = readFileSync(new URL("../web/static/views/capabilities.js", import.meta.url), "utf8");
const settingsView = readFileSync(new URL("../web/static/views/settings.js", import.meta.url), "utf8");
const knowledgeConfigurationView = readFileSync(new URL("../web/static/views/knowledge-configuration.js", import.meta.url), "utf8");
const auditView = readFileSync(new URL("../web/static/views/audit.js", import.meta.url), "utf8");
const tokenStyles = readFileSync(new URL("../web/static/styles/tokens-base.css", import.meta.url), "utf8");
const responsiveStyles = readFileSync(new URL("../web/static/styles/responsive.css", import.meta.url), "utf8");
const layoutStyles = readFileSync(new URL("../web/static/styles/layout.css", import.meta.url), "utf8");
const knowledgeStyles = readFileSync(new URL("../web/static/styles/knowledge.css", import.meta.url), "utf8");
const componentStyles = readFileSync(new URL("../web/static/styles/components.css", import.meta.url), "utf8");
const styleEntry = readFileSync(new URL("../web/static/styles.css", import.meta.url), "utf8");
assert.match(app, /storage\.saveWorkspace\(UI_STATE_KEY/);
assert.match(app, /storage\.loadWorkspace\(UI_STATE_KEY\)/);
assert.match(app, /storage\.clearToken\(\)/);
assert.match(app, /\/api\/trial-metrics/);
assert.match(app, /trialMetricsButton/);
assert.match(app, /uploadedDocument/);
assert.match(app, /refreshKnowledgeAfterUpload/);
assert.match(app, /spaceKnowledgeList/);
assert.match(app, /loadKnowledge\(\)\.then/);
assert.match(app, /spaceOpenEpoch/);
assert.match(app, /requestEpoch !== spaceOpenEpoch/);
assert.match(app, /showSpaceError/);
assert.match(app, /spaceId: state\.activeView === "space"/);
assert.match(auditView, /citation_issue_reasons/);
assert.doesNotMatch(app, /offerStartupChecklist\(\) \{[\s\S]{0,220}switchView\("settings"\)/);
assert.match(loginPage, /使用邀请码注册/);
assert.match(loginPage, /id="trialInvitationForm"/);
assert.match(loginPage, /id="loginForm" class="login-form"/);
assert.match(loginPage, /class="login-secondary-actions"/);
assert.doesNotMatch(loginPage, /value="admin@example\.com"/);
assert.doesNotMatch(loginPage, /value="admin123"/);
assert.match(composer, /window\.AgentChatComposer/);
assert.match(composer, /clipboardData\?\.getData\("text\/plain"\)/);
assert.match(composer, /event\.preventDefault\(\)/);
assert.match(composer, /document\.createTextNode\(normalized\)/);
assert.match(app, /addEventListener\("paste"/);
assert.match(app, /composer\.pastePlainText\(event, els\)/);
assert.match(loginPage, /\/static\/chat\/composer\.js\?v=p50-4-1/);
assert.match(loginPage, /\/static\/app\.js\?v=p52-8-2/);
assert.match(stream, /window\.AgentChatStream/);
assert.match(executionMode, /window\.AgentExecutionMode/);
assert.match(markdown, /window\.AgentMarkdown/);
assert.match(interactions, /window\.AgentChatInteractions/);
assert.match(runTrace, /window\.AgentRunTrace/);
assert.match(artifactPreview, /window\.AgentArtifactPreview/);
assert.match(artifactPreview, /artifact\.preview_url \|\| `\/api\/artifacts\/\$\{artifact\.id\}\/preview`/);
assert.match(artifactPreview, /Authorization: `Bearer \$\{state\.token\}`/);
assert.match(artifactPreview, /new DOMParser\(\)\.parseFromString\(content, "text\/html"\)/);
assert.match(artifactPreview, /shadow\.replaceChildren\(previewFragment\)/);
assert.match(artifactPreview, /attachShadow\(\{ mode: "open" \}\)/);
assert.match(artifactPreview, /highlightExcerpt\(root, artifact\)/);
assert.match(artifactPreview, /knowledge-hit-highlight/);
assert.match(artifactPreview, /scrollIntoView\(\{ block: "center", behavior: "smooth" \}\)/);
assert.match(loginPage, /id="artifactPreviewSurface"[^>]+role="document"/);
assert.match(loginPage, /id="artifactPreviewContent"/);
assert.match(loginPage, /\/static\/chat\/artifact-preview\.js\?v=p50-4-3/);
assert.match(loginPage, /\/static\/styles\.css\?v=p52-8-1/);
assert.match(tokenStyles, /\.login-form\s*\{[\s\S]*?display:\s*grid;[\s\S]*?gap:\s*18px;/);
assert.match(tokenStyles, /\.login-form > button,[\s\S]*?width:\s*100%;/);
assert.match(tokenStyles, /\.form-error:empty\s*\{\s*display:\s*none;/);
assert.match(resourceViews, /artifact\.previewable/);
assert.match(app, /artifactPreview\.bind\(state, els\)/);
assert.match(app, /if \(state\.artifactPreviewOpen\) artifactPreview\.showContext\(state, els\)/);
assert.match(artifactPreview, /threadContextPanel\.classList\.remove\("hidden"\)/);
assert.match(app, /data\.artifact && !wrapper\.querySelector\("\.artifact-link"\)/);
assert.match(app, /link\.dataset\.kind/);
assert.match(app, /bindKnowledgeSourceButtons\(wrapper, data\.knowledge_sources/);
assert.doesNotMatch(app, /link\.textContent = `调用资料：/);
assert.match(app, /button\._knowledgeSource = source/);
assert.match(app, /preview_url: `\/api\/knowledge\/\$\{id\}\/preview`/);
assert.match(app, /document\.highlight_excerpt \|\| document\.primary_excerpt \|\| document\.excerpt/);
assert.match(app, /source\.highlight_excerpt \|\| source\.excerpt/);
assert.match(knowledgeLibrary, /knowledge-preview/);
assert.match(knowledgeLibrary, /knowledge-structure/);
assert.match(knowledgeLibrary, /renderStructure\(els, data, escape\)/);
assert.match(knowledgeLibrary, /统一 Markdown（预览\/调试）/);
assert.match(app, /\/api\/knowledge\/\$\{document\.id\}\/structure/);
assert.match(knowledgeLibrary, /knowledge-chunks/);
assert.match(knowledgeLibrary, /renderChunks\(els, data, escape/);
assert.match(app, /\/api\/knowledge\/\$\{document\.id\}\/rechunk/);
assert.match(app, /\/api\/knowledge\/\$\{document\.id\}\/chunk-rollback/);
assert.match(app, /FTS5\/BM25/);
assert.match(loginPage, /id="knowledgeIndexStatus"/);
assert.match(loginPage, /id="knowledgeConfigurationButton"/);
assert.match(loginPage, /id="knowledgeConfigurationPage"/);
assert.match(loginPage, /id="knowledgeConfigurationTabs"/);
assert.match(loginPage, /\/static\/views\/knowledge-configuration\.js\?v=p52-8-1/);
assert.match(loginPage, /\/static\/views\/audit\.js\?v=p52-7-1/);
assert.match(app, /api\("\/api\/knowledge-configuration"\)/);
assert.match(app, /captureKnowledgeReturnState\(\)/);
assert.match(app, /requestAnimationFrame\(\(\) => \{ els\.knowledgePage\.scrollTop = saved\.scrollTop;/);
assert.match(app, /view === "knowledge-configuration" \? "knowledge" : view/);
assert.match(knowledgeConfigurationView, /window\.AgentKnowledgeConfigurationView/);
assert.match(knowledgeConfigurationView, /user_retrieval_profile/);
assert.match(knowledgeConfigurationView, /processing_presets/);
assert.match(knowledgeConfigurationView, /retrieval_policy/);
assert.match(knowledgeConfigurationView, /renderLoading/);
assert.match(knowledgeConfigurationView, /configuration-forbidden/);
assert.match(knowledgeConfigurationView, /knowledgePreferencesForm/);
assert.match(knowledgeConfigurationView, /精准/);
assert.match(knowledgeConfigurationView, /高召回/);
assert.match(knowledgeConfigurationView, /data-retrieval-candidate-form/);
assert.match(knowledgeConfigurationView, /data-evaluate-policy/);
assert.match(knowledgeConfigurationView, /data-publish-policy/);
assert.match(knowledgeConfigurationView, /data-rollback-retrieval/);
assert.match(knowledgeConfigurationView, /FTS\/BM25 字段权重（只读）/);
assert.match(knowledgeConfigurationView, /data-rebuild-embedding/);
assert.match(knowledgeConfigurationView, /data-run-embedding/);
assert.match(knowledgeConfigurationView, /data-embedding-rollback/);
assert.match(knowledgeConfigurationView, /data-retrieval-lab-form/);
assert.match(knowledgeConfigurationView, /BM25 候选/);
assert.match(knowledgeConfigurationView, /data-migration-batch-form/);
assert.match(knowledgeConfigurationView, /data-retry-migration/);
assert.match(knowledgeConfigurationView, /发布 25%/);
assert.match(auditView, /在知识库配置中心管理/);
assert.doesNotMatch(app, /preset: "standard", limit: 10/);
assert.match(knowledgeConfigurationView, /环境配置（只读）/);
assert.match(knowledgeConfigurationView, /不会发起向量网络请求/);
assert.match(knowledgeConfigurationView, /不返回凭证、服务地址、绝对路径、向量或知识正文/);
assert.match(app, /\/api\/embedding-index\/rebuild/);
assert.match(app, /confirm_document_count/);
assert.match(app, /\/api\/embedding-index\/run/);
assert.match(app, /embedding-rollback/);
assert.match(app, /\/api\/retrieval-lab\/compare/);
assert.match(app, /\/api\/knowledge-migrations\/\$\{encodeURIComponent\(batchId\)\}\/retry/);
assert.match(app, /\/api\/knowledge-configuration\/preferences/);
assert.match(loginPage, /id="retrievalProfileSelect"/);
assert.match(loginPage, /id="knowledgeScopeOverrideSelect"/);
assert.match(loginPage, /id="knowledgeUploadDialog"/);
assert.match(stream, /retrieval_profile: els\.retrievalProfileSelect\?\.value/);
assert.match(stream, /knowledge_scope: els\.knowledgeScopeOverrideSelect\?\.value/);
assert.match(app, /chunk_preset: els\.knowledgeUploadPresetSelect\.value/);
assert.doesNotMatch(knowledgeConfigurationView, /prompt\s*\(/);
assert.match(responsiveStyles, /\.workspace\.artifact-preview-open\s*\{[\s\S]*?grid-template-columns:\s*1fr;[\s\S]*?overflow:\s*hidden;/);
assert.match(responsiveStyles, /@media \(min-width: 601px\) and \(max-width: 760px\)[\s\S]*?grid-template-columns:\s*minmax\(0, 44%\) minmax\(0, 56%\)/);
assert.match(layoutStyles, /#settingsPage\s*\{[\s\S]*?min-height:\s*0;[\s\S]*?overflow:\s*hidden;/);
assert.match(layoutStyles, /#knowledgePage\s*\{[\s\S]*?overflow-y:\s*auto;[\s\S]*?overscroll-behavior:\s*contain;/);
assert.match(knowledgeStyles, /\.knowledge-structure-markdown\s*\{[\s\S]*?position:\s*sticky;[\s\S]*?height:\s*calc\(100dvh - 190px\);[\s\S]*?grid-template-rows:\s*auto minmax\(0, 1fr\);/);
assert.match(knowledgeStyles, /\.knowledge-structure-markdown pre\s*\{[\s\S]*?height:\s*100%;[\s\S]*?max-height:\s*none;[\s\S]*?overflow:\s*auto;/);
assert.match(componentStyles, /\.settings-stack\s*\{[\s\S]*?flex:\s*1;[\s\S]*?min-height:\s*0;[\s\S]*?overflow-y:\s*auto;/);
assert.match(styleEntry, /tokens-base\.css\?v=p50-5-1/);
assert.match(styleEntry, /components\.css\?v=p50-4-1/);
assert.match(styleEntry, /layout\.css\?v=p52-2-1/);
assert.match(styleEntry, /knowledge\.css\?v=p52-7-1/);
assert.match(styleEntry, /responsive\.css\?v=p52-7-1/);
assert.match(layoutStyles, /#knowledgeConfigurationPage\s*\{[\s\S]*?overflow:\s*hidden;/);
assert.match(knowledgeStyles, /\.knowledge-configuration-content\s*\{[\s\S]*?overflow-y:\s*auto;/);
assert.match(responsiveStyles, /\.configuration-summary-grid,[\s\S]*?grid-template-columns:\s*1fr;/);
assert.match(knowledgeLibrary, /window\.AgentKnowledgeLibrary/);
assert.match(spaceWorkspace, /window\.AgentSpaceWorkspace/);
assert.match(resourceViews, /window\.AgentResourceViews/);
assert.match(capabilityViews, /window\.AgentCapabilityViews/);
assert.match(settingsView, /window\.AgentSettingsView/);
assert.match(auditView, /window\.AgentAuditView/);
assert.match(auditView, /renderDetail/);
assert.match(loginPage, /自动判断（仅明确相关时读取）/);
assert.match(loginPage, /普通写作、计划、代码和闲聊不会主动调用知识库/);
assert.match(loginPage, /\/static\/views\/audit\.js\?v=p52-7-1/);
assert.match(loginPage, /\/static\/chat\/execution-mode\.js\?v=p52-3-1/);
assert.match(executionMode, /自动判断（仅明确相关时读取）/);
assert.match(auditView, /auto_route_stages: autoStages/);
assert.match(auditView, /可判定输入/);
assert.match(auditView, /执行探测/);
assert.match(auditView, /拒绝候选/);
assert.match(auditView, /最终注入/);
vm.runInContext(stream, context);
const payload = context.AgentChatStream.buildPayload({
  currentThreadId: "", pendingFolderId: "space-1", selectedSkillIds: ["skill-1"],
}, {
  modelSelect: { value: "auto" }, taskModeSelect: { value: "deep" }, sourceModeSelect: { value: "general" },
  knowledgeModeSelect: { value: "auto" }, webModeSelect: { value: "auto" }, fileModeSelect: { value: "auto" },
}, "测试", false);
assert.equal(payload.folder_id, "space-1");
assert.equal(payload.skill_ids[0], "skill-1");
let streamed;
let encodedEvent = new TextEncoder().encode('event: meta\ndata: {"thread_id":"thread-1"}\n\n');
await context.AgentChatStream.consume({ body: { getReader: () => ({
  read: async () => encodedEvent ? { done: false, value: encodedEvent } : { done: true },
}) } }, (event) => { streamed = event; encodedEvent = null; });
assert.equal(streamed.event, "meta");
assert.equal(streamed.data.thread_id, "thread-1");

vm.runInContext(artifactPreview, context);
const classSet = () => {
  const values = new Set();
  return {
    add: (...names) => names.forEach((name) => values.add(name)),
    remove: (...names) => names.forEach((name) => values.delete(name)),
    contains: (name) => values.has(name),
  };
};
const previewEls = {};
for (const key of [
  "workspaceView", "threadContextContent", "artifactPreviewContent",
  "threadContextTab", "artifactPreviewTab", "threadContextPanel",
]) {
  previewEls[key] = {
    classList: classSet(),
    setAttribute(name, value) { this[name] = value; },
  };
}
Object.assign(previewEls, {
  artifactPreviewTitle: { textContent: "" },
  artifactPreviewMeta: { textContent: "" },
  artifactPreviewNotice: { textContent: "" },
  artifactPreviewSurface: {
    shadowRoot: null,
    replaceChildren() {},
    attachShadow() {
      this.shadowRoot = {
        adoptedStyleSheets: [],
        children: [],
        querySelectorAll: () => [],
        replaceChildren(...children) { this.children = children; },
      };
      return this.shadowRoot;
    },
  },
  artifactPreviewDownload: { onclick: null },
});
const previewState = { token: "preview-token" };
context.fetch = async (path, options) => {
  request = { path, options };
  return {
    ok: true,
    text: async () => "<!doctype html><p>preview</p>",
  };
};
await context.AgentArtifactPreview.open(
  previewState,
  previewEls,
  { id: "artifact-1", filename: "report.html", kind: "html", revision: 1, previewable: true },
  async () => {},
);
assert.equal(request.path, "/api/artifacts/artifact-1/preview");
assert.equal(request.options.headers.Authorization, "Bearer preview-token");
assert.equal(previewState.artifactPreviewOpen, true);
assert.equal(previewEls.artifactPreviewSurface.shadowRoot.children.length, 1);

await context.AgentArtifactPreview.open(
  previewState,
  previewEls,
  { id: "artifact-2", filename: "report.md", kind: "markdown", revision: 1, previewable: true },
  async () => {},
);
assert.equal(request.path, "/api/artifacts/artifact-2/preview");
assert.equal(previewEls.artifactPreviewSurface.shadowRoot.children.length, 1);

console.log("frontend core module checks passed");
