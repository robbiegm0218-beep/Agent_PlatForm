window.AgentMarkdown = {
  render(markdown) {
    const root = document.createElement("div");
    root.className = "markdown-body";
    const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) { index += 1; continue; }
      if (line.startsWith("```")) {
        const language = line.slice(3).trim();
        const codeLines = [];
        index += 1;
        while (index < lines.length && !lines[index].startsWith("```")) codeLines.push(lines[index++]);
        if (index < lines.length) index += 1;
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        if (language) code.dataset.language = language;
        code.textContent = codeLines.join("\n");
        pre.appendChild(code);
        root.appendChild(pre);
        continue;
      }
      const heading = /^(#{1,3})\s+(.+)$/.exec(line);
      if (heading) {
        const title = document.createElement(`h${heading[1].length + 2}`);
        this.renderInline(title, heading[2].trim());
        root.appendChild(title);
        index += 1;
        continue;
      }
      if (/^>\s?/.test(line)) {
        const quote = document.createElement("blockquote");
        const quoteLines = [];
        while (index < lines.length && /^>\s?/.test(lines[index])) quoteLines.push(lines[index++].replace(/^>\s?/, ""));
        this.renderInline(quote, quoteLines.join("\n"));
        root.appendChild(quote);
        continue;
      }
      const listMatch = /^(\s*)([-*]|\d+\.)\s+(.+)$/.exec(line);
      if (listMatch) {
        const ordered = /\d+\./.test(listMatch[2]);
        const list = document.createElement(ordered ? "ol" : "ul");
        while (index < lines.length) {
          const itemMatch = /^(\s*)([-*]|\d+\.)\s+(.+)$/.exec(lines[index]);
          if (!itemMatch || (/\d+\./.test(itemMatch[2]) !== ordered)) break;
          const item = document.createElement("li");
          this.renderInline(item, itemMatch[3].trim());
          list.appendChild(item);
          index += 1;
        }
        root.appendChild(list);
        continue;
      }
      const paragraphLines = [line.trim()];
      index += 1;
      while (index < lines.length && lines[index].trim() && !lines[index].startsWith("```") && !/^(#{1,3})\s+/.test(lines[index]) && !/^>\s?/.test(lines[index]) && !/^(\s*)([-*]|\d+\.)\s+/.test(lines[index])) {
        paragraphLines.push(lines[index++].trim());
      }
      const paragraph = document.createElement("p");
      this.renderInline(paragraph, paragraphLines.join("\n"));
      root.appendChild(paragraph);
    }
    return root;
  },

  renderInline(element, text) {
    const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
    let lastIndex = 0;
    for (const match of String(text).matchAll(pattern)) {
      if (match.index > lastIndex) element.append(document.createTextNode(text.slice(lastIndex, match.index)));
      const token = match[0];
      if (token.startsWith("`")) {
        const code = document.createElement("code"); code.textContent = token.slice(1, -1); element.appendChild(code);
      } else if (token.startsWith("**")) {
        const strong = document.createElement("strong"); strong.textContent = token.slice(2, -2); element.appendChild(strong);
      } else if (token.startsWith("*")) {
        const emphasis = document.createElement("em"); emphasis.textContent = token.slice(1, -1); element.appendChild(emphasis);
      } else {
        const linkMatch = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(token);
        const link = document.createElement("a");
        link.href = linkMatch[2]; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = linkMatch[1];
        element.appendChild(link);
      }
      lastIndex = match.index + token.length;
    }
    if (lastIndex < text.length) element.append(document.createTextNode(text.slice(lastIndex)));
  },
};
