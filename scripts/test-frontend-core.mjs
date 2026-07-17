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
  localStorage,
  document: { querySelector: (selector) => {
    if (!elements.has(selector)) elements.set(selector, { selector });
    return elements.get(selector);
  } },
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
const composer = readFileSync(new URL("../web/static/chat/composer.js", import.meta.url), "utf8");
const stream = readFileSync(new URL("../web/static/chat/stream.js", import.meta.url), "utf8");
const executionMode = readFileSync(new URL("../web/static/chat/execution-mode.js", import.meta.url), "utf8");
const markdown = readFileSync(new URL("../web/static/chat/markdown.js", import.meta.url), "utf8");
const interactions = readFileSync(new URL("../web/static/chat/interactions.js", import.meta.url), "utf8");
const runTrace = readFileSync(new URL("../web/static/chat/run-trace.js", import.meta.url), "utf8");
const knowledgeLibrary = readFileSync(new URL("../web/static/knowledge/library.js", import.meta.url), "utf8");
const spaceWorkspace = readFileSync(new URL("../web/static/space/workspace.js", import.meta.url), "utf8");
const resourceViews = readFileSync(new URL("../web/static/views/resources.js", import.meta.url), "utf8");
const capabilityViews = readFileSync(new URL("../web/static/views/capabilities.js", import.meta.url), "utf8");
const settingsView = readFileSync(new URL("../web/static/views/settings.js", import.meta.url), "utf8");
const auditView = readFileSync(new URL("../web/static/views/audit.js", import.meta.url), "utf8");
assert.match(app, /storage\.saveWorkspace\(UI_STATE_KEY/);
assert.match(app, /storage\.loadWorkspace\(UI_STATE_KEY\)/);
assert.match(app, /storage\.clearToken\(\)/);
assert.match(composer, /window\.AgentChatComposer/);
assert.match(stream, /window\.AgentChatStream/);
assert.match(executionMode, /window\.AgentExecutionMode/);
assert.match(markdown, /window\.AgentMarkdown/);
assert.match(interactions, /window\.AgentChatInteractions/);
assert.match(runTrace, /window\.AgentRunTrace/);
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

console.log("frontend core module checks passed");
