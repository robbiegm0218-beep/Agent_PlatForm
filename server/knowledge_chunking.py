"""Deterministic, structure-aware chunking for P51-3."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Iterable

from server.knowledge_pipeline_contracts import ChunkPolicy, DocumentBlock, DocumentIR


STRUCTURED_CHUNK_POLICY_VERSION = "structure-token-v1"
CHUNK_PRESETS: dict[str, ChunkPolicy] = {
    "standard": ChunkPolicy(
        version=STRUCTURED_CHUNK_POLICY_VERSION,
        preset="standard",
        target_tokens=600,
        max_tokens=900,
        overlap_tokens=120,
    ),
    "long_document": ChunkPolicy(
        version=STRUCTURED_CHUNK_POLICY_VERSION,
        preset="long_document",
        target_tokens=900,
        max_tokens=1400,
        overlap_tokens=150,
    ),
    "table_dense": ChunkPolicy(
        version=STRUCTURED_CHUNK_POLICY_VERSION,
        preset="table_dense",
        target_tokens=420,
        max_tokens=700,
        overlap_tokens=60,
    ),
}


def policy_for_preset(preset: str) -> ChunkPolicy:
    try:
        return CHUNK_PRESETS[preset]
    except KeyError as exc:
        raise ValueError("切分预设无效") from exc


def estimate_tokens(text: str) -> int:
    """Stable local estimate: CJK chars + grouped latin/digits + punctuation."""
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    latin = sum(max(1, math.ceil(len(token) / 4)) for token in re.findall(r"[A-Za-z0-9_]+", text))
    punctuation = len(re.findall(r"[^\sA-Za-z0-9_\u3400-\u9fff]", text))
    return max(1, cjk + latin + math.ceil(punctuation / 2))


@dataclass(frozen=True)
class AtomicUnit:
    block_id: str
    block_type: str
    text: str
    section_path: tuple[str, ...]
    source_location: dict

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


@dataclass(frozen=True)
class StructuredChunk:
    position: int
    content: str
    block_ids: tuple[str, ...]
    section_path: tuple[str, ...]
    source_location: dict
    token_count: int
    overlap_tokens: int
    policy_version: str
    preset: str
    content_sha256: str


def _split_text(text: str, max_tokens: int) -> list[str]:
    candidates = [
        item.strip()
        for item in re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
        if item.strip()
    ]
    if not candidates:
        return []
    pieces: list[str] = []
    for candidate in candidates:
        if estimate_tokens(candidate) <= max_tokens:
            pieces.append(candidate)
            continue
        current = ""
        for character in candidate:
            proposed = current + character
            if current and estimate_tokens(proposed) > max_tokens:
                pieces.append(current)
                current = character
            else:
                current = proposed
        if current:
            pieces.append(current)
    return pieces


def _block_units(block: DocumentBlock, max_tokens: int) -> list[AtomicUnit]:
    if block.block_type in {"list", "table", "sheet"}:
        lines = [line.strip() for line in block.text.splitlines() if line.strip()]
        if estimate_tokens(block.text) <= max_tokens:
            parts = [block.text]
        else:
            parts = []
            current: list[str] = []
            for line in lines:
                if estimate_tokens(line) > max_tokens:
                    if current:
                        parts.append("\n".join(current))
                        current = []
                    parts.extend(_split_text(line, max_tokens))
                    continue
                proposed = "\n".join([*current, line])
                if current and estimate_tokens(proposed) > max_tokens:
                    parts.append("\n".join(current))
                    current = [line]
                else:
                    current.append(line)
            if current:
                parts.append("\n".join(current))
    else:
        parts = [block.text] if estimate_tokens(block.text) <= max_tokens else _split_text(block.text, max_tokens)
    return [
        AtomicUnit(
            block_id=block.block_id,
            block_type=block.block_type,
            text=part,
            section_path=block.section_path,
            source_location=block.source_location,
        )
        for part in parts if part.strip()
    ]


def _source_summary(units: Iterable[AtomicUnit]) -> dict:
    pages: list[int] = []
    sheets: list[str] = []
    ranges: list[str] = []
    lines: list[int] = []
    paragraphs: list[int] = []
    tables: list[int] = []
    images: list[str] = []
    for unit in units:
        source = unit.source_location
        if isinstance(source.get("page"), int):
            pages.append(source["page"])
        if source.get("sheet"):
            sheets.append(str(source["sheet"]))
        if source.get("cell_range"):
            ranges.append(str(source["cell_range"]))
        for key in ("line_start", "line_end"):
            if isinstance(source.get(key), int):
                lines.append(source[key])
        if isinstance(source.get("paragraph"), int):
            paragraphs.append(source["paragraph"])
        if isinstance(source.get("table"), int):
            tables.append(source["table"])
        if source.get("image"):
            images.append(str(source["image"]))
    result = {}
    if pages:
        result["pages"] = sorted(set(pages))
    if sheets:
        result["sheets"] = list(dict.fromkeys(sheets))
    if ranges:
        result["cell_ranges"] = list(dict.fromkeys(ranges))
    if lines:
        result["line_range"] = [min(lines), max(lines)]
    if paragraphs:
        result["paragraphs"] = sorted(set(paragraphs))
    if tables:
        result["tables"] = sorted(set(tables))
    if images:
        result["images"] = list(dict.fromkeys(images))
    return result


def _render_content(section_path: tuple[str, ...], units: list[AtomicUnit]) -> str:
    body = "\n\n".join(unit.text.strip() for unit in units if unit.text.strip())
    if not section_path:
        return body
    heading = " / ".join(section_path)
    if body.strip() == section_path[-1]:
        return body
    return f"章节：{heading}\n\n{body}"


def chunk_document_ir(
    document_ir: DocumentIR,
    preset: str = "standard",
    policy: ChunkPolicy | None = None,
) -> list[StructuredChunk]:
    policy = policy or policy_for_preset(preset)
    if policy.preset != preset:
        raise ValueError("切分策略与预设不匹配")
    units = [
        unit
        for block in document_ir.blocks
        for unit in _block_units(
            block,
            max(
                100,
                policy.max_tokens - (
                    estimate_tokens(f"章节：{' / '.join(block.section_path)}")
                    if block.section_path else 0
                ),
            ),
        )
    ]
    if not units:
        return []
    groups: list[tuple[list[AtomicUnit], int]] = []
    current: list[AtomicUnit] = []
    current_tokens = 0
    current_overlap = 0

    def flush() -> None:
        nonlocal current, current_tokens, current_overlap
        if not current:
            return
        groups.append((list(current), current_overlap))
        overlap: list[AtomicUnit] = []
        overlap_count = 0
        for unit in reversed(current):
            if unit.block_type not in {"paragraph", "image_ocr"}:
                continue
            if overlap_count + unit.tokens > policy.overlap_tokens:
                continue
            overlap.insert(0, unit)
            overlap_count += unit.tokens
        current = overlap
        current_tokens = overlap_count
        current_overlap = overlap_count

    for unit in units:
        section_changed = bool(current and current[-1].section_path != unit.section_path)
        section_overhead = estimate_tokens(f"章节：{' / '.join(unit.section_path)}") if unit.section_path else 0
        would_exceed_max = current_tokens + unit.tokens + section_overhead > policy.max_tokens
        target_reached = current_tokens + section_overhead >= policy.target_tokens
        if current and (section_changed or would_exceed_max or target_reached):
            flush()
            if current and current[-1].section_path != unit.section_path:
                current = []
                current_tokens = 0
                current_overlap = 0
        current.append(unit)
        current_tokens += unit.tokens
    flush()

    chunks = []
    for position, (group, overlap_tokens) in enumerate(groups):
        section_path = group[-1].section_path
        content = _render_content(section_path, group)
        chunks.append(StructuredChunk(
            position=position,
            content=content,
            block_ids=tuple(dict.fromkeys(unit.block_id for unit in group)),
            section_path=section_path,
            source_location=_source_summary(group),
            token_count=estimate_tokens(content),
            overlap_tokens=overlap_tokens,
            policy_version=policy.version,
            preset=policy.preset,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        ))
    return chunks


def persisted_chunk_rows(
    document_id: str,
    chunks: Iterable[StructuredChunk],
    *,
    chunk_version: int,
    active: bool,
    created_at: int,
) -> list[dict]:
    rows = []
    for chunk in chunks:
        stable = json.dumps(
            [document_id, chunk_version, chunk.position, chunk.content_sha256],
            separators=(",", ":"),
        )
        rows.append({
            "id": "chunk_" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24],
            "document_id": document_id,
            "position": chunk.position,
            "content": chunk.content,
            "chunk_version": chunk_version,
            "active": 1 if active else 0,
            "block_ids_json": json.dumps(list(chunk.block_ids), ensure_ascii=False),
            "section_path_json": json.dumps(list(chunk.section_path), ensure_ascii=False),
            "source_location_json": json.dumps(chunk.source_location, ensure_ascii=False, sort_keys=True),
            "token_count": chunk.token_count,
            "overlap_tokens": chunk.overlap_tokens,
            "policy_version": chunk.policy_version,
            "preset": chunk.preset,
            "content_sha256": chunk.content_sha256,
            "created_at": created_at,
        })
    return rows
