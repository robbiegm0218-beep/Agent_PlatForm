"""Safe local artifact rendering and file operations."""
from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import base64
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable


ARTIFACT_MIME_TYPES = {
    "markdown": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json; charset=utf-8",
}
PREVIEWABLE_ARTIFACT_KINDS = {"markdown", "html", "xlsx", "json"}

ALLOWED_HTML_TAGS = {
    "article", "aside", "blockquote", "br", "caption", "code", "dd", "details",
    "div", "dl", "dt", "em", "figcaption", "figure", "footer", "h1", "h2",
    "h3", "h4", "h5", "h6", "header", "hr", "i", "img", "li", "main", "nav",
    "ol", "p", "pre", "section", "small", "span", "strong", "summary", "table",
    "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
}
VOID_HTML_TAGS = {"br", "hr", "img"}
DROP_CONTENT_TAGS = {"script", "iframe", "object", "embed", "svg", "math", "template"}
SAFE_GLOBAL_ATTRIBUTES = {"class", "id", "title", "role", "lang", "dir"}
SAFE_TABLE_ATTRIBUTES = {"colspan", "rowspan", "scope"}
UNSAFE_CSS = re.compile(
    r"(?is)(?:@import|url\s*\(|expression\s*\(|javascript\s*:|vbscript\s*:|behavior\s*:|-moz-binding|position\s*:\s*(?:fixed|sticky))"
)


