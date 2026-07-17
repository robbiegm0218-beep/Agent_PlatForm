window.AgentApi = function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (window.AgentState.token) headers.Authorization = `Bearer ${window.AgentState.token}`;
  return fetch(path, { ...options, headers }).then(async (response) => {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error || "请求失败");
      error.status = response.status;
      throw error;
    }
    return data;
  });
};
