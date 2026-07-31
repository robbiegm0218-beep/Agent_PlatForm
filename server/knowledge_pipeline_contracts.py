"""Versioned contracts for the observable knowledge-processing pipeline.

P51-0 deliberately keeps these contracts outside the production upload path.
Later P51 phases may persist them only through additive schema migrations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DOCUMENT_IR_SCHEMA_VERSION = 1
DOCUMENT_BLOCK_TYPES = frozenset({
    "heading",
    "paragraph",
    "list",
    "table",
    "sheet",
    "image_ocr",
})
CHUNK_POLICY_PRESETS = frozenset({"standard", "long_document", "table_dense"})
LEXICAL_BACKENDS = frozenset({"python_lexical_v1", "sqlite_fts5"})
HYBRID_METHODS = frozenset({"lexical_only", "rrf", "weighted"})


def _bounded_integer(name: str, value: int, minimum: int, maximum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} 必须为整数")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间")


@dataclass(frozen=True)
class DocumentBlock:
    block_id: str
    block_type: str
    ordinal: int
    text: str
    section_path: tuple[str, ...] = ()
    source_location: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.block_id.strip():
            raise ValueError("结构块 ID 不能为空")
        if self.block_type not in DOCUMENT_BLOCK_TYPES:
            raise ValueError(f"不支持的结构块类型：{self.block_type}")
        _bounded_integer("结构块顺序", self.ordinal, 0, 10_000_000)
        if not isinstance(self.text, str):
            raise ValueError("结构块正文必须为字符串")
        if not all(isinstance(item, str) and item.strip() for item in self.section_path):
            raise ValueError("章节路径必须由非空字符串组成")


@dataclass(frozen=True)
class DocumentIR:
    document_id: str
    source_mime: str
    source_sha256: str
    parser_id: str
    parser_version: str
    blocks: tuple[DocumentBlock, ...]
    schema_version: int = DOCUMENT_IR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != DOCUMENT_IR_SCHEMA_VERSION:
            raise ValueError("Document IR schema 版本不受支持")
        for name, value in (
            ("文档 ID", self.document_id),
            ("来源 MIME", self.source_mime),
            ("解析器 ID", self.parser_id),
            ("解析器版本", self.parser_version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 不能为空")
        if len(self.source_sha256) != 64 or any(character not in "0123456789abcdef" for character in self.source_sha256):
            raise ValueError("来源哈希必须是小写 SHA-256")
        ordinals = [block.ordinal for block in self.blocks]
        if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
            raise ValueError("结构块顺序必须唯一且递增")
        if len({block.block_id for block in self.blocks}) != len(self.blocks):
            raise ValueError("结构块 ID 不能重复")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChunkPolicy:
    version: str = "fixed-char-v1"
    preset: str = "standard"
    target_tokens: int = 600
    max_tokens: int = 900
    overlap_tokens: int = 120
    preserve_headings: bool = True
    preserve_tables: bool = True

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("切分策略版本不能为空")
        if self.preset not in CHUNK_POLICY_PRESETS:
            raise ValueError(f"不支持的切分预设：{self.preset}")
        _bounded_integer("目标 Token 数", self.target_tokens, 64, 4000)
        _bounded_integer("最大 Token 数", self.max_tokens, 100, 8000)
        _bounded_integer("重叠 Token 数", self.overlap_tokens, 0, 1000)
        if self.target_tokens > self.max_tokens:
            raise ValueError("目标 Token 数不能超过最大 Token 数")
        if self.overlap_tokens >= self.target_tokens:
            raise ValueError("重叠 Token 数必须小于目标 Token 数")


@dataclass(frozen=True)
class IndexPolicy:
    version: str = "lexical-retrieval-v1"
    lexical_backend: str = "python_lexical_v1"
    embedding_enabled: bool = False
    embedding_model: str = ""
    vector_dimensions: int = 0
    hybrid_method: str = "lexical_only"
    lexical_weight: float = 1.0
    vector_weight: float = 0.0
    candidate_limit: int = 4
    rerank_limit: int = 0

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("索引策略版本不能为空")
        if self.lexical_backend not in LEXICAL_BACKENDS:
            raise ValueError(f"不支持的词法索引：{self.lexical_backend}")
        if self.hybrid_method not in HYBRID_METHODS:
            raise ValueError(f"不支持的混合策略：{self.hybrid_method}")
        _bounded_integer("候选数量", self.candidate_limit, 1, 100)
        _bounded_integer("重排数量", self.rerank_limit, 0, 100)
        _bounded_integer("向量维度", self.vector_dimensions, 0, 65_536)
        for name, value in (("词法权重", self.lexical_weight), ("向量权重", self.vector_weight)):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0 or value > 1:
                raise ValueError(f"{name} 必须在 0 到 1 之间")
        if self.embedding_enabled:
            if not self.embedding_model.strip() or self.vector_dimensions <= 0:
                raise ValueError("启用向量后必须指定模型和向量维度")
        elif self.embedding_model or self.vector_dimensions:
            raise ValueError("未启用向量时不能设置模型或向量维度")
        if self.hybrid_method == "lexical_only" and (self.embedding_enabled or self.vector_weight != 0):
            raise ValueError("纯词法策略不能启用向量权重")
        if self.hybrid_method != "lexical_only" and not self.embedding_enabled:
            raise ValueError("混合检索必须启用向量")
        if self.hybrid_method == "weighted" and abs(self.lexical_weight + self.vector_weight - 1.0) > 1e-9:
            raise ValueError("加权融合的词法与向量权重之和必须为 1")


def contract_snapshot() -> dict[str, Any]:
    """Return a content-free snapshot suitable for baseline reports."""
    return {
        "document_ir_schema_version": DOCUMENT_IR_SCHEMA_VERSION,
        "document_block_types": sorted(DOCUMENT_BLOCK_TYPES),
        "chunk_policy_presets": sorted(CHUNK_POLICY_PRESETS),
        "lexical_backends": sorted(LEXICAL_BACKENDS),
        "hybrid_methods": sorted(HYBRID_METHODS),
        "default_chunk_policy": asdict(ChunkPolicy()),
        "default_index_policy": asdict(IndexPolicy()),
    }
