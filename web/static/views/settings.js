window.AgentSettingsView = {
  async save(api, name) {
    return api("/api/me", { method: "PATCH", body: JSON.stringify({ name }) });
  },
  async logout(api, allDevices = false) {
    if (allDevices) return api("/api/logout-all", { method: "POST" });
    return api("/api/logout", { method: "POST" }).catch(() => {});
  },
  async changePassword(api, currentPassword, newPassword) {
    return api("/api/password/change", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
  },
  async exportPersonalData(api) {
    return api("/api/data-export", {
      method: "POST",
      body: JSON.stringify({ confirmation: "EXPORT_MY_DATA" }),
    });
  },
  async requestAccountDeletion(api) {
    return api("/api/account-deletion/request", {
      method: "POST",
      body: JSON.stringify({ confirmation: "DELETE_MY_ACCOUNT" }),
    });
  },
  async cancelAccountDeletion(api) {
    return api("/api/account-deletion/cancel", { method: "POST", body: JSON.stringify({}) });
  },
  async loadHostingStatus(api) {
    const [startup, security, usage, deletion] = await Promise.all([
      api("/api/startup-status"),
      api("/api/security-events"),
      api("/api/personal-usage"),
      api("/api/account-deletion"),
    ]);
    return { startup, events: security.events || [], usage, deletion };
  },
};
