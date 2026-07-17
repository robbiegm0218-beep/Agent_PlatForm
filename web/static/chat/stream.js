window.AgentChatStream = {
  buildPayload(state, els, content, retry) {
    const payload = {
      thread_id: state.currentThreadId,
      content,
      retry,
      model: els.modelSelect.value,
      task_mode: els.taskModeSelect.value,
      source_mode: els.sourceModeSelect.value,
      knowledge_mode: els.knowledgeModeSelect.value,
      web_mode: els.webModeSelect.value,
      file_mode: els.fileModeSelect.value,
    };
    if (!state.currentThreadId && state.pendingFolderId) payload.folder_id = state.pendingFolderId;
    if (state.selectedSkillIds.length) payload.skill_ids = state.selectedSkillIds;
    return payload;
  },

  async open(state, payload) {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.token}` },
      body: JSON.stringify(payload),
    });
    if (!response.ok || !response.body) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "发送失败");
    }
    return response;
  },

  async consume(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";
      events.forEach((eventText) => onEvent(this.parseSse(eventText)));
    }
  },

  parseSse(text) {
    const lines = text.split("\n");
    const eventLine = lines.find((line) => line.startsWith("event: "));
    const dataLine = lines.find((line) => line.startsWith("data: "));
    return {
      event: eventLine ? eventLine.slice(7) : "message",
      data: dataLine ? JSON.parse(dataLine.slice(6)) : {},
    };
  },
};
