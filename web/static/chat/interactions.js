window.AgentChatInteractions = {
  appendConfirmationActions({ assistant, confirmation, api, state, appendTrace, renderContent, appendArtifact, refreshThreads, loadRuns }) {
    if (assistant.wrapper.querySelector(".confirmation-actions")) return;
    const actions = document.createElement("div");
    actions.className = "confirmation-actions";
    const approveButton = document.createElement("button");
    approveButton.type = "button";
    approveButton.textContent = "确认执行";
    const rejectButton = document.createElement("button");
    rejectButton.type = "button";
    rejectButton.className = "secondary";
    rejectButton.textContent = "取消";
    const setBusy = (busy) => { approveButton.disabled = busy; rejectButton.disabled = busy; };
    approveButton.addEventListener("click", async () => {
      setBusy(true);
      appendTrace(assistant, "正在继续执行已确认操作");
      try {
        const result = await api(`/api/runs/${confirmation.run_id}/confirmation`, {
          method: "POST", body: JSON.stringify({ approved: true }),
        });
        appendTrace(assistant, "已完成已确认操作");
        renderContent(assistant.content, result.content || "");
        if (result.content) state.messages.push({ role: "assistant", content: result.content });
        actions.remove();
        if (result.artifact) appendArtifact(assistant.wrapper, result.artifact);
        await Promise.all([refreshThreads(), loadRuns()]);
      } catch (error) {
        appendTrace(assistant, "已确认操作执行失败");
        assistant.content.textContent = error.message || "文件生成失败";
        setBusy(false);
      }
    });
    rejectButton.addEventListener("click", async () => {
      setBusy(true);
      try {
        await api(`/api/runs/${confirmation.run_id}/confirmation`, {
          method: "POST", body: JSON.stringify({ approved: false }),
        });
        appendTrace(assistant, "已取消待确认操作");
        assistant.content.textContent = "已取消本次文件生成，未创建任何文件。";
        actions.remove();
        await loadRuns();
      } catch (error) {
        appendTrace(assistant, "取消待确认操作失败");
        assistant.content.textContent = error.message || "取消失败";
        setBusy(false);
      }
    });
    actions.append(approveButton, rejectButton);
    assistant.wrapper.appendChild(actions);
  },

  appendRetryButton(wrapper, content, onRetry) {
    if (wrapper.querySelector(".retry-button")) return;
    const retryButton = document.createElement("button");
    retryButton.className = "retry-button";
    retryButton.type = "button";
    retryButton.textContent = "重试";
    retryButton.addEventListener("click", () => onRetry(content));
    wrapper.appendChild(retryButton);
  },
};