def extract_html_document(value: str) -> str | None:
    raw = str(value or "")

    class TextCollector(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    collector = TextCollector()
    collector.feed(raw)
    flattened = html.unescape("\n".join(collector.parts))
    match = re.search(r"(?is)(?:<!doctype\s+html[^>]*>\s*)?<html\b[\s\S]*?</html\s*>", flattened)
    if match:
        return match.group(0)
    match = re.search(r"(?is)(?:<!doctype\s+html[^>]*>\s*)?<html\b[\s\S]*?</html\s*>", raw)
    return match.group(0) if match else None


def sanitize_css(css: str) -> str:
    value = re.sub(r"/\*[\s\S]*?\*/", "", str(css or ""))[:100_000]
    value = re.sub(r"(?is)@import[^;]*;?", "", value)
    value = re.sub(r"(?is)url\s*\([^)]*\)", "none", value)
    value = re.sub(r"(?is)position\s*:\s*(?:fixed|sticky)", "position: relative", value)
    value = re.sub(r"(?i)(?<![-\w])(?:html|body)(?![-\w])", ".preview-document", value)
    return "" if UNSAFE_CSS.search(value) else value


def sanitize_style_attribute(value: str) -> str:
    css = sanitize_css(value)
    return css[:2_000] if "{" not in css and "}" not in css else ""


class SafeHtmlDocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.body: list[str] = []
        self.styles: list[str] = []
        self.title = "HTML 页面"
        self._drop_depth = 0
        self._in_style = False
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            self._drop_depth += 1
            return
        if self._drop_depth:
            return
        if tag == "style":
            self._in_style = True
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in {"html", "head", "body", "meta", "link", "base", "form", "input", "button", "select", "textarea", "option"}:
            return
        if tag not in ALLOWED_HTML_TAGS:
            return
        safe_attrs: list[str] = []
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            value = str(raw_value or "")
            if name.startswith("on"):
                continue
            if name == "style":
                value = sanitize_style_attribute(value)
                if not value:
                    continue
            elif name in SAFE_TABLE_ATTRIBUTES and tag in {"table", "thead", "tbody", "tfoot", "tr", "th", "td"}:
                if name in {"colspan", "rowspan"} and not value.isdigit():
                    continue
            elif name == "src" and tag == "img":
                if not re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=\s]+", value):
                    continue
            elif name in {"alt", "width", "height"} and tag == "img":
                pass
            elif name.startswith("aria-") or name.startswith("data-") or name in SAFE_GLOBAL_ATTRIBUTES:
                pass
            else:
                continue
            safe_attrs.append(f' {name}="{html.escape(value, quote=True)}"')
        self.body.append(f"<{tag}{''.join(safe_attrs)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            self._drop_depth = max(0, self._drop_depth - 1)
            return
        if self._drop_depth:
            return
        if tag == "style":
            self._in_style = False
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in ALLOWED_HTML_TAGS and tag not in VOID_HTML_TAGS:
            self.body.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._drop_depth:
            return
        if self._in_style:
            self.styles.append(data)
            return
        if self._in_title:
            self.title = data.strip()[:160] or self.title
            return
        self.body.append(html.escape(data))


def sanitize_html_document(value: str) -> str:
    parser = SafeHtmlDocumentParser()
    parser.feed(str(value or ""))
    safe_title = html.escape(parser.title)
    safe_css = sanitize_css("\n".join(parser.styles))
    body = "".join(parser.body).strip()
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="agent-preview-mode" content="html-document">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'">
  <title>{safe_title}</title>
  <style>{safe_css}</style>
</head>
<body>
  <div class="preview-document">{body}</div>
</body>
</html>
"""


def artifact_metadata(kind: str) -> tuple[str, str]:
    extensions = {"markdown": ".md", "html": ".html", "xlsx": ".xlsx", "json": ".json"}
    if kind not in extensions:
        raise ValueError("不支持的文件类型")
    return extensions[kind], ARTIFACT_MIME_TYPES[kind]


def public_artifact(row) -> dict:
    item = {key: row[key] for key in row.keys()}
    item.pop("storage_path", None)
    item["previewable"] = item.get("kind") in PREVIEWABLE_ARTIFACT_KINDS
    item["mime_type"] = item.get("mime_type") or ARTIFACT_MIME_TYPES.get(item.get("kind"), "application/octet-stream")
    item["status"] = item.get("status") or "ready"
    item["revision"] = int(item.get("revision") or 1)
    item["size_bytes"] = int(item.get("size_bytes") or 0)
    item["updated_at"] = int(item.get("updated_at") or item.get("created_at") or 0)
    return item


def resolve_artifact_path(storage_path: str, artifact_root: Path) -> Path:
    path = Path(storage_path)
    allowed_root = artifact_root.resolve()
    if not path.is_file() or not path.resolve().is_relative_to(allowed_root):
        raise FileNotFoundError("文件产物不可用")
    return path


def _render_blocks(markdown: str) -> str:
    lines = str(markdown or "").replace("\r\n", "\n").split("\n")
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{html.escape(' '.join(paragraph).strip())}</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            blocks.append("<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in list_items) + "</ul>")
            list_items.clear()

    for raw_line in lines:
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            flush_paragraph()
            flush_list()
            if in_code:
                blocks.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
                code_lines.clear()
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            flush_list()
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{html.escape(heading.group(2).strip())}</h{level}>")
            continue
        item = re.match(r"^[-*]\s+(.+)$", stripped)
        if item:
            flush_paragraph()
            list_items.append(item.group(1).strip())
            continue
        flush_list()
        paragraph.append(stripped)
    if in_code:
        blocks.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
    flush_paragraph()
    flush_list()
    return "\n".join(blocks)


def render_static_html(title: str, markdown: str) -> str:
    safe_title = html.escape((title or "Agent_Platform 输出").strip()[:160])
    body = _render_blocks(markdown)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src 'none'; form-action 'none'; base-uri 'none'; frame-src 'none'">
  <meta name="referrer" content="no-referrer">
  <title>{safe_title}</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #fafaf7; color: #252522; }}
    main {{ max-width: 820px; margin: 0 auto; padding: 48px 40px 72px; }}
    h1 {{ margin: 0 0 28px; font-size: 32px; line-height: 1.2; }}
    h2, h3, h4 {{ margin: 30px 0 12px; line-height: 1.3; }}
    p, li {{ font-size: 16px; line-height: 1.75; }}
    ul {{ padding-left: 24px; }}
    pre {{ overflow: auto; padding: 16px; border: 1px solid #deded7; border-radius: 10px; background: #f1f1ec; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 14px; }}
    @media (max-width: 640px) {{ main {{ padding: 28px 20px 48px; }} h1 {{ font-size: 27px; }} }}
  </style>
</head>
<body>
  <main>
    <h1>{safe_title}</h1>
    {body}
  </main>
</body>
</html>
"""

def render_image_preview(title: str, mime_type: str, content: bytes) -> str:
    safe_title = html.escape((title or "图片预览").strip()[:160])
    if mime_type not in {"image/png", "image/jpeg", "image/webp", "image/tiff"}:
        raise ValueError("该图片格式不支持预览")
    encoded = base64.b64encode(content).decode("ascii")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'">
  <title>{safe_title}</title>
</head>
<body>
  <main class="image-document">
    <h1>{safe_title}</h1>
    <img src="data:{mime_type};base64,{encoded}" alt="{safe_title}">
  </main>
</body>
</html>
"""


def write_artifact_file(
    *,
    artifact_root: Path,
    user_id: str,
    artifact_id: str,
    kind: str,
    title: str,
    answer: str,
    node_binary: str,
    xlsx_script: Path,
    root_dir: Path,
) -> dict:
    extension, mime_type = artifact_metadata(kind)
    filename = f"{artifact_id}{extension}"
    storage_dir = artifact_root / user_id
    storage_dir.mkdir(parents=True, exist_ok=True)
    path = (storage_dir / filename).resolve()
    if storage_dir.resolve() not in path.parents or path.exists():
        raise ValueError("文件产物路径无效")
    if kind == "markdown":
        path.write_text(f"# {title}\n\n{answer.strip()}\n", encoding="utf-8")
    elif kind == "html":
        html_document = extract_html_document(answer)
        path.write_text(
            sanitize_html_document(html_document) if html_document else render_static_html(title, answer),
            encoding="utf-8",
        )
    elif kind == "xlsx":
        result = subprocess.run(
            [node_binary, str(xlsx_script), str(path), title, answer],
            cwd=str(root_dir), text=True, capture_output=True, timeout=30,
        )
        if result.returncode != 0 or not path.exists():
            raise RuntimeError((result.stderr or result.stdout or "Excel 生成器未返回文件").strip()[:500])
    content = path.read_bytes()
    return {
        "filename": filename,
        "path": path,
        "mime_type": mime_type,
        "size_bytes": len(content),
        "content_sha256": hashlib.sha256(content).hexdigest(),
    }


def preview_content(
    row,
    artifact_root: Path,
    *,
    xlsx_text_extractor: Callable[[bytes], str] | None = None,
) -> tuple[bytes, str]:
    kind = str(row["kind"])
    if kind not in PREVIEWABLE_ARTIFACT_KINDS:
        raise ValueError("该文件类型不支持预览")
    path = resolve_artifact_path(str(row["storage_path"]), artifact_root)
    content = path.read_bytes()
    expected_hash = str(row["content_sha256"] or "") if "content_sha256" in row.keys() else ""
    if expected_hash and hashlib.sha256(content).hexdigest() != expected_hash:
        raise ValueError("文件产物完整性校验失败")
    if kind == "html":
        decoded = content.decode("utf-8")
        html_document = extract_html_document(decoded)
        if html_document:
            return sanitize_html_document(html_document).encode("utf-8"), ARTIFACT_MIME_TYPES["html"]
        return content, ARTIFACT_MIME_TYPES["html"]
    if kind == "json":
        try:
            formatted = json.dumps(json.loads(content.decode("utf-8")), ensure_ascii=False, indent=2)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON 文件内容无效") from exc
        title = str(row["filename"]).removesuffix(".json")
        return render_static_html(title, f"```json\n{formatted}\n```").encode("utf-8"), ARTIFACT_MIME_TYPES["html"]
    if kind == "xlsx":
        if not xlsx_text_extractor:
            raise ValueError("当前环境暂不能预览 Excel 文件")
        title = str(row["filename"]).removesuffix(".xlsx")
        extracted = xlsx_text_extractor(content)
        return render_static_html(title, f"```\n{extracted}\n```").encode("utf-8"), ARTIFACT_MIME_TYPES["html"]
    markdown = content.decode("utf-8")
    title = str(row["filename"]).removesuffix(".md")
    return render_static_html(title, markdown).encode("utf-8"), ARTIFACT_MIME_TYPES["html"]
