window.AgentState = {
  token: window.AgentStorage ? window.AgentStorage.getToken() : (localStorage.getItem("agent_platform_token") || ""),
  user: null,
  threads: [], folders: [], collapsedFolderIds: new Set(), spacesCollapsed: false, tasksCollapsed: false,
  demoMembersBySpace: {}, currentThreadId: "", pendingFolderId: "", messages: [], runs: [],
  threadContext: { sources: [], outputs: [] }, skills: [], models: [], artifacts: [], tools: [],
  knowledgeDocuments: [], memories: [], selectedSkillIds: [], activeView: "chat", streaming: false,
  currentThreadEditable: true, spaceComposerFolder: null, knowledgeUploadSpaceId: "", currentSpaceId: "",
};

window.AgentUiState = {
  key: "agent_platform_workspace_state",
  validViews: new Set(["chat", "skills", "settings", "knowledge", "memories", "artifacts", "space"]),
};
