window.AgentApi = function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (window.AgentState.token) headers.Authorization = `Bearer ${window.AgentState.token}`;
  return fetch(path, { ...options, headers })
    .then(async (response) => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(data.error || "请求失败");
        error.status = response.status;
        throw error;
      }
      return data;
    })
    .catch((error) => {
      if (error?.status) throw error;
      if (error?.name === "TypeError") {
        throw new Error("无法连接本地服务，请确认服务已启动后重试。");
      }
      throw error;
    });
};
