window.AgentArtifactPreview = {
  clearSurface(els) {
    els.artifactPreviewSurface.replaceChildren();
    if (els.artifactPreviewSurface.shadowRoot) {
      els.artifactPreviewSurface.shadowRoot.replaceChildren();
      els.artifactPreviewSurface.shadowRoot.adoptedStyleSheets = [];
    }
  },

  showContext(state, els) {
    state.artifactPreviewOpen = false;
    this.clearSurface(els);
    els.workspaceView.classList.remove("artifact-preview-open");
    els.threadContextPanel.classList.toggle("hidden", state.activeView !== "chat");
    els.threadContextContent.classList.remove("hidden");
    els.artifactPreviewContent.classList.add("hidden");
    els.threadContextTab.classList.add("active");
    els.threadContextTab.setAttribute("aria-selected", "true");
    els.artifactPreviewTab.classList.remove("active");
    els.artifactPreviewTab.setAttribute("aria-selected", "false");
  },

  async open(state, els, artifact, onDownload) {
    if (!artifact?.previewable) {
      await onDownload(artifact);
      return;
    }
    state.selectedArtifactId = artifact.id;
    state.artifactPreviewOpen = true;
    state.artifactPreviewRevision = Number(artifact.revision || 1);
    els.workspaceView.classList.add("artifact-preview-open");
    els.threadContextPanel.classList.remove("hidden");
    els.threadContextContent.classList.add("hidden");
    els.artifactPreviewContent.classList.remove("hidden");
    els.threadContextTab.classList.remove("active");
    els.threadContextTab.setAttribute("aria-selected", "false");
    els.artifactPreviewTab.disabled = false;
    els.artifactPreviewTab.classList.add("active");
    els.artifactPreviewTab.setAttribute("aria-selected", "true");
    els.artifactPreviewTitle.textContent = artifact.filename;
    els.artifactPreviewMeta.textContent = `${String(artifact.kind || "").toUpperCase()} · 版本 ${state.artifactPreviewRevision}`;
    els.artifactPreviewNotice.textContent = "正在加载安全预览…";
    this.clearSurface(els);
    els.artifactPreviewDownload.onclick = () => onDownload(artifact);
    try {
      const previewUrl = artifact.preview_url || `/api/artifacts/${artifact.id}/preview`;
      const response = await fetch(previewUrl, {
        headers: { Authorization: `Bearer ${state.token}` },
        cache: "no-store",
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "文件预览失败");
      }
      const content = await response.text();
      if (state.selectedArtifactId !== artifact.id) return;
      const documentPreview = new DOMParser().parseFromString(content, "text/html");
      const htmlDocumentMode = documentPreview.querySelector('meta[name="agent-preview-mode"]')?.content === "html-document";
      const previewFragment = document.createDocumentFragment();
      for (const child of [...documentPreview.body.childNodes]) {
        previewFragment.appendChild(document.importNode(child, true));
      }
      if (htmlDocumentMode) {
        const shadow = els.artifactPreviewSurface.shadowRoot || els.artifactPreviewSurface.attachShadow({ mode: "open" });
        const artifactCss = [...documentPreview.querySelectorAll("style")].map((style) => style.textContent || "").join("\n");
        const baseCss = `
          :host { display: block; height: 100%; overflow: auto; background: white; color: #252522; }
          *, *::before, *::after { box-sizing: border-box; }
          .preview-document { min-height: 100%; }
          img { max-width: 100%; }
        `;
        try {
          const sheet = new CSSStyleSheet();
          sheet.replaceSync(`${baseCss}\n${artifactCss}`);
          shadow.adoptedStyleSheets = [sheet];
          shadow.replaceChildren(previewFragment);
        } catch (_error) {
          const style = document.createElement("style");
          style.textContent = `${baseCss}\n${artifactCss}`;
          shadow.replaceChildren(style, previewFragment);
        }
      } else {
        // Non-HTML files use the platform's fixed document template.
        els.artifactPreviewSurface.replaceChildren(previewFragment);
      }
      els.artifactPreviewNotice.textContent = "";
    } catch (error) {
      els.artifactPreviewNotice.textContent = error.message || "文件预览失败";
    }
  },

  bind(state, els) {
    els.threadContextTab.addEventListener("click", () => this.showContext(state, els));
    els.artifactPreviewTab.addEventListener("click", () => {
      if (state.selectedArtifactId) {
        state.artifactPreviewOpen = true;
        els.threadContextContent.classList.add("hidden");
        els.artifactPreviewContent.classList.remove("hidden");
        els.threadContextTab.classList.remove("active");
        els.threadContextTab.setAttribute("aria-selected", "false");
        els.artifactPreviewTab.classList.add("active");
        els.artifactPreviewTab.setAttribute("aria-selected", "true");
      }
    });
    els.artifactPreviewClose.addEventListener("click", () => this.showContext(state, els));
  },
};
