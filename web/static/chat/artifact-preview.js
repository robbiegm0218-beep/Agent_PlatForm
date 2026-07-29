window.AgentArtifactPreview = {
  clearSurface(els) {
    els.artifactPreviewSurface.replaceChildren();
    if (els.artifactPreviewSurface.shadowRoot) {
      els.artifactPreviewSurface.shadowRoot.replaceChildren();
      els.artifactPreviewSurface.shadowRoot.adoptedStyleSheets = [];
    }
  },

  highlightExcerpt(root, artifact) {
    const excerpt = String(artifact.highlight_excerpt || "").trim();
    if (!excerpt || !root) return 0;
    const normalize = (value) => String(value || "")
      .replace(/^[\s#>*+\-\d.)、]+/gm, "")
      .replace(/[*_`~[\]]/g, "")
      .replace(/\s+/g, "")
      .trim();
    const lines = excerpt
      .split(/\n+/)
      .map(normalize)
      .filter((line) => line.length >= 4);
    const whole = normalize(excerpt);
    const elements = [...root.querySelectorAll("p, li, h1, h2, h3, h4, pre, td, th")];
    let matches = elements.filter((element) => {
      const text = normalize(element.textContent);
      if (text.length < 4) return false;
      return lines.some((line) => text.includes(line) || line.includes(text));
    });
    if (!matches.length && whole) {
      matches = elements.filter((element) => {
        const text = normalize(element.textContent);
        const probe = text.length <= whole.length ? text : whole;
        return probe.length >= 8 && (text.includes(probe) || whole.includes(probe));
      });
    }
    matches = matches.slice(0, 8);
    matches.forEach((element) => {
      element.classList.add("knowledge-hit-highlight");
      element.dataset.knowledgeHit = "true";
    });
    matches[0]?.scrollIntoView({ block: "center", behavior: "smooth" });
    return matches.length;
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
      const previewFragment = document.createDocumentFragment();
      for (const child of [...documentPreview.body.childNodes]) {
        previewFragment.appendChild(document.importNode(child, true));
      }
      // A shadow root cannot be detached after the first HTML preview. Render
      // every file type into the same isolated surface so switching from HTML
      // to Markdown, Excel, JSON, PDF, Word, text, or images never hides the
      // newly loaded light-DOM content behind an existing empty shadow root.
      const shadow = els.artifactPreviewSurface.shadowRoot || els.artifactPreviewSurface.attachShadow({ mode: "open" });
      const artifactCss = [...documentPreview.querySelectorAll("style")].map((style) => style.textContent || "").join("\n");
      const baseCss = `
        :host { display: block; height: 100%; overflow: auto; background: white; color: #252522; }
        *, *::before, *::after { box-sizing: border-box; }
        .preview-document { min-height: 100%; }
        img { max-width: 100%; height: auto; }
        .knowledge-hit-highlight {
          background: #fff2a8 !important;
          box-shadow: 0 0 0 3px #fff2a8;
          border-radius: 3px;
        }
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
      const previewRoot = shadow;
      this.highlightExcerpt(previewRoot, artifact);
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
