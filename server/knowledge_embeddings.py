"""Versioned, failure-isolated embedding jobs for knowledge chunks."""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol


class EmbeddingError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "disabled"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    dimensions: int = 0
    timeout_seconds: float = 30.0

    @property
    def enabled(self) -> bool:
        return self.provider != "disabled"

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "provider": self.provider,
                "base_url": self.base_url.rstrip("/"),
                "model": self.model,
                "dimensions": self.dimensions,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def version(self) -> str:
        return f"{self.provider}:{self.model}:{self.dimensions}:{self.fingerprint[:12]}"

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        provider = os.environ.get("KNOWLEDGE_EMBEDDING_PROVIDER", "disabled").strip().lower()
        if provider in {"", "none", "off"}:
            provider = "disabled"
        config = cls(
            provider=provider,
            base_url=os.environ.get("KNOWLEDGE_EMBEDDING_BASE_URL", "").strip(),
            api_key=os.environ.get("KNOWLEDGE_EMBEDDING_API_KEY", "").strip(),
            model=os.environ.get("KNOWLEDGE_EMBEDDING_MODEL", "").strip(),
            dimensions=int(os.environ.get("KNOWLEDGE_EMBEDDING_DIMENSIONS", "0") or 0),
            timeout_seconds=float(os.environ.get("KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS", "30") or 30),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.provider not in {"disabled", "openai_compatible"}:
            raise ValueError("KNOWLEDGE_EMBEDDING_PROVIDER 仅支持 disabled 或 openai_compatible")
        if not self.enabled:
            return
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("向量服务地址必须是 http(s) URL")
        if not self.api_key or not self.model:
            raise ValueError("启用向量服务时必须配置 API Key 和模型")
        if self.dimensions <= 0 or self.dimensions > 65536:
            raise ValueError("向量维度必须在 1 到 65536 之间")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 300:
            raise ValueError("向量请求超时必须在 0 到 300 秒之间")


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatibleEmbeddingProvider:
    def __init__(self, config: EmbeddingConfig):
        self.config = config

    def embed(self, texts: list[str]) -> list[list[float]]:
        body = json.dumps(
            {"model": self.config.model, "input": texts, "dimensions": self.config.dimensions}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.base_url.rstrip('/')}/embeddings",
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise EmbeddingError(f"向量服务请求失败：{exc}") from exc
        data = payload.get("data", [])
        if len(data) != len(texts):
            raise EmbeddingError("向量服务返回数量与输入不一致")
        ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
        return [item.get("embedding", []) for item in ordered]


def pack_vector(vector: list[float], dimensions: int) -> bytes:
    if len(vector) != dimensions:
        raise EmbeddingError(f"向量维度不匹配：期望 {dimensions}，实际 {len(vector)}")
    values = [float(value) for value in vector]
    if not values or any(not math.isfinite(value) for value in values):
        raise EmbeddingError("向量包含无效数值")
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        raise EmbeddingError("向量范数必须大于 0")
    normalized = [value / norm for value in values]
    return struct.pack(f"<{dimensions}f", *normalized)


def normalize_vector(vector: list[float], dimensions: int) -> list[float]:
    return list(struct.unpack(f"<{dimensions}f", pack_vector(vector, dimensions)))


def unpack_vector(payload: bytes, dimensions: int) -> list[float]:
    if not payload or len(payload) != dimensions * 4:
        raise EmbeddingError("持久化向量长度与维度不匹配")
    values = list(struct.unpack(f"<{dimensions}f", payload))
    if any(not math.isfinite(value) for value in values):
        raise EmbeddingError("持久化向量包含无效数值")
    return values


class KnowledgeEmbeddingService:
    def __init__(
        self,
        db_factory,
        now: Callable[[], int],
        new_id: Callable[[str], str],
        config: EmbeddingConfig,
        provider: EmbeddingProvider | None = None,
    ):
        self.db_factory = db_factory
        self.now = now
        self.new_id = new_id
        self.config = config
        self.provider = provider or (
            OpenAICompatibleEmbeddingProvider(config) if config.enabled else None
        )

    def sync_model(self) -> str:
        if not self.config.enabled:
            return ""
        timestamp = self.now()
        with self.db_factory() as conn:
            conn.execute(
                "UPDATE knowledge_embedding_models SET status = 'retired' WHERE version != ? AND status = 'active'",
                (self.config.version,),
            )
            conn.execute(
                """INSERT INTO knowledge_embedding_models
                   (version, provider, model, dimensions, config_fingerprint,
                    status, created_at, activated_at)
                   VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
                   ON CONFLICT(version) DO UPDATE SET status = 'active',
                       activated_at = CASE WHEN activated_at = 0 THEN excluded.activated_at ELSE activated_at END""",
                (
                    self.config.version, self.config.provider, self.config.model,
                    self.config.dimensions, self.config.fingerprint, timestamp, timestamp,
                ),
            )
        return self.config.version

    def enqueue_document(self, document_id: str, requested_by_user_id: str = "") -> dict:
        if not self.config.enabled:
            return {"status": "disabled", "job_id": "", "model_version": ""}
        model_version = self.sync_model()
        timestamp = self.now()
        with self.db_factory() as conn:
            document = conn.execute(
                "SELECT active_chunk_version FROM knowledge_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            if not document:
                raise ValueError("知识库文件不存在")
            chunk_version = int(document[0])
            existing = conn.execute(
                """SELECT id, status FROM knowledge_embedding_jobs
                   WHERE document_id = ? AND chunk_version = ? AND model_version = ?
                     AND status IN ('queued', 'running')""",
                (document_id, chunk_version, model_version),
            ).fetchone()
            if existing:
                return {"status": existing["status"], "job_id": existing["id"], "model_version": model_version}
            total = int(conn.execute(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE document_id = ? AND chunk_version = ?",
                (document_id, chunk_version),
            ).fetchone()[0])
            job_id = self.new_id("embedding_job")
            conn.execute(
                """INSERT INTO knowledge_embedding_jobs
                   (id, document_id, chunk_version, model_version, requested_by_user_id,
                    status, total_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)""",
                (job_id, document_id, chunk_version, model_version, requested_by_user_id, total, timestamp, timestamp),
            )
            conn.execute(
                """UPDATE knowledge_documents SET embedding_status = 'queued',
                   embedding_updated_at = ? WHERE id = ?""",
                (timestamp, document_id),
            )
        return {"status": "queued", "job_id": job_id, "model_version": model_version}

    def process_next(self) -> dict | None:
        if not self.config.enabled or not self.provider:
            return None
        timestamp = self.now()
        with self.db_factory() as conn:
            job = conn.execute(
                """SELECT * FROM knowledge_embedding_jobs
                   WHERE status = 'queued' ORDER BY created_at, id LIMIT 1"""
            ).fetchone()
            if not job:
                return None
            job = dict(job)
            claimed = conn.execute(
                "UPDATE knowledge_embedding_jobs SET status = 'running', started_at = ?, updated_at = ? WHERE id = ? AND status = 'queued'",
                (timestamp, timestamp, job["id"]),
            )
            if claimed.rowcount != 1:
                return None
            chunks = [dict(row) for row in conn.execute(
                """SELECT id, document_id, chunk_version, content, content_sha256
                   FROM knowledge_chunks WHERE document_id = ? AND chunk_version = ?
                   ORDER BY position""",
                (job["document_id"], job["chunk_version"]),
            ).fetchall()]
        reused = succeeded = failed = 0
        errors: list[str] = []
        for chunk in chunks:
            try:
                with self.db_factory() as conn:
                    reusable = conn.execute(
                        """SELECT vector_blob, dimensions FROM knowledge_chunk_embeddings
                           WHERE document_id = ? AND model_version = ? AND content_sha256 = ?
                             AND status = 'ready' AND vector_blob IS NOT NULL
                           ORDER BY updated_at DESC LIMIT 1""",
                        (chunk["document_id"], job["model_version"], chunk["content_sha256"]),
                    ).fetchone()
                if reusable:
                    vector_blob = reusable["vector_blob"]
                    reused += 1
                else:
                    vector_blob = pack_vector(
                        self.provider.embed([chunk["content"]])[0],
                        self.config.dimensions,
                    )
                with self.db_factory() as conn:
                    self._upsert_embedding(conn, job, chunk, "ready", vector_blob, "")
                succeeded += 1
            except Exception as exc:
                message = str(exc)[:500]
                errors.append(message)
                failed += 1
                with self.db_factory() as conn:
                    self._upsert_embedding(conn, job, chunk, "failed", None, message)
        completed_at = self.now()
        status = "ready" if chunks and failed == 0 else ("partial" if succeeded else "failed")
        with self.db_factory() as conn:
            conn.execute(
                """UPDATE knowledge_embedding_jobs SET status = ?, reused_count = ?,
                   succeeded_count = ?, failed_count = ?, error_message = ?,
                   completed_at = ?, updated_at = ? WHERE id = ?""",
                (status, reused, succeeded, failed, "; ".join(errors[:3]), completed_at, completed_at, job["id"]),
            )
            current = conn.execute(
                "SELECT active_chunk_version FROM knowledge_documents WHERE id = ?",
                (job["document_id"],),
            ).fetchone()
            if status == "ready" and current and int(current[0]) == int(job["chunk_version"]):
                conn.execute(
                    """UPDATE knowledge_documents
                       SET active_embedding_model_version = ?, embedding_status = 'ready',
                           embedding_updated_at = ? WHERE id = ?""",
                    (job["model_version"], completed_at, job["document_id"]),
                )
            else:
                conn.execute(
                    """UPDATE knowledge_documents SET embedding_status = ?,
                       embedding_updated_at = ? WHERE id = ?""",
                    (status, completed_at, job["document_id"]),
                )
        return {
            "job_id": job["id"], "document_id": job["document_id"], "status": status,
            "total_count": len(chunks), "reused_count": reused,
            "succeeded_count": succeeded, "failed_count": failed,
        }

    def embed_query(self, query: str) -> tuple[list[float], str] | None:
        if not self.config.enabled or not self.provider or not query.strip():
            return None
        vector = self.provider.embed([query.strip()])[0]
        return normalize_vector(vector, self.config.dimensions), self.config.version

    def _upsert_embedding(self, conn, job: dict, chunk: dict, status: str, vector_blob: bytes | None, error: str) -> None:
        timestamp = self.now()
        conn.execute(
            """INSERT INTO knowledge_chunk_embeddings
               (id, chunk_id, document_id, chunk_version, model_version,
                content_sha256, dimensions, vector_blob, status, error_message,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(chunk_id, model_version) DO UPDATE SET
                 content_sha256 = excluded.content_sha256,
                 dimensions = excluded.dimensions,
                 vector_blob = excluded.vector_blob,
                 status = excluded.status,
                 error_message = excluded.error_message,
                 updated_at = excluded.updated_at""",
            (
                self.new_id("embedding"), chunk["id"], chunk["document_id"],
                chunk["chunk_version"], job["model_version"], chunk["content_sha256"],
                self.config.dimensions, vector_blob, status, error, timestamp, timestamp,
            ),
        )

    def status(self) -> dict:
        result = {
            "enabled": self.config.enabled,
            "provider": self.config.provider,
            "model": self.config.model,
            "dimensions": self.config.dimensions,
            "model_version": self.config.version if self.config.enabled else "",
            "fallback": "fts5-bm25",
        }
        with self.db_factory() as conn:
            counts = {
                row["status"]: int(row["count"])
                for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM knowledge_embedding_jobs GROUP BY status"
                ).fetchall()
            }
        result["jobs"] = counts
        return result

    def recent_jobs(self, limit: int = 50) -> list[dict]:
        with self.db_factory() as conn:
            return [dict(row) for row in conn.execute(
                """SELECT id, document_id, chunk_version, model_version, status,
                          total_count, reused_count, succeeded_count, failed_count,
                          error_message, created_at, started_at, completed_at, updated_at
                   FROM knowledge_embedding_jobs ORDER BY created_at DESC LIMIT ?""",
                (min(max(limit, 1), 200),),
            ).fetchall()]

    def models(self) -> list[dict]:
        with self.db_factory() as conn:
            return [dict(row) for row in conn.execute(
                """SELECT version, provider, model, dimensions, config_fingerprint,
                          status, created_at, activated_at
                   FROM knowledge_embedding_models
                   ORDER BY activated_at DESC, created_at DESC"""
            ).fetchall()]

    def rollback_document(self, document_id: str, model_version: str) -> None:
        timestamp = self.now()
        with self.db_factory() as conn:
            document = conn.execute(
                "SELECT active_chunk_version FROM knowledge_documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            if not document:
                raise ValueError("知识库文件不存在")
            total = int(conn.execute(
                "SELECT COUNT(*) FROM knowledge_chunks WHERE document_id = ? AND chunk_version = ?",
                (document_id, document[0]),
            ).fetchone()[0])
            ready = int(conn.execute(
                """SELECT COUNT(*) FROM knowledge_chunk_embeddings
                   WHERE document_id = ? AND chunk_version = ? AND model_version = ?
                     AND status = 'ready'""",
                (document_id, document[0], model_version),
            ).fetchone()[0])
            if total == 0 or ready != total:
                raise ValueError("目标向量模型版本不完整，不能回滚")
            conn.execute(
                """UPDATE knowledge_documents SET active_embedding_model_version = ?,
                   embedding_status = 'ready', embedding_updated_at = ? WHERE id = ?""",
                (model_version, timestamp, document_id),
            )
