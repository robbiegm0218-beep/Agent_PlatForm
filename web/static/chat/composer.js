window.AgentChatComposer = {
  getPromptText(els) {
    return [...els.chatInput.childNodes]
      .filter((node) => !(node.nodeType === Node.ELEMENT_NODE && node.classList.contains("skill-tag")))
      .map((node) => node.textContent)
      .join("")
      .trim();
  },

  getChatContent(state, els) {
    const selected = state.skills.filter((skill) => state.selectedSkillIds.includes(skill.id) && skill.enabled);
    const tags = selected.map((skill) => `@${skill.name}`).join(" ");
    return [tags, this.getPromptText(els)].filter(Boolean).join(" ");
  },

  focus(els) {
    els.chatInput.focus();
    const range = document.createRange();
    range.selectNodeContents(els.chatInput);
    range.collapse(false);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  },

  renderSkills(state, els) {
    const prompt = this.getPromptText(els);
    const selected = state.skills.filter((skill) => state.selectedSkillIds.includes(skill.id) && skill.enabled);
    els.chatInput.innerHTML = "";
    selected.forEach((skill) => {
      const tag = document.createElement("span");
      tag.className = "skill-tag";
      tag.dataset.skillId = skill.id;
      tag.setAttribute("contenteditable", "false");
      tag.textContent = `@${skill.name}`;
      els.chatInput.appendChild(tag);
    });
    if (prompt) els.chatInput.appendChild(document.createTextNode(prompt));
    const availableCount = state.skills.filter((skill) => skill.enabled).length;
    els.skillPickerButton.textContent = selected.length
      ? `已选 ${selected.length} · ${availableCount} 项可用`
      : `选择技能 · ${availableCount} 项可用`;
  },

  renderPicker(state, els, onToggle) {
    const enabledSkills = state.skills.filter((skill) => skill.enabled);
    els.skillPickerMenu.innerHTML = "";
    if (!enabledSkills.length) {
      const empty = document.createElement("div");
      empty.className = "skill-picker-empty";
      empty.textContent = "暂无已启用技能";
      els.skillPickerMenu.appendChild(empty);
      return;
    }
    enabledSkills.forEach((skill) => {
      const item = document.createElement("label");
      item.className = "skill-picker-item";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = state.selectedSkillIds.includes(skill.id);
      input.addEventListener("change", () => onToggle(skill.id));
      const text = document.createElement("span");
      text.textContent = skill.name;
      item.append(input, text);
      els.skillPickerMenu.appendChild(item);
    });
  },

  toggleSkill(state, skillId) {
    state.selectedSkillIds = state.selectedSkillIds.includes(skillId)
      ? state.selectedSkillIds.filter((id) => id !== skillId)
      : [...state.selectedSkillIds, skillId];
  },

  removeSkillBeforeCaret(state, els) {
    const selection = window.getSelection();
    if (!selection.rangeCount || !selection.isCollapsed) return false;
    const range = selection.getRangeAt(0);
    const container = range.startContainer;
    const offset = range.startOffset;
    let previous = null;
    if (container === els.chatInput && offset > 0) previous = els.chatInput.childNodes[offset - 1];
    else if (container.nodeType === Node.TEXT_NODE && offset === 0) previous = container.previousSibling;
    if (previous?.nodeType === Node.TEXT_NODE && !previous.textContent) previous = previous.previousSibling;
    if (!(previous instanceof HTMLElement) || !previous.classList.contains("skill-tag")) return false;
    state.selectedSkillIds = state.selectedSkillIds.filter((skillId) => skillId !== previous.dataset.skillId);
    return true;
  },
};
