window.AgentCapabilityViews = {
  skillSummary(skill) {
    const normalized = String(skill.description || skill.prompt || "暂无技能说明").replace(/^#{1,6}\s*/gm, "").replace(/[`*_]/g, "").replace(/\s+/g, " ").trim();
    return normalized.length > 150 ? `${normalized.slice(0, 147).trimEnd()}…` : normalized;
  },
  renderSkills(els, skills, escape, { onToggle, onEdit, onVersion, onDelete }) {
    els.skillsGrid.innerHTML = "";
    skills.forEach((skill) => {
      const card = document.createElement("article");
      card.className = "capability-card";
      card.innerHTML = `<h3>${escape(skill.name)}</h3><p class="skill-description" title="${escape(skill.description || skill.prompt || "")}">${escape(this.skillSummary(skill))}</p><div class="card-footer"><div class="skill-state"><span class="status-pill">${skill.enabled ? "已启用" : "未启用"}</span><label class="switch"><input type="checkbox" ${skill.enabled ? "checked" : ""}/><span></span></label></div><div class="skill-actions"><button class="skill-action skill-edit" type="button">编辑</button><button class="skill-action skill-version" type="button">版本</button><button class="skill-action danger skill-delete" type="button">删除</button></div></div>`;
      const input = card.querySelector("input");
      const pill = card.querySelector(".status-pill");
      input.addEventListener("change", async () => { try { await onToggle(skill, input.checked); pill.textContent = input.checked ? "已启用" : "未启用"; } catch (error) { input.checked = !input.checked; window.alert(error.message); } });
      card.querySelector(".skill-edit").addEventListener("click", () => onEdit(skill));
      card.querySelector(".skill-version").addEventListener("click", () => onVersion(skill));
      card.querySelector(".skill-delete").addEventListener("click", () => onDelete(skill));
      els.skillsGrid.appendChild(card);
    });
  },
  renderApps(els, apps, tools, escape, { onExecute }) {
    els.appsGrid.innerHTML = "";
    apps.forEach((app) => {
      const card = document.createElement("article");
      card.className = "capability-card";
      card.innerHTML = `<h3>${escape(app.name)}</h3><p>${escape(app.description)}</p><div class="card-footer"><span class="status-pill">${escape(app.status)}</span></div>`;
      els.appsGrid.appendChild(card);
    });
    tools.forEach((tool) => {
      const card = document.createElement("article");
      card.className = "capability-card tool-card";
      const heading = document.createElement("h3"); heading.textContent = tool.name;
      const description = document.createElement("p"); description.textContent = tool.description;
      const form = document.createElement("form"); form.className = "tool-form";
      const properties = tool.input_schema?.properties || {};
      Object.entries(properties).forEach(([key, definition]) => {
        const label = document.createElement("label"); label.textContent = definition.description || key;
        const input = document.createElement("input"); input.name = key; input.type = definition.type === "integer" ? "number" : "text";
        input.required = (tool.input_schema?.required || []).includes(key); if (definition.type === "integer") input.min = key === "limit" ? "1" : "";
        label.appendChild(input); form.appendChild(label);
      });
      const submit = document.createElement("button"); submit.type = "submit"; submit.textContent = tool.enabled ? "执行" : "未启用"; submit.disabled = !tool.enabled;
      const result = document.createElement("pre"); result.className = "tool-result hidden";
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const args = {};
        Object.entries(properties).forEach(([key, definition]) => { const raw = form.elements[key]?.value.trim(); if (raw !== "") args[key] = definition.type === "integer" ? Number(raw) : raw; });
        submit.disabled = true; result.classList.remove("hidden"); result.textContent = "正在执行…";
        try { result.textContent = JSON.stringify(await onExecute(tool, args), null, 2); }
        catch (error) { result.textContent = `执行失败：${error.message}\n修改参数后可再次执行。`; }
        finally { submit.disabled = !tool.enabled; }
      });
      form.append(submit, result);
      const footer = document.createElement("div"); footer.className = "card-footer"; footer.innerHTML = `<span class="status-pill">${tool.enabled ? "本地只读工具" : "未启用"}</span>`;
      card.append(heading, description, form, footer); els.appsGrid.appendChild(card);
    });
  },
};
