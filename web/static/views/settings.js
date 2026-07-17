window.AgentSettingsView = {
  async save(api, name) {
    return api("/api/me", { method: "PATCH", body: JSON.stringify({ name }) });
  },
  async logout(api, allDevices = false) {
    if (allDevices) return api("/api/logout-all", { method: "POST" });
    return api("/api/logout", { method: "POST" }).catch(() => {});
  },
};
