window.AgentRunTrace = {
  appendAssistantMessage(els) {
    const wrapper = document.createElement("article");
    wrapper.className = "message assistant";
    wrapper.innerHTML = `
      <div class="message-role">Agent_Platform</div>
      <section class="reasoning-summary hidden">
        <button class="reasoning-summary-toggle" type="button" aria-expanded="false"><span>推理摘要</span><span class="reasoning-summary-chevron">⌄</span></button>
        <div class="reasoning-summary-body hidden"><ul></ul></div>
      </section>
      <section class="execution-trace">
        <button class="execution-trace-toggle" type="button" aria-expanded="true"><span class="execution-trace-title">执行过程</span><span class="execution-trace-time">预计剩余 30 秒</span><span class="execution-trace-chevron">⌃</span></button>
        <div class="execution-trace-body"><ol class="execution-trace-list"><li>正在准备运行</li></ol></div>
      </section>
      <div class="answer-label">最终回答</div>
      <div class="message-content"></div>
    `;
    els.messages.appendChild(wrapper);
    els.messages.scrollTop = els.messages.scrollHeight;
    const traceToggle = wrapper.querySelector(".execution-trace-toggle");
    const traceBody = wrapper.querySelector(".execution-trace-body");
    traceToggle.addEventListener("click", () => {
      const expanded = traceToggle.getAttribute("aria-expanded") === "true";
      traceToggle.setAttribute("aria-expanded", String(!expanded));
      traceBody.classList.toggle("hidden", expanded);
    });
    const reasoning = wrapper.querySelector(".reasoning-summary");
    const reasoningToggle = wrapper.querySelector(".reasoning-summary-toggle");
    const reasoningBody = wrapper.querySelector(".reasoning-summary-body");
    reasoningToggle.addEventListener("click", () => {
      const expanded = reasoningToggle.getAttribute("aria-expanded") === "true";
      reasoningToggle.setAttribute("aria-expanded", String(!expanded));
      reasoningBody.classList.toggle("hidden", expanded);
    });
    return {
      wrapper, traceToggle, traceTitle: wrapper.querySelector(".execution-trace-title"),
      traceTime: wrapper.querySelector(".execution-trace-time"), traceList: wrapper.querySelector(".execution-trace-list"),
      reasoning, reasoningToggle, reasoningBody, reasoningList: reasoning.querySelector("ul"),
      content: wrapper.querySelector(".message-content"),
    };
  },

  renderReasoningSummary(assistant, items) {
    if (!Array.isArray(items) || !items.length) return;
    assistant.reasoningList.replaceChildren();
    items.slice(0, 5).forEach((text) => {
      const item = document.createElement("li");
      item.textContent = text;
      assistant.reasoningList.appendChild(item);
    });
    assistant.reasoning.classList.remove("hidden");
  },

  appendExecutionTrace(els, assistant, summary) {
    const last = assistant.traceList.lastElementChild;
    if (last?.textContent === summary) return;
    const item = document.createElement("li");
    item.textContent = summary;
    assistant.traceList.appendChild(item);
    assistant.traceTitle.textContent = `执行过程 · ${assistant.traceList.children.length} 步`;
    els.messages.scrollTop = els.messages.scrollHeight;
  },

  startCountdown(assistant) {
    const startedAt = Date.now();
    const update = () => {
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      const remaining = Math.max(0, 30 - elapsed);
      assistant.traceTime.textContent = remaining ? `预计剩余 ${remaining} 秒 · 已用 ${elapsed} 秒` : `正在继续处理 · 已用 ${elapsed} 秒`;
    };
    update();
    const timer = window.setInterval(update, 1000);
    return {
      stop(label = "已完成") {
        window.clearInterval(timer);
        const elapsed = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
        assistant.traceTime.textContent = `${label} · 用时 ${elapsed} 秒`;
      },
      timer,
    };
  },
};
