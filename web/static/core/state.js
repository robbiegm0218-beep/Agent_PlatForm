window.AgentState = {
  token: window.AgentStorage ? window.AgentStorage.getToken() : (localStorage.getItem("agent_platform_token") || ""),
  user: null,
  threads: [], folders: [], collapsedFolderIds: new Set(), spacesCollapsed: false, tasksCollapsed: false,
  demoMembersBySpace: {}, currentThreadId: "", pendingFolderId: "", messages: [], runs: [],
  threadContext: { sources: [], outputs: [] }, skills: [], models: [], artifacts: [], tools: [],
  knowledgeDocuments: [], knowledgeProcessingRuns: [], memories: [], selectedSkillIds: [], activeView: "chat", streaming: false,
  currentThreadEditable: true, spaceComposerFolder: null, knowledgeUploadSpaceId: "", pendingKnowledgeUploadFile: null, currentSpaceId: "",
  selectedArtifactId: "", artifactPreviewOpen: false, artifactPreviewRevision: 0,
  knowledgeConfiguration: null, knowledgeConfigurationLoading: false, knowledgeConfigurationTab: "overview", knowledgeReprocessingBatches: [], knowledgeRetrievalGovernance: {}, knowledgeEmbeddingGovernance: {}, knowledgeMigrationGovernance: {},
  knowledgeReturnState: { scrollTop: 0, search: "", scope: "general", projectId: "" },
};

window.AgentUiState = {
  key: "agent_platform_workspace_state",
  validViews: new Set(["chat", "skills", "settings", "knowledge", "knowledge-configuration", "memories", "artifacts", "space"]),
};
