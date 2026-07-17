window.AgentStorage = {
  tokenKey: "agent_platform_token",
  getToken() { return localStorage.getItem(this.tokenKey) || ""; },
  setToken(token) { localStorage.setItem(this.tokenKey, token); },
  clearToken() { localStorage.removeItem(this.tokenKey); },
  saveWorkspace(key, value) { localStorage.setItem(key, JSON.stringify(value)); },
  loadWorkspace(key) {
    try { return JSON.parse(localStorage.getItem(key) || "{}"); }
    catch (_error) { localStorage.removeItem(key); return {}; }
  },
};
