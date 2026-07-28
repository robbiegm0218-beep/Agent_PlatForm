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

assert.equal(context.AgentState.token, "token-1");
context.AgentStorage.saveWorkspace("workspace", { view: "knowledge" });
assert.equal(context.AgentStorage.loadWorkspace("workspace").view, "knowledge");
assert.equal(context.AgentElements.modelStatus.selector, "#modelStatus");

let request;
context.fetch = async (path, options) => {
  request = { path, options };
  return { ok: true, json: async () => ({ ok: true }) };
};
await context.AgentApi("/api/me", { method: "GET" });
assert.equal(request.options.headers.Authorization, "Bearer token-1");

context.fetch = async () => ({ ok: false, status: 401, json: async () => ({ error: "未授权" }) });
await assert.rejects(() => context.AgentApi("/api/me"), (error) => error.status === 401 && error.message === "未授权");

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
const auditView = readFileSync(new URL("../web/static/views/audit.js", import.meta.url), "utf8");
const responsiveStyles = readFileSync(new URL("../web/static/styles/responsive.css", import.meta.url), "utf8");
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
assert.doesNotMatch(loginPage, /value="admin@example\.com"/);
assert.doesNotMatch(loginPage, /value="admin123"/);
assert.match(composer, /window\.AgentChatComposer/);
assert.match(stream, /window\.AgentChatStream/);
assert.match(executionMode, /window\.AgentExecutionMode/);
assert.match(markdown, /window\.AgentMarkdown/);
assert.match(interactions, /window\.AgentChatInteractions/);
assert.match(runTrace, /window\.AgentRunTrace/);
assert.match(artifactPreview, /window\.AgentArtifactPreview/);
assert.match(artifactPreview, /artifact\.preview_url \|\| `\/api\/artifacts\/\$\{artifact\.id\}\/preview`/);
assert.match(artifactPreview, /Authorization: `Bearer \$\{state\.token\}`/);
assert.match(artifactPreview, /new DOMParser\(\)\.parseFromString\(content, "text\/html"\)/);
assert.match(artifactPreview, /artifactPreviewSurface\.replaceChildren\(previewFragment\)/);
assert.match(artifactPreview, /attachShadow\(\{ mode: "open" \}\)/);
assert.match(artifactPreview, /agent-preview-mode/);
assert.match(loginPage, /id="artifactPreviewSurface"[^>]+role="document"/);
assert.match(loginPage, /id="artifactPreviewContent"/);
assert.match(loginPage, /\/static\/app\.js\?v=p48-4-3/);
assert.match(loginPage, /\/static\/styles\.css\?v=p48-4-4/);
assert.match(resourceViews, /artifact\.previewable/);
assert.match(app, /artifactPreview\.bind\(state, els\)/);
assert.match(app, /if \(state\.artifactPreviewOpen\) artifactPreview\.showContext\(state, els\)/);
assert.match(artifactPreview, /threadContextPanel\.classList\.remove\("hidden"\)/);
assert.match(app, /data\.artifact && !wrapper\.querySelector\("\.artifact-link"\)/);
assert.match(app, /link\.dataset\.kind/);
assert.match(app, /appendKnowledgeSourceLinks\(wrapper, data\.knowledge_sources/);
assert.match(app, /preview_url: `\/api\/knowledge\/\$\{id\}\/preview`/);
assert.match(knowledgeLibrary, /knowledge-preview/);
assert.match(responsiveStyles, /\.workspace\.artifact-preview-open\s*\{[\s\S]*?grid-template-columns:\s*1fr;[\s\S]*?overflow:\s*hidden;/);
assert.match(responsiveStyles, /@media \(min-width: 601px\) and \(max-width: 760px\)[\s\S]*?grid-template-columns:\s*minmax\(0, 44%\) minmax\(0, 56%\)/);
assert.match(styleEntry, /responsive\.css\?v=p48-3-1/);
assert.match(knowledgeLibrary, /window\.AgentKnowledgeLibrary/);
assert.match(spaceWorkspace, /window\.AgentSpaceWorkspace/);
assert.match(resourceViews, /window\.AgentResourceViews/);
assert.match(capabilityViews, /window\.AgentCapabilityViews/);
assert.match(settingsView, /window\.AgentSettingsView/);
assert.match(auditView, /window\.AgentAuditView/);
assert.match(auditView, /renderDetail/);
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
  artifactPreviewSurface: { replaceChildren() {} },
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

console.log("frontend core module checks passed");
