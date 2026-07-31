"""Structured, deterministic parsers for P51-2 knowledge Document IR."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import asdict
from pathlib import Path

from server.knowledge_pipeline_contracts import DocumentBlock, DocumentIR


PARSER_PROFILE_VERSION = "document-ir-v1"


def _block_id(
    document_id: str,
    ordinal: int,
    block_type: str,
    text: str,
    source_location: dict,
) -> str:
    payload = json.dumps(
        [document_id, ordinal, block_type, text, source_location],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "block_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _block(
    document_id: str,
    blocks: list[DocumentBlock],
    block_type: str,
    text: str,
    *,
    section_path: tuple[str, ...] = (),
    source_location: dict | None = None,
    metadata: dict | None = None,
) -> None:
    normalized = str(text).strip()
    if not normalized:
        return
    ordinal = len(blocks)
    source = source_location or {}
    blocks.append(DocumentBlock(
        block_id=_block_id(document_id, ordinal, block_type, normalized, source),
        block_type=block_type,
        ordinal=ordinal,
        text=normalized,
        section_path=section_path,
        source_location=source,
        metadata=metadata or {},
    ))


def _markdown_blocks(document_id: str, text: str) -> list[DocumentBlock]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    blocks: list[DocumentBlock] = []
    headings: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        line_number = index + 1
        if not stripped:
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", stripped)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            headings = headings[:level - 1]
            headings.append(title)
            _block(
                document_id, blocks, "heading", title,
                section_path=tuple(headings),
                source_location={"line_start": line_number, "line_end": line_number},
                metadata={"level": level},
            )
            index += 1
            continue
        if re.match(r"^(?:[-*+]|\d+[.)])\s+", stripped):
            items = []
            start = line_number
            while index < len(lines):
                candidate = lines[index].strip()
                matched = re.match(r"^(?:[-*+]|\d+[.)])\s+(.+)$", candidate)
                if not matched:
                    break
                items.append(matched.group(1).strip())
                index += 1
            _block(
                document_id, blocks, "list", "\n".join(items),
                section_path=tuple(headings),
                source_location={"line_start": start, "line_end": index},
                metadata={"item_count": len(items)},
            )
            continue
        if "|" in stripped and index + 1 < len(lines):
            separator = lines[index + 1].strip()
            if re.match(r"^\|?\s*:?-{3,}", separator):
                table_lines = [stripped, separator]
                start = line_number
                index += 2
                while index < len(lines) and "|" in lines[index] and lines[index].strip():
                    table_lines.append(lines[index].strip())
                    index += 1
                _block(
                    document_id, blocks, "table", "\n".join(table_lines),
                    section_path=tuple(headings),
                    source_location={"line_start": start, "line_end": start + len(table_lines) - 1},
                    metadata={"row_count": max(0, len(table_lines) - 1)},
                )
                continue
        paragraph = [stripped]
        start = line_number
        index += 1
        while index < len(lines):
            candidate = lines[index].strip()
            if not candidate or re.match(r"^(#{1,6})\s+", candidate) or re.match(r"^(?:[-*+]|\d+[.)])\s+", candidate):
                break
            if "|" in candidate and index + 1 < len(lines) and re.match(r"^\|?\s*:?-{3,}", lines[index + 1].strip()):
                break
            paragraph.append(candidate)
            index += 1
        _block(
            document_id, blocks, "paragraph", "\n".join(paragraph),
            section_path=tuple(headings),
            source_location={"line_start": start, "line_end": start + len(paragraph) - 1},
        )
    return blocks


def _plain_text_blocks(document_id: str, text: str) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []
    cursor = 1
    for paragraph in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        stripped = paragraph.strip()
        if not stripped:
            cursor += paragraph.count("\n") + 1
            continue
        line_count = stripped.count("\n") + 1
        _block(
            document_id, blocks, "paragraph", stripped,
            source_location={"line_start": cursor, "line_end": cursor + line_count - 1},
        )
        cursor += paragraph.count("\n") + 2
    return blocks


def _docx_blocks(document_id: str, raw: bytes) -> list[DocumentBlock]:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        raise ValueError("当前环境未安装 DOCX 解析组件") from exc
    document = Document(io.BytesIO(raw))
    blocks: list[DocumentBlock] = []
    headings: list[str] = []
    paragraph_number = 0
    table_number = 0
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            paragraph_number += 1
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style_name = str(paragraph.style.name if paragraph.style else "")
            heading_match = re.search(r"heading\s*([1-6])", style_name, re.IGNORECASE)
            if heading_match:
                level = int(heading_match.group(1))
                headings = headings[:level - 1]
                headings.append(text)
                _block(
                    document_id, blocks, "heading", text,
                    section_path=tuple(headings),
                    source_location={"paragraph": paragraph_number},
                    metadata={"level": level, "style": style_name},
                )
            elif re.search(r"(?:list|bullet|number)", style_name, re.IGNORECASE):
                _block(
                    document_id, blocks, "list", text,
                    section_path=tuple(headings),
                    source_location={"paragraph": paragraph_number},
                    metadata={"item_count": 1, "style": style_name},
                )
            else:
                _block(
                    document_id, blocks, "paragraph", text,
                    section_path=tuple(headings),
                    source_location={"paragraph": paragraph_number},
                    metadata={"style": style_name},
                )
        elif child.tag.endswith("}tbl"):
            table_number += 1
            table = Table(child, document)
            rows = []
            for row in table.rows:
                values = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                if any(values):
                    rows.append(values)
            if rows:
                markdown = "\n".join("| " + " | ".join(values) + " |" for values in rows)
                _block(
                    document_id, blocks, "table", markdown,
                    section_path=tuple(headings),
                    source_location={"table": table_number},
                    metadata={"row_count": len(rows), "column_count": max(map(len, rows))},
                )
    return blocks


def _pdf_blocks(document_id: str, extracted_text: str) -> list[DocumentBlock]:
    blocks: list[DocumentBlock] = []
    markers = list(re.finditer(r"【PDF 第\s*(\d+)\s*页】\s*", extracted_text))
    if not markers:
        return _plain_text_blocks(document_id, extracted_text)
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(extracted_text)
        content = extracted_text[marker.end():end].strip()
        page = int(marker.group(1))
        _block(
            document_id, blocks, "paragraph", content,
            section_path=(f"第 {page} 页",),
            source_location={"page": page},
        )
    return blocks


def _xlsx_shared_strings(archive: zipfile.ZipFile, namespace: str) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.itertext()).strip() for node in root.findall(f"{namespace}si")]


def _xlsx_blocks(document_id: str, raw: bytes) -> list[DocumentBlock]:
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel_namespace = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    package_rel_namespace = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    blocks: list[DocumentBlock] = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            shared = _xlsx_shared_strings(archive, namespace)
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            targets = {
                relation.attrib.get("Id"): relation.attrib.get("Target", "")
                for relation in relationships.findall(f"{package_rel_namespace}Relationship")
            }
            for sheet in workbook.findall(f"{namespace}sheets/{namespace}sheet"):
                sheet_name = sheet.attrib.get("name", "未命名")
                target = targets.get(sheet.attrib.get(f"{rel_namespace}id"), "")
                normalized_target = target.lstrip("/")
                path = normalized_target if normalized_target.startswith("xl/") else "xl/" + normalized_target
                if path not in archive.namelist():
                    continue
                root = ET.fromstring(archive.read(path))
                rows: list[str] = []
                first_cell = ""
                last_cell = ""
                for row in root.findall(f".//{namespace}sheetData/{namespace}row"):
                    values = []
                    row_cells = row.findall(f"{namespace}c")
                    for cell in row_cells:
                        reference = cell.attrib.get("r", "")
                        first_cell = first_cell or reference
                        last_cell = reference or last_cell
                        value = cell.findtext(f"{namespace}v", default="")
                        if cell.attrib.get("t") == "s" and value.isdigit() and int(value) < len(shared):
                            value = shared[int(value)]
                        elif cell.attrib.get("t") == "inlineStr":
                            inline = cell.find(f"{namespace}is")
                            value = "".join(inline.itertext()) if inline is not None else ""
                        values.append(value.strip())
                    if any(values):
                        rows.append(" | ".join(values))
                if rows:
                    cell_range = f"{first_cell}:{last_cell}" if first_cell and last_cell else ""
                    _block(
                        document_id, blocks, "sheet", "\n".join(rows),
                        section_path=(sheet_name,),
                        source_location={"sheet": sheet_name, "cell_range": cell_range},
                        metadata={"row_count": len(rows)},
                    )
    except (KeyError, ET.ParseError, zipfile.BadZipFile) as exc:
        raise ValueError("无法读取 Excel 结构") from exc
    return blocks


def build_document_ir(
    *,
    document_id: str,
    filename: str,
    raw: bytes,
    extracted_text: str,
    source_mime: str,
    source_sha256: str,
    parser_version: str,
) -> DocumentIR:
    suffix = Path(filename).suffix.lower()
    if suffix == ".md":
        blocks = _markdown_blocks(document_id, extracted_text)
    elif suffix == ".txt":
        blocks = _plain_text_blocks(document_id, extracted_text)
    elif suffix == ".docx":
        blocks = _docx_blocks(document_id, raw)
    elif suffix == ".pdf":
        blocks = _pdf_blocks(document_id, extracted_text)
    elif suffix == ".xlsx":
        blocks = _xlsx_blocks(document_id, raw)
    elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}:
        blocks = []
        _block(
            document_id, blocks, "image_ocr", extracted_text,
            source_location={"image": Path(filename).name},
            metadata={"ocr_engine": "tesseract-local"},
        )
    else:
        blocks = _plain_text_blocks(document_id, extracted_text)
    if not blocks and extracted_text.strip():
        blocks = _plain_text_blocks(document_id, extracted_text)
    return DocumentIR(
        document_id=document_id,
        source_mime=source_mime,
        source_sha256=source_sha256,
        parser_id=f"{suffix.lstrip('.') or 'plain'}-structured",
        parser_version=f"{parser_version}+{PARSER_PROFILE_VERSION}",
        blocks=tuple(blocks),
    )


def document_ir_to_markdown(document_ir: DocumentIR) -> str:
    output: list[str] = []
    for block in document_ir.blocks:
        if block.block_type == "heading":
            level = min(max(int(block.metadata.get("level", 2)), 1), 6)
            output.append(f"{'#' * level} {block.text}")
        elif block.block_type == "list":
            output.append("\n".join(f"- {item}" for item in block.text.splitlines() if item.strip()))
        elif block.block_type == "table":
            rows = block.text.splitlines()
            if rows and not (len(rows) > 1 and re.match(r"^\|?\s*:?-{3,}", rows[1].strip())):
                columns = max(1, rows[0].count("|") - 1)
                rows.insert(1, "| " + " | ".join("---" for _ in range(columns)) + " |")
            output.append("\n".join(rows))
        elif block.block_type == "sheet":
            sheet = str(block.source_location.get("sheet", "工作表"))
            output.append(f"## 工作表：{sheet}\n\n```\n{block.text}\n```")
        elif block.block_type == "image_ocr":
            output.append(f"## 图片 OCR\n\n{block.text}")
        else:
            output.append(block.text)
    return "\n\n".join(item for item in output if item.strip()).strip()


def persisted_block_rows(document_ir: DocumentIR, ingestion_run_id: str, created_at: int) -> list[dict]:
    rows = []
    for block in document_ir.blocks:
        rows.append({
            **asdict(block),
            "document_id": document_ir.document_id,
            "ingestion_run_id": ingestion_run_id,
            "section_path_json": json.dumps(list(block.section_path), ensure_ascii=False),
            "source_location_json": json.dumps(block.source_location, ensure_ascii=False, sort_keys=True),
            "metadata_json": json.dumps(block.metadata, ensure_ascii=False, sort_keys=True),
            "char_count": len(block.text),
            "content_sha256": hashlib.sha256(block.text.encode("utf-8")).hexdigest(),
            "parser_version": document_ir.parser_version,
            "created_at": created_at,
        })
    return rows
