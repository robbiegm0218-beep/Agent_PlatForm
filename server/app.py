#!/usr/bin/env python3
import base64
import binascii
import hashlib
import io
import json
import os
import sqlite3
import ssl
import time
import secrets
import logging
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import uuid
from urllib.parse import parse_qs, urlparse
from http import HTTPStatus
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
try:
    from docx import Document
except ImportError:
    Document = None
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None
try:
    from server.local_extensions import CallableModelAdapter, LocalTool, LocalToolRegistry, LocalWorkflowRunner
except ModuleNotFoundError:
    from local_extensions import CallableModelAdapter, LocalTool, LocalToolRegistry, LocalWorkflowRunner

try:
    import certifi
except ImportError:
    certifi = None


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
DB_PATH = ROOT_DIR / "agent_platform.db"
KNOWLEDGE_DIR = ROOT_DIR / "data" / "knowledge"
ARTIFACT_DIR = ROOT_DIR / "data" / "artifacts"
ARTIFACT_NODE = os.environ.get("ARTIFACT_NODE", shutil.which("node") or "node")
ARTIFACT_SCRIPT = ROOT_DIR / "server" / "create_xlsx_artifact.mjs"


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without overriding explicit environment values."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_env_file(ROOT_DIR / ".env")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_DEEP_MODEL = os.environ.get("DEEPSEEK_DEEP_MODEL", "deepseek-v4-pro")
MODEL_ALIASES = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-flash",
}
DEEPSEEK_MODEL = MODEL_ALIASES.get(DEEPSEEK_MODEL, DEEPSEEK_MODEL)
DEEPSEEK_DEEP_MODEL = MODEL_ALIASES.get(DEEPSEEK_DEEP_MODEL, DEEPSEEK_DEEP_MODEL)
DEEPSEEK_SSL_VERIFY = os.environ.get("DEEPSEEK_SSL_VERIFY", "true").lower() not in {"0", "false", "no"}
DEEPSEEK_CA_FILE = os.environ.get("DEEPSEEK_CA_FILE", "")
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", str(14 * 24 * 60 * 60)))
MAX_REQUEST_BYTES = int(os.environ.get("MAX_REQUEST_BYTES", "65536"))
MAX_KNOWLEDGE_UPLOAD_BYTES = int(os.environ.get("MAX_KNOWLEDGE_UPLOAD_BYTES", str(8 * 1024 * 1024)))
MAX_RESPONSE_TOKENS = int(os.environ.get("MAX_RESPONSE_TOKENS", "2048"))
MAX_TOOL_STEPS = int(os.environ.get("MAX_TOOL_STEPS", "4"))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30"))
REQUEST_WINDOW_NS = 60 * 1_000_000_000
REQUESTS_BY_USER: dict[str, list[int]] = {}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("agent_platform")

SKILLS_DIR = ROOT_DIR / "server" / "skills"

MODEL_CATALOG = {
    "deepseek-v4-flash": {
        "name": "DeepSeek V4 Flash",
        "tier": "quick",
        "supports_tools": True,
        "max_output_tokens": {"quick": 2048, "standard": 4096, "deep": 6144},
    },
    "deepseek-v4-pro": {
        "name": "DeepSeek V4 Pro",
        "tier": "deep",
        "supports_tools": True,
        "max_output_tokens": {"quick": 4096, "standard": 6144, "deep": 8192},
    },
}
if DEEPSEEK_MODEL not in MODEL_CATALOG:
    LOGGER.warning("unsupported_configured_model model=%s; using deepseek-v4-flash", DEEPSEEK_MODEL)
    DEEPSEEK_MODEL = "deepseek-v4-flash"
if DEEPSEEK_DEEP_MODEL not in MODEL_CATALOG:
    LOGGER.warning("unsupported_deep_model model=%s; using deepseek-v4-pro", DEEPSEEK_DEEP_MODEL)
    DEEPSEEK_DEEP_MODEL = "deepseek-v4-pro"


def load_skills() -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(SKILLS_DIR.glob("*.json"))]


def validate_skill(skill: dict) -> dict:
    skill.setdefault("kind", "prompt_skill")
    skill.setdefault("tool_ids", [])
    required = ("id", "name", "description", "version", "prompt", "input_limit", "default_enabled", "status")
    if not isinstance(skill, dict) or any(key not in skill for key in required):
        raise ValueError("技能包缺少必要字段")
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", str(skill["id"])):
        raise ValueError("技能 ID 只能包含小写字母、数字和下划线")
    if skill["status"] not in {"enabled", "disabled"}:
        raise ValueError("技能状态无效")
    if skill["kind"] not in {"prompt_skill", "tool_skill"}:
        raise ValueError("技能类型无效")
    if not isinstance(skill["tool_ids"], list) or not all(isinstance(tool_id, str) for tool_id in skill["tool_ids"]):
        raise ValueError("技能工具配置无效")
    skill["input_limit"] = int(skill["input_limit"])
    skill["default_enabled"] = bool(skill["default_enabled"])
    return skill


def save_skill(skill: dict) -> dict:
    skill = validate_skill(skill)
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    (SKILLS_DIR / f"{skill['id']}.json").write_text(json.dumps(skill, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    global SKILLS
    SKILLS = load_skills()
    return skill


def parse_markdown_skill(markdown: str, filename: str = "") -> dict:
    text = markdown.strip()
    if not text:
        raise ValueError("Markdown 技能文件不能为空")
    metadata: dict[str, str] = {}
    body = text
    if text.startswith("---\n"):
        _, frontmatter, body = text.split("---\n", 2)
        for line in frontmatter.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip('"').strip("'")
    lines = [line.strip() for line in body.splitlines()]
    heading = next((line[2:].strip() for line in lines if line.startswith("# ")), "")
    name = metadata.get("name") or heading or Path(filename).stem or "未命名技能"
    prompt = "\n".join(line for line in lines if not line.startswith("# ")).strip()
    if not prompt:
        raise ValueError("Markdown 技能需要包含提示正文")
    generated_id = f"skill_{hashlib.sha256((filename + text).encode('utf-8')).hexdigest()[:16]}"
    return {
        "id": metadata.get("id") or generated_id,
        "name": name,
        "description": metadata.get("description") or f"从 Markdown 导入的技能：{name}",
        "version": metadata.get("version", "1.0.0"),
        "prompt": prompt,
        "input_limit": int(metadata.get("input_limit", "12000")),
        "default_enabled": metadata.get("default_enabled", "false").lower() == "true",
        "status": metadata.get("status", "enabled"),
        "kind": metadata.get("kind", "prompt_skill"),
        "tool_ids": [tool_id.strip() for tool_id in metadata.get("tool_ids", "").split(",") if tool_id.strip()],
    }


SKILLS = load_skills()
"""[
    {
        "id": "general_assistant",
        "name": "通用助手",
        "description": "适合日常问答、规划、总结和信息整理。",
        "prompt": "你是一个清晰、务实、可靠的通用助手。回答要结构明确，避免空话。",
        "default_enabled": True,
        "category": "skill",
    },
    {
        "id": "writing_assistant",
        "name": "写作助手",
        "description": "帮助撰写、润色、改写邮件、方案、文案和报告。",
        "prompt": "你是一个专业写作助手。根据用户目标输出可直接使用的文本，并保持语气自然。",
        "default_enabled": False,
        "category": "skill",
    },
    {
        "id": "code_assistant",
        "name": "代码助手",
        "description": "帮助解释代码、设计技术方案、排查错误和生成示例。",
        "prompt": "你是一个资深软件工程助手。优先给出可执行方案、关键代码和风险点。",
        "default_enabled": False,
        "category": "skill",
    },
    {
        "id": "translation_assistant",
        "name": "翻译助手",
        "description": "处理中英文翻译、润色、改写和语气调整。",
        "prompt": "你是一个精准翻译和语言润色助手。保留原意，输出自然、地道的表达。",
        "default_enabled": False,
        "category": "skill",
    },
]"""

APPS = [
    {
        "id": "deepseek",
        "name": "DeepSeek 模型",
        "description": "当前模型供应商。配置 DEEPSEEK_API_KEY 后启用真实模型回复。",
        "status": "configured" if DEEPSEEK_API_KEY else "mock",
        "category": "app",
    },
    {
        "id": "local_skill_registry",
        "name": "本地技能库",
        "description": "第一版技能由代码维护，用户可在前台启用或禁用。",
        "status": "enabled",
        "category": "app",
    },
    {
        "id": "local_artifacts",
        "name": "本地文件产物",
        "description": "可生成 Markdown 和 Excel 文件；创建文件前必须由用户确认。",
        "status": "enabled",
        "category": "app",
    },
]


def platform_status_tool(_arguments: dict) -> dict:
    return {
        "service": "Agent_Platform",
        "model": DEEPSEEK_MODEL,
        "deepseek_configured": bool(DEEPSEEK_API_KEY),
        "storage": "sqlite",
    }


def search_workspace_files(arguments: dict) -> dict:
    query = arguments["query"].strip().lower()
    limit = min(max(arguments.get("limit", 8), 1), 20)
    if len(query) < 2:
        raise ValueError("检索关键词至少需要 2 个字符")
    ignored_parts = {".git", "__pycache__", "node_modules"}
    matches = []
    for path in ROOT_DIR.rglob("*"):
        if len(matches) >= limit:
            break
        if not path.is_file() or ignored_parts.intersection(path.parts) or path.name in {".env", "agent_platform.db"}:
            continue
        relative_path = path.relative_to(ROOT_DIR).as_posix()
        if query in relative_path.lower():
            matches.append({"path": relative_path, "size_bytes": path.stat().st_size})
    return {"query": arguments["query"], "matches": matches, "count": len(matches)}


LOCAL_TOOLS = LocalToolRegistry([
    LocalTool(
        "platform_status",
        "平台状态",
        "读取本机 Agent_Platform 的健康状态。",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={"type": "object"},
        execute_fn=platform_status_tool,
    ),
    LocalTool(
        "search_workspace_files",
        "检索本地文件",
        "按文件名在当前 Agent_Platform 工作区检索文件，不读取文件内容。",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要检索的文件名关键词"},
                "limit": {"type": "integer", "description": "最多返回数量，1 到 20"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        execute_fn=search_workspace_files,
    ),
])
WORKFLOW_RUNNER = LocalWorkflowRunner()


def now() -> int:
    return time.time_ns()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 600_000).hex()
    return f"pbkdf2_sha256$600000${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("pbkdf2_sha256$"):
        _, iterations, salt, digest = stored.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), int(iterations)).hex()
        return secrets.compare_digest(actual, digest)
    return secrets.compare_digest(hashlib.sha256(password.encode("utf-8")).hexdigest(), stored)


class DatabaseConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, factory=DatabaseConnection)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                name TEXT NOT NULL,
                avatar_url TEXT DEFAULT '',
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                folder_id TEXT DEFAULT '',
                title TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS thread_folders (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                status TEXT NOT NULL,
                model TEXT NOT NULL,
                started_at INTEGER NOT NULL,
                completed_at INTEGER,
                error TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS run_events (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_enabled_skills (
                user_id TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, skill_id)
            );
            CREATE TABLE IF NOT EXISTS thread_selected_skills (
                thread_id TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                selected INTEGER NOT NULL,
                PRIMARY KEY (thread_id, skill_id)
            );
            CREATE TABLE IF NOT EXISTS run_steps (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                requires_confirmation INTEGER NOT NULL DEFAULT 0,
                error TEXT DEFAULT '',
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge_documents (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                content TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                kind TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                summary TEXT DEFAULT '',
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_confirmations (
                run_id TEXT PRIMARY KEY,
                request TEXT NOT NULL,
                status TEXT NOT NULL,
                decision TEXT DEFAULT '',
                created_at INTEGER NOT NULL,
                resolved_at INTEGER
            );
            """
        )
        ensure_column(conn, "threads", "context_summary", "TEXT DEFAULT ''")
        ensure_column(conn, "threads", "folder_id", "TEXT DEFAULT ''")
        ensure_column(conn, "runs", "skill_snapshot", "TEXT DEFAULT '[]'")
        ensure_column(conn, "runs", "execution_context", "TEXT DEFAULT '{}'")
        ensure_column(conn, "runs", "plan_snapshot", "TEXT DEFAULT '[]'")
        ensure_column(conn, "runs", "reflection_snapshot", "TEXT DEFAULT '{}'")
        ensure_column(conn, "runs", "input_tokens_estimate", "INTEGER DEFAULT 0")
        ensure_column(conn, "runs", "output_tokens_estimate", "INTEGER DEFAULT 0")
        ensure_column(conn, "runs", "tool_call_count", "INTEGER DEFAULT 0")
        ensure_column(conn, "sessions", "expires_at", "INTEGER DEFAULT 0")
        user = conn.execute("SELECT id FROM users WHERE email = ?", ("admin@example.com",)).fetchone()
        if not user:
            user_id = new_id("user")
            conn.execute(
                "INSERT INTO users (id, email, password_hash, name, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, "admin@example.com", hash_password("admin123"), "Admin", now()),
            )
            for skill in SKILLS:
                conn.execute(
                    "INSERT INTO user_enabled_skills (user_id, skill_id, enabled, updated_at) VALUES (?, ?, ?, ?)",
                    (user_id, skill["id"], 1 if skill["default_enabled"] else 0, now()),
                )


def row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def allow_request(user_id: str) -> bool:
    current = now()
    recent = [stamp for stamp in REQUESTS_BY_USER.get(user_id, []) if current - stamp < REQUEST_WINDOW_NS]
    if len(recent) >= RATE_LIMIT_PER_MINUTE:
        REQUESTS_BY_USER[user_id] = recent
        return False
    recent.append(current)
    REQUESTS_BY_USER[user_id] = recent
    return True


def infer_task_profile(content: str, requested_model: str = "auto", requested_task_mode: str = "auto") -> dict:
    deep_markers = ("调研", "方案", "报告", "深度", "全面", "竞品", "商业计划", "架构设计", "复盘")
    standard_markers = ("改写", "撰写", "写一", "代码", "分析", "待办", "负责人", "设计")
    tool_markers = ("平台状态", "系统状态", "文件", "检索", "查找", "搜索")
    needs_tools = any(marker in content for marker in tool_markers)
    knowledge_intent = classify_knowledge_intent(content)
    needs_knowledge = knowledge_intent["needed"]
    complexity = "deep" if len(content) >= 80 or any(marker in content for marker in deep_markers) else "standard"
    if len(content) < 32 and complexity != "deep" and not any(marker in content for marker in standard_markers):
        complexity = "quick"
    if requested_task_mode != "auto":
        complexity = requested_task_mode
    if requested_model != "auto":
        model = requested_model
        route = "manual"
        reason = "用户手动选择模型"
    elif complexity == "deep" and not needs_tools:
        model = DEEPSEEK_DEEP_MODEL
        route = "automatic"
        reason = "复杂任务使用高质量模型"
    else:
        model = DEEPSEEK_MODEL
        route = "automatic"
        reason = "普通或工具任务使用快速工具兼容模型"
    profile = MODEL_CATALOG[model]
    if needs_tools and not profile["supports_tools"]:
        model = DEEPSEEK_MODEL
        profile = MODEL_CATALOG[model]
        route = "fallback"
        reason = "任务需要工具调用，已切换到工具兼容模型"
    return {
        "model": model,
        "task_tier": complexity,
        "route": "manual_task_mode" if requested_task_mode != "auto" and route == "automatic" else route,
        "reason": reason,
        "needs_tools": needs_tools,
        "needs_knowledge": needs_knowledge,
        "knowledge_intent": knowledge_intent,
        "max_output_tokens": profile["max_output_tokens"][complexity],
        "quality_check": complexity == "deep",
    }


def classify_knowledge_intent(content: str) -> dict:
    """Allow retrieval only for an explicit local-source request or a factual query."""
    normalized = re.sub(r"\s+", "", content.lower())
    local_source_markers = ("知识库", "本地资料", "上传资料", "参考资料", "附件", "文档中", "材料中")
    if any(marker in normalized for marker in local_source_markers):
        return {"needed": True, "reason": "explicit_local_source"}
    if re.search(r"(?:根据|基于|查阅|引用|检索).{0,10}(?:资料|文档|材料|来源)", normalized):
        return {"needed": True, "reason": "explicit_local_source"}

    # A definition/data question can be answered from a matching local source, but UI and writing requests are not evidence requests.
    operational_markers = ("平台", "技能", "模型", "版本", "接口", "服务", "对话", "文件夹", "改动范围", "今天", "星期", "代码")
    factual_markers = ("什么是", "是什么", "定义", "含义", "说明", "介绍", "多少", "数据", "指标", "事实")
    if (
        len(normalized) >= 5
        and any(marker in normalized for marker in factual_markers)
        and not any(marker in normalized for marker in operational_markers)
    ):
        return {"needed": True, "reason": "factual_query"}
    return {"needed": False, "reason": "not_recognized"}


def allowed_tools_for_task(content: str) -> list[dict]:
    tool_definitions = [tool for tool in LOCAL_TOOLS.list() if tool["enabled"] and tool["risk"] == "read_only"]
    if "平台状态" in content or "系统状态" in content:
        return [tool for tool in tool_definitions if tool["id"] == "platform_status"]
    if any(marker in content for marker in ("文件", "检索", "查找", "搜索")):
        return [tool for tool in tool_definitions if tool["id"] == "search_workspace_files"]
    return []


def extract_knowledge_text(filename: str, raw: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".txt"}:
        return raw.decode("utf-8", errors="replace")
    if suffix == ".docx":
        if not Document:
            raise ValueError("当前环境未安装 Word 解析组件")
        document = Document(io.BytesIO(raw))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    if suffix == ".pdf":
        if not PdfReader:
            raise ValueError("当前环境未安装 PDF 解析组件 pypdf")
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    raise ValueError("仅支持 Markdown、TXT、DOCX 和 PDF 文件")


def chunk_knowledge_text(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    normalized = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not normalized:
        return []
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + size)
        if end < len(normalized):
            boundary = max(normalized.rfind("\n", start + size // 2, end), normalized.rfind("。", start + size // 2, end))
            if boundary > start:
                end = boundary + 1
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def knowledge_terms(query: str) -> list[str]:
    compact = re.sub(r"\s+", "", query.lower())
    english = re.findall(r"[a-z0-9_]{2,}", compact)
    chinese = [compact[index:index + 2] for index in range(max(0, len(compact) - 1)) if re.search(r"[\u4e00-\u9fff]", compact[index:index + 2])]
    return list(dict.fromkeys(english + chinese))[:20]


def search_knowledge(user_id: str, query: str, limit: int = 4) -> list[dict]:
    terms = knowledge_terms(query)
    if not terms:
        return []
    with db() as conn:
        rows = conn.execute(
            """
            SELECT knowledge_chunks.*, knowledge_documents.filename
            FROM knowledge_chunks JOIN knowledge_documents ON knowledge_documents.id = knowledge_chunks.document_id
            WHERE knowledge_documents.user_id = ?
            """,
            (user_id,),
        ).fetchall()
    scored = []
    minimum_score = 1 if len(terms) == 1 else 2
    for row in rows:
        content = row["content"]
        score = sum(content.lower().count(term) for term in terms)
        if score >= minimum_score:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], item[1]["position"]))
    return [
        {
            "document_id": row["document_id"],
            "filename": row["filename"],
            "position": row["position"],
            "excerpt": row["content"][:700],
            "score": score,
        }
        for score, row in scored[:limit]
    ]


def build_execution_plan(content: str, active_skills: list[dict], allowed_tools: list[dict]) -> list[dict]:
    complex_markers = ("计划", "方案", "调研", "分析", "步骤", "并且", "然后", "先")
    is_complex = len(content) >= 48 or any(marker in content for marker in complex_markers)
    if not is_complex:
        return [{"id": "step_1", "title": "完成回答", "status": "pending"}]
    steps = [{"id": "step_1", "title": "分析任务目标与约束", "status": "pending"}]
    if infer_task_profile(content)["needs_knowledge"]:
        steps.append({"id": f"step_{len(steps) + 1}", "title": "检索本地资料依据", "status": "pending"})
    if active_skills:
        steps.append({"id": "step_2", "title": "应用所选技能", "status": "pending"})
    if allowed_tools:
        steps.append({"id": f"step_{len(steps) + 1}", "title": "按需检索本地工具信息", "status": "pending"})
    steps.append({"id": f"step_{len(steps) + 1}", "title": "生成并检查最终回答", "status": "pending"})
    return steps


def build_execution_context(user_id: str, task_profile: dict, active_skills: list[dict], requested_skill_ids: list[str] | None, content: str, knowledge_refs: list[dict]) -> dict:
    tool_definitions = allowed_tools_for_task(content) if task_profile["needs_tools"] else []
    return {
        "version": 1,
        "user_id": user_id,
        "model": task_profile["model"],
        "task_tier": task_profile["task_tier"],
        "model_route": task_profile["route"],
        "model_route_reason": task_profile["reason"],
        "max_output_tokens": task_profile["max_output_tokens"],
        "quality_check": task_profile["quality_check"],
        "skills": active_skills,
        "skill_route": "explicit" if requested_skill_ids is not None else "default",
        "allowed_tool_ids": [tool["id"] for tool in tool_definitions],
        "tools": tool_definitions,
        "max_tool_steps": MAX_TOOL_STEPS,
        "input_limit": min([skill["input_limit"] for skill in active_skills] or [MAX_REQUEST_BYTES]),
        "task_preview": content[:160],
        "knowledge_refs": knowledge_refs,
        "knowledge_route": "retrieved" if knowledge_refs else ("required_no_match" if task_profile["needs_knowledge"] else "not_needed"),
        "knowledge_intent": task_profile["knowledge_intent"],
        "knowledge_match_count": len(knowledge_refs),
    }


def event_summary(event_type: str, payload: dict) -> str:
    if event_type == "skill_routed":
        names = "、".join(payload.get("skills", [])) or "未使用技能"
        return f"技能路由：{names}"
    if event_type == "plan_created":
        return f"执行计划：{len(payload.get('steps', []))} 个步骤"
    if event_type == "tool_call":
        return f"正在调用工具：{payload.get('tool_name', payload.get('tool_id', '本地工具'))}"
    if event_type == "tool_result":
        return f"工具完成：{payload.get('tool_name', payload.get('tool_id', '本地工具'))}"
    if event_type == "tool_error":
        return f"工具失败：{payload.get('tool_name', payload.get('tool_id', '本地工具'))}"
    if event_type == "reflection_started":
        return "正在进行结果质量检查"
    if event_type == "reflection_revised":
        return "已根据质量检查修订回答"
    if event_type == "reflection_completed":
        return f"质量检查：{payload.get('summary', '已完成')}"
    if event_type == "knowledge_retrieved":
        return f"本地知识库命中 {payload.get('count', 0)} 个资料片段"
    if event_type == "knowledge_no_match":
        return "本地知识库未命中，回答将标注为建议或待验证项"
    if event_type == "knowledge_not_needed":
        return "本次问题未使用本地资料"
    return "正在处理任务"


class AgentPlatformHandler(SimpleHTTPRequestHandler):
    server_version = "AgentPlatform/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path.startswith("/api/"):
            self.handle_api_get()
            return
        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        self.handle_api_post()

    def do_PATCH(self):
        self.handle_api_patch()

    def do_DELETE(self):
        self.handle_api_delete()

    def read_json(self, max_bytes: int = MAX_REQUEST_BYTES) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > max_bytes:
            raise ValueError("请求内容过大")
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: int = 400) -> None:
        LOGGER.warning("api_error status=%s path=%s code=%s", status, self.path.split("?")[0], message[:80])
        self.send_json({"error": message}, status)

    def bearer_token(self) -> str:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth.replace("Bearer ", "", 1).strip()
        return ""

    def current_user(self):
        token = self.bearer_token()
        if not token:
            return None
        with db() as conn:
            row = conn.execute(
                """
                SELECT users.* FROM users
                JOIN sessions ON sessions.user_id = users.id
                WHERE sessions.token = ? AND (sessions.expires_at = 0 OR sessions.expires_at > ?)
                """,
                (token, now()),
            ).fetchone()
            return row_to_dict(row) if row else None

    def require_user(self):
        user = self.current_user()
        if not user:
            self.send_error_json("未登录或登录已失效", HTTPStatus.UNAUTHORIZED)
            return None
        return user

    def handle_api_get(self) -> None:
        user = self.require_user() if self.path != "/api/health" else None
        if self.path == "/api/health":
            self.send_json(
                {
                    "ok": True,
                    "model": DEEPSEEK_MODEL,
                    "deepseek_configured": bool(DEEPSEEK_API_KEY),
                    "deepseek_ssl_verify": DEEPSEEK_SSL_VERIFY,
                    "database": "sqlite",
                    "rate_limit_per_minute": RATE_LIMIT_PER_MINUTE,
                }
            )
            return
        if not user:
            return

        if self.path == "/api/me":
            self.send_json({"user": public_user(user)})
            return
        if self.path == "/api/models":
            models = [{"id": "auto", "name": "自动选择", "configured": bool(DEEPSEEK_API_KEY)}]
            for model_id, profile in MODEL_CATALOG.items():
                models.append({
                    "id": model_id,
                    "name": profile["name"],
                    "configured": bool(DEEPSEEK_API_KEY),
                    "supports_tools": profile["supports_tools"],
                    "tier": profile["tier"],
                })
            self.send_json({"models": models, "default_model": DEEPSEEK_MODEL, "deep_model": DEEPSEEK_DEEP_MODEL})
            return
        if self.path == "/api/metrics":
            self.get_metrics(user)
            return
        if self.path == "/api/knowledge":
            self.list_knowledge(user)
            return
        if self.path == "/api/artifacts":
            self.list_artifacts(user)
            return
        if self.path.startswith("/api/artifacts/") and self.path.endswith("/download"):
            self.download_artifact(user)
            return
        if self.path.startswith("/api/knowledge/search"):
            self.search_knowledge_api(user)
            return
        if self.path == "/api/threads":
            self.list_threads(user)
            return
        if self.path == "/api/folders":
            self.list_folders(user)
            return
        if self.path.startswith("/api/runs/"):
            self.get_run(user)
            return
        if self.path.startswith("/api/threads/") and self.path.endswith("/runs"):
            self.list_runs(user)
            return
        if self.path.startswith("/api/threads/") and self.path.endswith("/skills"):
            self.list_thread_skills(user)
            return
        if self.path.startswith("/api/threads/"):
            self.get_thread(user)
            return
        if self.path.startswith("/api/skills/"):
            self.get_skill(user)
            return
        if self.path == "/api/skills":
            self.list_skills(user)
            return
        if self.path == "/api/apps":
            self.send_json({"apps": [
                {**APPS[0], "status": "已连接" if DEEPSEEK_API_KEY else "未配置"},
                {**APPS[1], "status": f"已启用 · {len(SKILLS)} 项 · v1"},
                {**APPS[2], "status": "已启用 · 创建前需确认"},
            ]})
            return
        if self.path == "/api/tools":
            self.send_json({"tools": LOCAL_TOOLS.list()})
            return
        self.send_error_json("接口不存在", HTTPStatus.NOT_FOUND)

    def handle_api_post(self) -> None:
        if self.path == "/api/login":
            self.login()
            return
        user = self.require_user()
        if not user:
            return
        if self.path == "/api/logout":
            self.logout()
            return
        if self.path == "/api/logout-all":
            self.logout_all(user)
            return
        if self.path == "/api/skills":
            self.create_skill(user)
            return
        if self.path == "/api/knowledge":
            self.create_knowledge(user)
            return
        if self.path == "/api/threads":
            self.create_thread(user)
            return
        if self.path == "/api/folders":
            self.create_folder(user)
            return
        if self.path.startswith("/api/runs/") and self.path.endswith("/confirmation"):
            self.resolve_confirmation(user)
            return
        if self.path == "/api/chat":
            self.chat(user)
            return
        self.send_error_json("接口不存在", HTTPStatus.NOT_FOUND)

    def handle_api_patch(self) -> None:
        user = self.require_user()
        if not user:
            return
        if self.path == "/api/me":
            self.update_me(user)
            return
        if self.path.startswith("/api/folders/"):
            self.update_folder(user)
            return
        if self.path.startswith("/api/threads/"):
            if self.path.endswith("/skills"):
                self.update_thread_skills(user)
                return
            self.update_thread(user)
            return
        if self.path.startswith("/api/skills/"):
            self.update_skill(user)
            return
        self.send_error_json("接口不存在", HTTPStatus.NOT_FOUND)

    def handle_api_delete(self) -> None:
        user = self.require_user()
        if not user:
            return
        if self.path.startswith("/api/threads/"):
            thread_id = self.path.split("/")[-1]
            with db() as conn:
                thread = conn.execute(
                    "SELECT id FROM threads WHERE id = ? AND user_id = ?",
                    (thread_id, user["id"]),
                ).fetchone()
                if not thread:
                    self.send_error_json("对话不存在", HTTPStatus.NOT_FOUND)
                    return
                conn.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
                conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
            self.send_json({"ok": True})
            return
        if self.path.startswith("/api/folders/"):
            self.delete_folder(user)
            return
        if self.path.startswith("/api/skills/"):
            self.delete_skill(user)
            return
        if self.path.startswith("/api/knowledge/"):
            self.delete_knowledge(user)
            return
        if self.path.startswith("/api/artifacts/"):
            self.delete_artifact(user)
            return
        self.send_error_json("接口不存在", HTTPStatus.NOT_FOUND)

    def login(self) -> None:
        payload = self.read_json()
        email = payload.get("email", "").strip().lower()
        password = payload.get("password", "")
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if not user or not verify_password(password, user["password_hash"]):
                self.send_error_json("邮箱或密码错误", HTTPStatus.UNAUTHORIZED)
                return
            token = new_id("session")
            if not user["password_hash"].startswith("pbkdf2_sha256$"):
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user["id"]))
            conn.execute("INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)", (token, user["id"], now(), now() + SESSION_TTL_SECONDS * 1_000_000_000))
        self.send_json({"token": token, "user": public_user(row_to_dict(user))})

    def logout(self) -> None:
        token = self.bearer_token()
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        self.send_json({"ok": True})

    def logout_all(self, user: dict) -> None:
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
        self.send_json({"ok": True})

    def update_me(self, user: dict) -> None:
        payload = self.read_json()
        name = payload.get("name", "").strip()
        if not name:
            self.send_error_json("昵称不能为空")
            return
        with db() as conn:
            conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, user["id"]))
            updated = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        self.send_json({"user": public_user(row_to_dict(updated))})

    def list_threads(self, user: dict) -> None:
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM threads WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
                (user["id"],),
            ).fetchall()
        self.send_json({"threads": [row_to_dict(row) for row in rows]})

    def list_folders(self, user: dict) -> None:
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM thread_folders WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
                (user["id"],),
            ).fetchall()
        self.send_json({"folders": [row_to_dict(row) for row in rows]})

    def get_thread(self, user: dict) -> None:
        thread_id = self.path.split("/")[-1]
        with db() as conn:
            thread = conn.execute(
                "SELECT * FROM threads WHERE id = ? AND user_id = ?",
                (thread_id, user["id"]),
            ).fetchone()
            if not thread:
                self.send_error_json("对话不存在", HTTPStatus.NOT_FOUND)
                return
            messages = conn.execute(
                "SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at ASC, id ASC",
                (thread_id,),
            ).fetchall()
        self.send_json({"thread": row_to_dict(thread), "messages": [row_to_dict(row) for row in messages]})

    def create_thread(self, user: dict) -> None:
        payload = self.read_json()
        title = payload.get("title", "新对话").strip() or "新对话"
        folder_id = self.validate_folder_id(user["id"], payload.get("folder_id", ""))
        thread_id = new_id("thread")
        with db() as conn:
            conn.execute(
                "INSERT INTO threads (id, user_id, folder_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (thread_id, user["id"], folder_id, title, now(), now()),
            )
            thread = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        self.send_json({"thread": row_to_dict(thread)})

    def validate_folder_id(self, user_id: str, folder_id: object) -> str:
        folder_id = str(folder_id or "")
        if not folder_id:
            return ""
        with db() as conn:
            folder = conn.execute(
                "SELECT id FROM thread_folders WHERE id = ? AND user_id = ?", (folder_id, user_id)
            ).fetchone()
        if not folder:
            raise ValueError("文件夹不存在")
        return folder_id

    def create_folder(self, user: dict) -> None:
        name = self.read_json().get("name", "").strip()
        if not name:
            self.send_error_json("文件夹名称不能为空")
            return
        folder_id = new_id("folder")
        with db() as conn:
            conn.execute(
                "INSERT INTO thread_folders (id, user_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (folder_id, user["id"], name[:80], now(), now()),
            )
            folder = conn.execute("SELECT * FROM thread_folders WHERE id = ?", (folder_id,)).fetchone()
        self.send_json({"folder": row_to_dict(folder)})

    def update_folder(self, user: dict) -> None:
        folder_id = self.path.split("/")[-1]
        name = self.read_json().get("name", "").strip()
        if not name:
            self.send_error_json("文件夹名称不能为空")
            return
        with db() as conn:
            conn.execute(
                "UPDATE thread_folders SET name = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (name[:80], now(), folder_id, user["id"]),
            )
            folder = conn.execute(
                "SELECT * FROM thread_folders WHERE id = ? AND user_id = ?", (folder_id, user["id"])
            ).fetchone()
        if not folder:
            self.send_error_json("文件夹不存在", HTTPStatus.NOT_FOUND)
            return
        self.send_json({"folder": row_to_dict(folder)})

    def delete_folder(self, user: dict) -> None:
        folder_id = self.path.split("/")[-1]
        with db() as conn:
            folder = conn.execute(
                "SELECT id FROM thread_folders WHERE id = ? AND user_id = ?", (folder_id, user["id"])
            ).fetchone()
            if not folder:
                self.send_error_json("文件夹不存在", HTTPStatus.NOT_FOUND)
                return
            conn.execute("UPDATE threads SET folder_id = '' WHERE folder_id = ? AND user_id = ?", (folder_id, user["id"]))
            conn.execute("DELETE FROM thread_folders WHERE id = ?", (folder_id,))
        self.send_json({"ok": True})

    def update_thread(self, user: dict) -> None:
        thread_id = self.path.split("/")[-1]
        payload = self.read_json()
        if "title" not in payload and "folder_id" not in payload:
            self.send_error_json("没有可更新的对话信息")
            return
        with db() as conn:
            thread = conn.execute(
                "SELECT * FROM threads WHERE id = ? AND user_id = ?", (thread_id, user["id"])
            ).fetchone()
            if not thread:
                self.send_error_json("对话不存在", HTTPStatus.NOT_FOUND)
                return
            title = payload.get("title", thread["title"]).strip()
            if not title:
                self.send_error_json("对话名称不能为空")
                return
            folder_id = self.validate_folder_id(user["id"], payload.get("folder_id", thread["folder_id"]))
            conn.execute(
                "UPDATE threads SET title = ?, folder_id = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (title[:80], folder_id, now(), thread_id, user["id"]),
            )
            thread = conn.execute(
                "SELECT * FROM threads WHERE id = ? AND user_id = ?", (thread_id, user["id"])
            ).fetchone()
        if not thread:
            self.send_error_json("对话不存在", HTTPStatus.NOT_FOUND)
            return
        self.send_json({"thread": row_to_dict(thread)})

    def list_runs(self, user: dict) -> None:
        thread_id = self.path.split("/")[-2]
        with db() as conn:
            rows = conn.execute(
                """
                SELECT runs.* FROM runs JOIN threads ON threads.id = runs.thread_id
                WHERE runs.thread_id = ? AND threads.user_id = ?
                ORDER BY runs.started_at DESC, runs.id DESC
                """,
                (thread_id, user["id"]),
            ).fetchall()
        self.send_json({"runs": [row_to_dict(row) for row in rows]})

    def get_run(self, user: dict) -> None:
        run_id = self.path.split("/")[-1]
        with db() as conn:
            run = conn.execute(
                """
                SELECT runs.* FROM runs JOIN threads ON threads.id = runs.thread_id
                WHERE runs.id = ? AND threads.user_id = ?
                """,
                (run_id, user["id"]),
            ).fetchone()
            if not run:
                self.send_error_json("运行记录不存在", HTTPStatus.NOT_FOUND)
                return
            events = conn.execute(
                "SELECT * FROM run_events WHERE run_id = ? ORDER BY created_at ASC, id ASC", (run_id,)
            ).fetchall()
            steps = conn.execute(
                "SELECT * FROM run_steps WHERE run_id = ? ORDER BY position ASC", (run_id,)
            ).fetchall()
            confirmation = conn.execute(
                "SELECT * FROM run_confirmations WHERE run_id = ?", (run_id,)
            ).fetchone()
            artifact = conn.execute(
                "SELECT * FROM artifacts WHERE run_id = ?", (run_id,)
            ).fetchone()
        self.send_json({"run": row_to_dict(run), "events": [row_to_dict(row) for row in events], "steps": [row_to_dict(row) for row in steps], "confirmation": row_to_dict(confirmation) if confirmation else None, "artifact": row_to_dict(artifact) if artifact else None})

    def resolve_confirmation(self, user: dict) -> None:
        run_id = self.path.split("/")[-2]
        approved = self.read_json().get("approved")
        if not isinstance(approved, bool):
            self.send_error_json("确认结果无效")
            return
        with db() as conn:
            run = conn.execute("SELECT runs.* FROM runs JOIN threads ON threads.id = runs.thread_id WHERE runs.id = ? AND threads.user_id = ?", (run_id, user["id"])).fetchone()
            confirmation = conn.execute("SELECT * FROM run_confirmations WHERE run_id = ?", (run_id,)).fetchone()
            if not run or not confirmation:
                self.send_error_json("待确认运行不存在", HTTPStatus.NOT_FOUND)
                return
            if confirmation["status"] != "pending" or run["status"] != "awaiting_confirmation":
                self.send_error_json("该运行已处理", HTTPStatus.CONFLICT)
                return
            status = "approved" if approved else "rejected"
            conn.execute("UPDATE run_confirmations SET status = ?, decision = ?, resolved_at = ? WHERE run_id = ?", (status, "用户批准" if approved else "用户拒绝", now(), run_id))
            if not approved:
                conn.execute("UPDATE runs SET status = ?, completed_at = ? WHERE id = ?", ("cancelled", now(), run_id))
                conn.execute(
                    "UPDATE run_steps SET status = ?, updated_at = ? WHERE run_id = ? AND status = 'awaiting_confirmation'",
                    ("cancelled", now(), run_id),
                )
            conn.execute("INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)", (new_id("event"), run_id, "confirmation_resolved", json.dumps({"approved": approved}), now()))
        if not approved:
            self.send_json({"ok": True, "approved": False, "run_id": run_id})
            return

        try:
            result = complete_confirmed_artifact_run(run_id, user["id"])
        except Exception as exc:
            LOGGER.warning("confirmed_run_failed run_id=%s error=%s", run_id, str(exc)[:160])
            self.send_error_json(str(exc), HTTPStatus.BAD_GATEWAY)
            return
        self.send_json({"ok": True, "approved": True, "run_id": run_id, **result})

    def get_metrics(self, user: dict) -> None:
        with db() as conn:
            rows = conn.execute(
                """
                SELECT runs.* FROM runs JOIN threads ON threads.id = runs.thread_id
                WHERE threads.user_id = ? AND runs.status = 'completed'
                ORDER BY runs.started_at DESC LIMIT 200
                """,
                (user["id"],),
            ).fetchall()
        buckets: dict[str, dict] = {}
        for row in rows:
            run = row_to_dict(row)
            context = json.loads(run["execution_context"] or "{}")
            tier = context.get("task_tier", "standard")
            bucket = buckets.setdefault(tier, {"runs": 0, "input_tokens_estimate": 0, "output_tokens_estimate": 0, "tool_call_count": 0, "average_seconds": 0.0})
            bucket["runs"] += 1
            bucket["input_tokens_estimate"] += run.get("input_tokens_estimate", 0)
            bucket["output_tokens_estimate"] += run.get("output_tokens_estimate", 0)
            bucket["tool_call_count"] += run.get("tool_call_count", 0)
            if run["completed_at"]:
                bucket["average_seconds"] += max(0, (run["completed_at"] - run["started_at"]) / 1_000_000_000)
        for bucket in buckets.values():
            bucket["average_seconds"] = round(bucket["average_seconds"] / bucket["runs"], 2)
        self.send_json({"tiers": buckets, "sample_size": len(rows)})

    def list_knowledge(self, user: dict) -> None:
        with db() as conn:
            rows = conn.execute(
                "SELECT id, filename, mime_type, size_bytes, chunk_count, created_at FROM knowledge_documents WHERE user_id = ? ORDER BY created_at DESC",
                (user["id"],),
            ).fetchall()
        self.send_json({"documents": [row_to_dict(row) for row in rows], "pdf_supported": bool(PdfReader)})

    def list_artifacts(self, user: dict) -> None:
        with db() as conn:
            rows = conn.execute("SELECT * FROM artifacts WHERE user_id = ? ORDER BY created_at DESC, id DESC", (user["id"],)).fetchall()
        self.send_json({"artifacts": [row_to_dict(row) for row in rows]})

    def download_artifact(self, user: dict) -> None:
        artifact_id = self.path.split("/")[-2]
        with db() as conn:
            artifact = conn.execute(
                "SELECT * FROM artifacts WHERE id = ? AND user_id = ?", (artifact_id, user["id"])
            ).fetchone()
        if not artifact:
            self.send_error_json("文件产物不存在", HTTPStatus.NOT_FOUND)
            return
        path = Path(artifact["storage_path"])
        allowed_root = ARTIFACT_DIR.resolve()
        if not path.is_file() or not path.resolve().is_relative_to(allowed_root):
            self.send_error_json("文件产物不可用", HTTPStatus.NOT_FOUND)
            return
        content_type = "text/markdown; charset=utf-8" if artifact["kind"] == "markdown" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{artifact["filename"]}"')
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def delete_artifact(self, user: dict) -> None:
        artifact_id = self.path.split("/")[-1]
        with db() as conn:
            artifact = conn.execute(
                "SELECT * FROM artifacts WHERE id = ? AND user_id = ?",
                (artifact_id, user["id"]),
            ).fetchone()
        if not artifact:
            self.send_error_json("文件产物不存在", HTTPStatus.NOT_FOUND)
            return
        path = Path(artifact["storage_path"])
        path.unlink(missing_ok=True)
        with db() as conn:
            conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
        self.send_json({"ok": True})

    def search_knowledge_api(self, user: dict) -> None:
        query = parse_qs(urlparse(self.path).query).get("query", [""])[0].strip()
        self.send_json({"results": search_knowledge(user["id"], query) if query else []})

    def create_knowledge(self, user: dict) -> None:
        try:
            payload = self.read_json(MAX_KNOWLEDGE_UPLOAD_BYTES)
            filename = Path(payload.get("filename", "")).name
            encoded = payload.get("content_base64", "")
            if not filename or not isinstance(encoded, str):
                raise ValueError("资料文件无效")
            raw = base64.b64decode(encoded, validate=True)
            if not raw or len(raw) > MAX_KNOWLEDGE_UPLOAD_BYTES:
                raise ValueError("资料为空或超过大小限制")
            text = extract_knowledge_text(filename, raw)
            chunks = chunk_knowledge_text(text)
            if not chunks:
                raise ValueError("未能从资料中提取可检索文本")
        except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
            self.send_error_json(str(exc))
            return
        document_id = new_id("knowledge")
        storage_dir = KNOWLEDGE_DIR / user["id"]
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / f"{document_id}{Path(filename).suffix.lower()}"
        storage_path.write_bytes(raw)
        mime_type = payload.get("mime_type", "application/octet-stream")[:120]
        with db() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_documents (id, user_id, filename, storage_path, mime_type, content_hash, size_bytes, chunk_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (document_id, user["id"], filename, str(storage_path), mime_type, hashlib.sha256(raw).hexdigest(), len(raw), len(chunks), now()),
            )
            conn.executemany(
                "INSERT INTO knowledge_chunks (id, document_id, position, content) VALUES (?, ?, ?, ?)",
                [(new_id("chunk"), document_id, position, chunk) for position, chunk in enumerate(chunks)],
            )
        self.send_json({"document": {"id": document_id, "filename": filename, "chunk_count": len(chunks)}}, HTTPStatus.CREATED)

    def delete_knowledge(self, user: dict) -> None:
        document_id = self.path.split("?")[0].split("/")[-1]
        with db() as conn:
            row = conn.execute(
                "SELECT storage_path FROM knowledge_documents WHERE id = ? AND user_id = ?",
                (document_id, user["id"]),
            ).fetchone()
            if not row:
                self.send_error_json("资料不存在", HTTPStatus.NOT_FOUND)
                return
            conn.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM knowledge_documents WHERE id = ?", (document_id,))
        path = Path(row["storage_path"])
        if path.exists():
            path.unlink()
        self.send_json({"ok": True})

    def list_skills(self, user: dict) -> None:
        with db() as conn:
            rows = conn.execute(
                "SELECT skill_id, enabled FROM user_enabled_skills WHERE user_id = ?",
                (user["id"],),
            ).fetchall()
        enabled_map = {row["skill_id"]: bool(row["enabled"]) for row in rows}
        skills = []
        for skill in SKILLS:
            item = dict(skill)
            item["enabled"] = enabled_map.get(skill["id"], skill["default_enabled"])
            skills.append(item)
        self.send_json({"skills": skills})

    def get_skill(self, user: dict) -> None:
        skill_id = self.path.split("/")[-1]
        skill = next((item for item in SKILLS if item["id"] == skill_id), None)
        if not skill:
            self.send_error_json("技能不存在", HTTPStatus.NOT_FOUND)
            return
        self.send_json({"skill": skill})

    def list_thread_skills(self, user: dict) -> None:
        thread_id = self.path.split("/")[-2]
        with db() as conn:
            thread = conn.execute("SELECT id FROM threads WHERE id = ? AND user_id = ?", (thread_id, user["id"])).fetchone()
            rows = conn.execute("SELECT skill_id, selected FROM thread_selected_skills WHERE thread_id = ?", (thread_id,)).fetchall()
        if not thread:
            self.send_error_json("对话不存在", HTTPStatus.NOT_FOUND)
            return
        selected = {row["skill_id"]: bool(row["selected"]) for row in rows}
        self.send_json({"skill_ids": [skill_id for skill_id, value in selected.items() if value]})

    def update_thread_skills(self, user: dict) -> None:
        thread_id = self.path.split("/")[-2]
        skill_ids = set(self.read_json().get("skill_ids", []))
        valid_ids = {skill["id"] for skill in SKILLS}
        if not skill_ids.issubset(valid_ids):
            self.send_error_json("包含不存在的技能")
            return
        with db() as conn:
            if not conn.execute("SELECT id FROM threads WHERE id = ? AND user_id = ?", (thread_id, user["id"])).fetchone():
                self.send_error_json("对话不存在", HTTPStatus.NOT_FOUND)
                return
            rows = conn.execute(
                "SELECT skill_id, enabled FROM user_enabled_skills WHERE user_id = ?",
                (user["id"],),
            ).fetchall()
            enabled = {row["skill_id"]: bool(row["enabled"]) for row in rows}
            disabled_ids = [skill_id for skill_id in skill_ids if not enabled.get(
                skill_id, next(skill["default_enabled"] for skill in SKILLS if skill["id"] == skill_id)
            )]
            if disabled_ids:
                self.send_error_json("已关闭的技能不能用于本次对话")
                return
            conn.execute("DELETE FROM thread_selected_skills WHERE thread_id = ?", (thread_id,))
            conn.executemany("INSERT INTO thread_selected_skills (thread_id, skill_id, selected) VALUES (?, ?, 1)", [(thread_id, skill_id) for skill_id in skill_ids])
        self.send_json({"ok": True, "skill_ids": sorted(skill_ids)})

    def update_skill(self, user: dict) -> None:
        skill_id = self.path.split("/")[-1]
        if skill_id not in [skill["id"] for skill in SKILLS]:
            self.send_error_json("技能不存在", HTTPStatus.NOT_FOUND)
            return
        payload = self.read_json()
        if "skill" in payload:
            try:
                if payload["skill"].get("id") != skill_id:
                    raise ValueError("技能 ID 不可修改")
                payload["skill"]["description"] = payload["skill"].get("prompt", "")
                skill = save_skill(payload["skill"])
            except (ValueError, TypeError) as exc:
                self.send_error_json(str(exc))
                return
            self.send_json({"skill": {key: value for key, value in skill.items() if key != "prompt"}})
            return
        enabled = 1 if payload.get("enabled") else 0
        with db() as conn:
            conn.execute(
                """
                INSERT INTO user_enabled_skills (user_id, skill_id, enabled, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, skill_id)
                DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at
                """,
                (user["id"], skill_id, enabled, now()),
            )
            conn.execute(
                """
                DELETE FROM thread_selected_skills
                WHERE skill_id = ? AND thread_id IN (SELECT id FROM threads WHERE user_id = ?)
                """,
                (skill_id, user["id"]),
            )
        self.send_json({"ok": True})

    def create_skill(self, user: dict) -> None:
        try:
            payload = self.read_json()
            source_skill = payload.get("skill") or parse_markdown_skill(payload.get("markdown", ""), payload.get("filename", ""))
            skill = save_skill(source_skill)
        except (ValueError, TypeError) as exc:
            self.send_error_json(str(exc))
            return
        with db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO user_enabled_skills (user_id, skill_id, enabled, updated_at) VALUES (?, ?, ?, ?)",
                (user["id"], skill["id"], 1 if skill["default_enabled"] else 0, now()),
            )
        self.send_json({"skill": {key: value for key, value in skill.items() if key != "prompt"}}, HTTPStatus.CREATED)

    def delete_skill(self, user: dict) -> None:
        skill_id = self.path.split("/")[-1]
        path = SKILLS_DIR / f"{skill_id}.json"
        if not path.exists():
            self.send_error_json("技能不存在", HTTPStatus.NOT_FOUND)
            return
        path.unlink()
        global SKILLS
        SKILLS = load_skills()
        with db() as conn:
            conn.execute("DELETE FROM user_enabled_skills WHERE skill_id = ?", (skill_id,))
            conn.execute("DELETE FROM thread_selected_skills WHERE skill_id = ?", (skill_id,))
        self.send_json({"ok": True})

    def chat(self, user: dict) -> None:
        if not allow_request(user["id"]):
            self.send_error_json("请求过于频繁，请稍后再试", HTTPStatus.TOO_MANY_REQUESTS)
            return
        payload = self.read_json()
        thread_id = payload.get("thread_id", "")
        content = payload.get("content", "").strip()
        retry = bool(payload.get("retry"))
        requested_model = payload.get("model", "auto")
        requested_task_mode = payload.get("task_mode", "auto")
        requested_skill_ids = payload.get("skill_ids")
        if not content:
            self.send_error_json("消息不能为空")
            return
        if requested_model not in {"auto", *MODEL_CATALOG}:
            self.send_error_json("模型不可用")
            return
        if requested_task_mode not in {"auto", "quick", "standard", "deep"}:
            self.send_error_json("任务档位无效")
            return
        if requested_skill_ids is not None and (
            not isinstance(requested_skill_ids, list) or not all(isinstance(skill_id, str) for skill_id in requested_skill_ids)
        ):
            self.send_error_json("技能参数无效")
            return
        task_profile = infer_task_profile(content, requested_model, requested_task_mode)
        requested_active_skills = None
        if requested_skill_ids is not None:
            requested_active_skills = enabled_skills(user["id"], requested_skill_ids=requested_skill_ids)
            if set(requested_skill_ids) != {skill["id"] for skill in requested_active_skills}:
                self.send_error_json("所选技能不存在或已关闭", HTTPStatus.BAD_REQUEST)
                return

        with db() as conn:
            thread = conn.execute(
                "SELECT * FROM threads WHERE id = ? AND user_id = ?",
                (thread_id, user["id"]),
            ).fetchone()
            if not thread:
                if retry:
                    self.send_error_json("无法重试：原对话不存在", HTTPStatus.NOT_FOUND)
                    return
                thread_id = new_id("thread")
                title = content[:24] if content else "新对话"
                conn.execute(
                    "INSERT INTO threads (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (thread_id, user["id"], title, now(), now()),
                )
            elif thread["title"] == "新对话" and not retry:
                conn.execute(
                    "UPDATE threads SET title = ?, updated_at = ? WHERE id = ?",
                    (content[:24], now(), thread_id),
                )
            # Resolve short commands such as “生成” against prior committed user intent.
            artifact_kind = requested_artifact_kind(content, thread_id)
            if retry:
                last_user_message = conn.execute(
                    """
                    SELECT content FROM messages
                    WHERE thread_id = ? AND role = 'user'
                    ORDER BY created_at DESC, id DESC LIMIT 1
                    """,
                    (thread_id,),
                ).fetchone()
                if not last_user_message or last_user_message["content"] != content:
                    self.send_error_json("无法重试：原消息已变更", HTTPStatus.CONFLICT)
                    return
            else:
                conn.execute(
                    "INSERT INTO messages (id, thread_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                    (new_id("msg"), thread_id, "user", content, now()),
                )
            active_skills = requested_active_skills if requested_active_skills is not None else enabled_skills(user["id"], thread_id)
            knowledge_refs = search_knowledge(user["id"], content) if task_profile["needs_knowledge"] else []
            execution_context = build_execution_context(user["id"], task_profile, active_skills, requested_skill_ids, content, knowledge_refs)
            artifact_enabled = any(skill["id"] == "file_artifact" for skill in active_skills)
            if artifact_kind and not artifact_enabled:
                self.send_error_json("本地文件产物技能未启用，请先在“技能和应用”中启用后再生成文件。", HTTPStatus.BAD_REQUEST)
                return
            if artifact_kind:
                execution_context["artifact_request"] = {"kind": artifact_kind, "target": "本地受控产物目录"}
            actual_model = execution_context["model"]
            execution_plan = build_execution_plan(content, active_skills, execution_context["tools"])
            run_id = new_id("run")
            conn.execute(
                """
                INSERT INTO runs (id, thread_id, status, model, started_at, skill_snapshot, execution_context, plan_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    thread_id,
                    "awaiting_confirmation" if artifact_kind else "running",
                    actual_model,
                    now(),
                    json.dumps(active_skills, ensure_ascii=False),
                    json.dumps(execution_context, ensure_ascii=False),
                    json.dumps(execution_plan, ensure_ascii=False),
                ),
            )
            conn.execute(
                "INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("event"), run_id, "started", "{}", now()),
            )
            conn.execute(
                "INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("event"), run_id, "execution_context", json.dumps({"model": actual_model, "task_tier": execution_context["task_tier"], "tool_ids": execution_context["allowed_tool_ids"]}, ensure_ascii=False), now()),
            )
            conn.execute(
                "INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("event"), run_id, "skill_routed", json.dumps({"route": execution_context["skill_route"], "skills": [skill["name"] for skill in active_skills]}, ensure_ascii=False), now()),
            )
            knowledge_event = "knowledge_retrieved" if knowledge_refs else (
                "knowledge_no_match" if task_profile["needs_knowledge"] else "knowledge_not_needed"
            )
            conn.execute(
                "INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("event"), run_id, knowledge_event, json.dumps({"count": len(knowledge_refs), "intent": task_profile["knowledge_intent"]["reason"]}, ensure_ascii=False), now()),
            )
            conn.execute(
                "INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("event"), run_id, "plan_created", json.dumps({"steps": execution_plan}, ensure_ascii=False), now()),
            )
            conn.executemany(
                """
                INSERT INTO run_steps (id, run_id, position, title, status, requires_confirmation, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (new_id("step"), run_id, index, step["title"], "awaiting_confirmation" if artifact_kind and index == 1 else "pending", 1 if artifact_kind and index == 1 else 0, now())
                    for index, step in enumerate(execution_plan, start=1)
                ],
            )
            if artifact_kind:
                request = artifact_confirmation_text(artifact_kind)
                conn.execute(
                    "INSERT INTO run_confirmations (run_id, request, status, created_at) VALUES (?, ?, ?, ?)",
                    (run_id, request, "pending", now()),
                )
                conn.execute(
                    "INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (new_id("event"), run_id, "confirmation_requested", json.dumps({"kind": artifact_kind, "target": "data/artifacts"}, ensure_ascii=False), now()),
                )

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        answer = ""
        reflection = {"applied": False, "passed": True, "issues": [], "summary": "未触发质量检查", "revision_count": 0}
        try:
            self.write_event("meta", {"thread_id": thread_id, "run_id": run_id, "model": actual_model})
            self.write_event("status", {"summary": event_summary("skill_routed", {"skills": [skill["name"] for skill in active_skills]})})
            self.write_event("status", {"summary": event_summary(knowledge_event, {"count": len(knowledge_refs)})})
            self.write_event("status", {"summary": event_summary("plan_created", {"steps": execution_plan})})
            if artifact_kind:
                self.write_event("confirmation", {"run_id": run_id, "request": artifact_confirmation_text(artifact_kind), "kind": artifact_kind})
                return
            with db() as conn:
                conn.execute(
                    "INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (new_id("event"), run_id, "model_request", json.dumps({"model": actual_model, "task_tier": execution_context["task_tier"]}), now()),
                )
                conn.execute(
                    "UPDATE run_steps SET status = ?, updated_at = ? WHERE run_id = ? AND position = 1",
                    ("running", now(), run_id),
                )
            def emit_runtime_event(event_type: str, payload: dict) -> None:
                with db() as event_conn:
                    event_conn.execute(
                        "INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                        (new_id("event"), run_id, event_type, json.dumps(payload, ensure_ascii=False), now()),
                    )
                self.write_event("status", {"summary": event_summary(event_type, payload)})

            draft_answer = "".join(stream_answer(thread_id, content, execution_context, emit_runtime_event))
            final_answer, reflection = reflect_answer(content, draft_answer, execution_context, emit_runtime_event)
            final_answer = append_knowledge_sources(final_answer, execution_context["knowledge_refs"], execution_context["knowledge_route"])
            answer = ""
            for chunk in chunk_text(final_answer, 12):
                answer += chunk
                self.write_event("delta", {"content": chunk})
            with db() as conn:
                conn.execute(
                    "INSERT INTO messages (id, thread_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                    (new_id("msg"), thread_id, "assistant", answer, now()),
                )
                conn.execute(
                    """
                    UPDATE runs
                    SET status = ?, completed_at = ?, reflection_snapshot = ?, input_tokens_estimate = ?, output_tokens_estimate = ?, tool_call_count = ?
                    WHERE id = ?
                    """,
                    (
                        "completed",
                        now(),
                        json.dumps(reflection, ensure_ascii=False),
                        estimate_tokens(content),
                        estimate_tokens(answer),
                        conn.execute("SELECT COUNT(*) AS count FROM run_events WHERE run_id = ? AND type = 'tool_call'", (run_id,)).fetchone()["count"],
                        run_id,
                    ),
                )
                conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now(), thread_id))
                conn.execute(
                    "UPDATE run_steps SET status = ?, updated_at = ? WHERE run_id = ? AND status IN ('pending', 'running')",
                    ("completed", now(), run_id),
                )
                conn.execute(
                    "INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (new_id("event"), run_id, "completed", json.dumps({"length": len(answer)}, ensure_ascii=False), now()),
                )
            self.write_event("done", {"content": answer})
            LOGGER.info("run_completed run_id=%s thread_id=%s model=%s", run_id, thread_id, actual_model)
        except Exception as exc:
            with db() as conn:
                conn.execute(
                    "UPDATE runs SET status = ?, completed_at = ?, error = ? WHERE id = ?",
                    ("failed", now(), str(exc), run_id),
                )
                conn.execute(
                    "INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (new_id("event"), run_id, "failed", json.dumps({"error": str(exc)}, ensure_ascii=False), now()),
                )
                conn.execute(
                    "UPDATE run_steps SET status = ?, error = ?, updated_at = ? WHERE run_id = ? AND status = 'running'",
                    ("failed", str(exc), now(), run_id),
                )
            self.write_event("error", {"error": str(exc)})
            LOGGER.warning("run_failed run_id=%s thread_id=%s error=%s", run_id, thread_id, str(exc)[:160])
        finally:
            # The browser can send again only after the SSE response ends.
            self.close_connection = True

    def write_event(self, event: str, data: dict) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        self.wfile.write(payload.encode("utf-8"))
        self.wfile.flush()


def public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "avatar_url": user.get("avatar_url", ""),
    }


def enabled_skills(user_id: str, thread_id: str = "", requested_skill_ids: list[str] | None = None) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT skill_id, enabled FROM user_enabled_skills WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    enabled = {row["skill_id"]: bool(row["enabled"]) for row in rows}
    selected = set(requested_skill_ids) if requested_skill_ids is not None else None
    if selected is None and thread_id:
        with db() as conn:
            thread_rows = conn.execute("SELECT skill_id FROM thread_selected_skills WHERE thread_id = ? AND selected = 1", (thread_id,)).fetchall()
        if thread_rows:
            selected = {row["skill_id"] for row in thread_rows}
    skills = []
    for skill in SKILLS:
        globally_enabled = enabled.get(skill["id"], skill["default_enabled"])
        selected_for_thread = skill["id"] in selected if selected is not None else True
        is_enabled = globally_enabled and selected_for_thread
        if is_enabled:
            skills.append({
                "id": skill["id"],
                "name": skill["name"],
                "prompt": skill["prompt"],
                "input_limit": skill["input_limit"],
                "kind": skill.get("kind", "prompt_skill"),
                "tool_ids": skill.get("tool_ids", []),
            })
    return skills


def enabled_skill_prompts(skills: list[dict]) -> list[str]:
    return [f"技能：{skill['name']}\n规则：{skill['prompt']}" for skill in skills]


def recent_messages(thread_id: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE thread_id = ? ORDER BY created_at ASC, id ASC",
            (thread_id,),
        ).fetchall()
        summary = conn.execute("SELECT context_summary FROM threads WHERE id = ?", (thread_id,)).fetchone()
        old_rows, recent_rows = rows[:-12], rows[-12:]
        if old_rows:
            compact = structured_conversation_summary(old_rows)
            if not summary or summary["context_summary"] != compact:
                conn.execute("UPDATE threads SET context_summary = ? WHERE id = ?", (compact, thread_id))
            return [{"role": "system", "content": f"早期对话结构化摘要：\n{compact}"}] + [row_to_dict(row) for row in recent_rows]
    return [row_to_dict(row) for row in rows]


def structured_conversation_summary(rows: list[sqlite3.Row]) -> str:
    user_messages = [row["content"] for row in rows if row["role"] == "user"]
    assistant_messages = [row["content"] for row in rows if row["role"] == "assistant"]
    goal = user_messages[0][:400] if user_messages else "未记录"
    constraints = [message[:180] for message in user_messages if any(marker in message for marker in ("要求", "不要", "必须", "限制", "格式"))][-3:]
    confirmed = assistant_messages[-2:]
    pending = user_messages[-1][:240] if user_messages else "无"
    return (
        f"用户目标：{goal}\n"
        f"已确认结论：{'；'.join(confirmed)[:700] or '无'}\n"
        f"约束：{'；'.join(constraints)[:500] or '无'}\n"
        f"最近待办：{pending}"
    )


def is_skill_inventory_question(content: str) -> bool:
    return bool(re.search(r"(?:你|平台|我).{0,8}(?:有|有哪些|有什么|具备).{0,8}(?:技能|能力)", content))


def build_system_prompt(execution_context: dict) -> str:
    system_prompt = "你运行在 Agent_Platform 中。请用中文回答，保持清晰、务实、可执行。不得编造资料来源、工具结果或未启用技能。"
    active_skills = execution_context["skills"]
    skill_prompts = enabled_skill_prompts(active_skills)
    if skill_prompts:
        system_prompt += "\n\n[技能规则]\n本次消息仅允许使用以下技能：\n" + "\n\n".join(skill_prompts)
    else:
        system_prompt += "\n\n[技能规则]\n本次消息没有启用技能。不得声称或使用任何技能。"
    tier_rules = {
        "quick": "直接回答重点，避免展开无关细节。",
        "standard": "先覆盖用户目标，再给出清晰结构和可执行建议。",
        "deep": "先明确范围、假设和结论结构；对不确定内容说明边界；输出完整、分层的结果。",
    }
    system_prompt += f"\n\n[任务规则]\n当前任务档位：{execution_context['task_tier']}。{tier_rules[execution_context['task_tier']]}"
    if execution_context["allowed_tool_ids"]:
        system_prompt += "\n\n[工具规则]\n仅在必要时调用当前提供的只读工具。工具结果仅作为事实依据，不能泄露敏感配置。"
    else:
        system_prompt += "\n\n[工具规则]\n本次任务未授权工具调用，请直接基于已提供上下文回答。"
    if any(skill["id"] == "file_artifact" for skill in active_skills):
        system_prompt += (
            "\n\n[本地文件产物]\n平台已启用本地 Markdown（.md）和 Excel（.xlsx）生成能力。"
            "当用户询问是否支持时，应明确回答支持；当用户明确要求生成时，平台会先展示确认操作，"
            "用户确认后才会写入 data/artifacts/ 并返回下载入口。不要对能力询问、模糊回复或“确定”声称已经弹出确认卡；"
            "只有平台实际返回确认卡后才能说明等待确认。不得声称已经生成，除非收到实际产物结果。"
        )
    references = execution_context.get("knowledge_refs", [])
    if references:
        source_text = "\n\n".join(f"资料：{item['filename']}\n内容：{item['excerpt']}" for item in references)
        system_prompt += "\n\n[本地资料]\n以下为本次检索到的资料片段。引用资料中的事实时，请在对应表述后标注资料名称；资料未覆盖的内容需说明是建议或推断。\n" + source_text
    elif execution_context.get("knowledge_route") == "required_no_match":
        system_prompt += "\n\n[资料边界]\n本次任务需要资料依据，但本地知识库没有命中内容。不得把模型常识说成已验证事实；请将结论表述为建议、假设或待验证项。"
    return system_prompt


def append_knowledge_sources(answer: str, references: list[dict], knowledge_route: str) -> str:
    labels = list(dict.fromkeys(f"{item['filename']}（片段 {item['position'] + 1}）" for item in references))
    if labels:
        return answer.rstrip() + "\n\n参考资料：" + "、".join(labels)
    if knowledge_route == "required_no_match":
        return answer.rstrip() + "\n\n说明：以下内容为基于任务描述的模型建议，未检索到可用本地资料，不应作为事实结论。"
    return answer


def requested_artifact_kind_from_content(content: str) -> str:
    """Recognize actual file-creation commands, not capability questions."""
    normalized = re.sub(r"\s+", "", content.lower())
    if artifact_kind_from_text(normalized) and normalized.endswith(("吗", "么", "？", "?")):
        return ""
    if re.search(r"(?:能否|是否|怎么|如何|支持|可以|可否|能不能|会不会).{0,12}(?:生成|创建|导出|保存)", normalized):
        return ""
    if not re.search(r"(?:生成|创建|导出|保存(?:为)?).{0,20}", normalized):
        return ""
    return artifact_kind_from_text(normalized)


def artifact_kind_from_text(content: str) -> str:
    normalized = re.sub(r"\s+", "", content.lower())
    if re.search(r"(?:\.xlsx\b|xlsx|excel|表格)", normalized):
        return "xlsx"
    if re.search(r"(?:\.md\b|markdown|md文件|md文档)", normalized):
        return "markdown"
    return ""


def requested_artifact_kind(content: str, thread_id: str = "") -> str:
    """Use an immediately preceding file type only for a short, explicit creation command."""
    kind = requested_artifact_kind_from_content(content)
    if kind or not thread_id:
        return kind
    normalized = re.sub(r"\s+", "", content.lower()).strip("。！!")
    if normalized not in {"生成", "创建", "导出", "保存", "生成文件", "创建文件"}:
        return ""
    with db() as conn:
        rows = conn.execute(
            "SELECT content FROM messages WHERE thread_id = ? AND role = 'user' ORDER BY created_at DESC, id DESC LIMIT 6",
            (thread_id,),
        ).fetchall()
    for row in rows:
        prior_kind = artifact_kind_from_text(row["content"])
        if prior_kind:
            return prior_kind
    return ""


def artifact_confirmation_text(kind: str) -> str:
    label = "Excel（.xlsx）" if kind == "xlsx" else "Markdown（.md）"
    return f"将根据本次任务生成 {label} 文件，并写入本机 data/artifacts/ 目录。确认后才会创建文件。"


def create_artifact(user_id: str, run_id: str, kind: str, source_content: str, answer: str) -> dict:
    if kind not in {"markdown", "xlsx"}:
        raise ValueError("不支持的文件类型")
    artifact_id = new_id("artifact")
    extension = ".xlsx" if kind == "xlsx" else ".md"
    filename = f"{artifact_id}{extension}"
    storage_dir = ARTIFACT_DIR / user_id
    storage_dir.mkdir(parents=True, exist_ok=True)
    path = (storage_dir / filename).resolve()
    if storage_dir.resolve() not in path.parents or path.exists():
        raise ValueError("文件产物路径无效")
    title = source_content.strip().splitlines()[0][:80] or "Agent_Platform 输出"
    try:
        if kind == "markdown":
            path.write_text(f"# {title}\n\n{answer.strip()}\n", encoding="utf-8")
        else:
            result = subprocess.run(
                [ARTIFACT_NODE, str(ARTIFACT_SCRIPT), str(path), title, answer],
                cwd=str(ROOT_DIR), text=True, capture_output=True, timeout=30,
            )
            if result.returncode != 0 or not path.exists():
                raise RuntimeError((result.stderr or result.stdout or "Excel 生成器未返回文件").strip()[:500])
            # artifact-tool may create an adjacent inspection file; it is not a user artifact.
            path.with_name(path.name + ".inspect.ndjson").unlink(missing_ok=True)
    except Exception:
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".inspect.ndjson").unlink(missing_ok=True)
        raise
    summary = f"由运行 {run_id} 生成的{'Excel' if kind == 'xlsx' else 'Markdown'}文件"
    with db() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, user_id, run_id, filename, kind, storage_path, summary, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (artifact_id, user_id, run_id, filename, kind, str(path), summary, now()),
        )
        conn.execute(
            "INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (new_id("event"), run_id, "artifact_created", json.dumps({"artifact_id": artifact_id, "filename": filename, "kind": kind}, ensure_ascii=False), now()),
        )
    return {"id": artifact_id, "filename": filename, "kind": kind, "summary": summary}


def complete_confirmed_artifact_run(run_id: str, user_id: str) -> dict:
    with db() as conn:
        run = conn.execute(
            "SELECT runs.* FROM runs JOIN threads ON threads.id = runs.thread_id WHERE runs.id = ? AND threads.user_id = ?",
            (run_id, user_id),
        ).fetchone()
        user_message = conn.execute(
            "SELECT content FROM messages WHERE thread_id = ? AND role = 'user' ORDER BY created_at DESC, id DESC LIMIT 1",
            (run["thread_id"],),
        ).fetchone() if run else None
        if not run or not user_message:
            raise ValueError("待确认运行不存在")
        context = json.loads(run["execution_context"] or "{}")
        request = context.get("artifact_request") or {}
        kind = request.get("kind")
        if kind not in {"markdown", "xlsx"}:
            raise ValueError("该运行没有可执行的文件产物请求")
        conn.execute("UPDATE runs SET status = ? WHERE id = ?", ("running", run_id))
        conn.execute("UPDATE run_steps SET status = ?, updated_at = ? WHERE run_id = ? AND status = 'awaiting_confirmation'", ("running", now(), run_id))
        conn.execute("INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)", (new_id("event"), run_id, "model_request", json.dumps({"model": run["model"]}), now()))

    def emit_runtime_event(event_type: str, payload: dict) -> None:
        with db() as event_conn:
            event_conn.execute(
                "INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id("event"), run_id, event_type, json.dumps(payload, ensure_ascii=False), now()),
            )

    try:
        source_content = user_message["content"]
        draft = "".join(stream_answer(run["thread_id"], source_content, context, emit_runtime_event))
        answer, reflection = reflect_answer(source_content, draft, context, emit_runtime_event)
        answer = append_knowledge_sources(answer, context.get("knowledge_refs", []), context.get("knowledge_route", ""))
        artifact = create_artifact(user_id, run_id, kind, source_content, answer)
        with db() as conn:
            conn.execute("INSERT INTO messages (id, thread_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)", (new_id("msg"), run["thread_id"], "assistant", answer, now()))
            conn.execute("UPDATE runs SET status = ?, completed_at = ?, reflection_snapshot = ?, input_tokens_estimate = ?, output_tokens_estimate = ?, tool_call_count = ? WHERE id = ?", ("completed", now(), json.dumps(reflection, ensure_ascii=False), estimate_tokens(source_content), estimate_tokens(answer), conn.execute("SELECT COUNT(*) AS count FROM run_events WHERE run_id = ? AND type = 'tool_call'", (run_id,)).fetchone()["count"], run_id))
            conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now(), run["thread_id"]))
            conn.execute("UPDATE run_steps SET status = ?, updated_at = ? WHERE run_id = ? AND status IN ('pending', 'running')", ("completed", now(), run_id))
            conn.execute("INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)", (new_id("event"), run_id, "completed", json.dumps({"length": len(answer)}, ensure_ascii=False), now()))
        return {"content": answer, "artifact": artifact}
    except Exception as exc:
        with db() as conn:
            conn.execute("UPDATE runs SET status = ?, completed_at = ?, error = ? WHERE id = ?", ("failed", now(), str(exc), run_id))
            conn.execute("UPDATE run_steps SET status = ?, error = ?, updated_at = ? WHERE run_id = ? AND status = 'running'", ("failed", str(exc), now(), run_id))
            conn.execute("INSERT INTO run_events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)", (new_id("event"), run_id, "failed", json.dumps({"error": str(exc)}, ensure_ascii=False), now()))
        raise


def stream_answer(thread_id: str, user_content: str, execution_context: dict, on_event) -> object:
    system_prompt = build_system_prompt(execution_context)

    if is_skill_inventory_question(user_content):
        names = "、".join(skill["name"] for skill in execution_context["skills"]) or "当前没有启用技能"
        artifact_note = "已启用本地 Markdown 和 Excel 文件生成，创建前需要确认。" if any(
            skill["id"] == "file_artifact" for skill in execution_context["skills"]
        ) else ""
        answer = f"当前可调用的技能：{names}。{artifact_note}"
        yield from chunk_text(answer, 10)
        return

    if DEEPSEEK_API_KEY:
        yield from run_deepseek_agent(thread_id, system_prompt, execution_context, on_event)
        return

    if "平台状态" in user_content or "系统状态" in user_content:
        tool_id = "platform_status"
        tool = LOCAL_TOOLS.get(tool_id)
        on_event("tool_call", {"tool_id": tool_id, "tool_name": tool.name, "arguments": {}})
        result = LOCAL_TOOLS.execute(tool_id, {}, set(execution_context["allowed_tool_ids"]))
        on_event("tool_result", {"tool_id": tool_id, "tool_name": tool.name, "summary": "已读取平台状态"})
        answer = f"当前平台状态：模型为 {result['model']}，DeepSeek 配置状态为 {'已连接' if result['deepseek_configured'] else '未配置'}，本地存储为 {result['storage']}。"
        yield from chunk_text(answer, 10)
        return

    mock = (
        "当前未配置 DeepSeek API Key，所以这是本地模拟回复。\n\n"
        f"我已收到你的问题：{user_content}\n\n"
        "第一版平台已经具备登录、对话、技能启用、应用展示和个人设置的基础闭环。"
        "配置 DEEPSEEK_API_KEY 后，这里会切换为真实模型的流式回复。"
    )
    for piece in chunk_text(mock, 10):
        time.sleep(0.03)
        yield piece


def should_reflect(content: str, execution_context: dict) -> bool:
    markers = ("方案", "调研", "报告", "文章", "计划", "分析", "总结", "复盘", "检查")
    return execution_context.get("quality_check", False) or len(content) >= 80 or any(marker in content for marker in markers)


def reflect_answer(user_content: str, draft_answer: str, execution_context: dict, on_event) -> tuple[str, dict]:
    if not should_reflect(user_content, execution_context):
        return draft_answer, {"applied": False, "passed": True, "issues": [], "summary": "普通任务，未触发质量检查", "revision_count": 0}

    on_event("reflection_started", {})
    if not DEEPSEEK_API_KEY:
        snapshot = {
            "applied": True,
            "passed": bool(draft_answer.strip()),
            "issues": [] if draft_answer.strip() else ["回答为空"],
            "summary": "已完成本地基础完整性检查",
            "revision_count": 0,
        }
        on_event("reflection_completed", snapshot)
        return draft_answer, snapshot

    evaluation_prompt = (
        "你是结果质量检查器。只返回 JSON 对象，不解释过程。"
        "检查最终回答是否覆盖用户目标、格式是否清晰、是否存在明显自相矛盾或未完成事项。"
        "JSON 字段必须为 passed(boolean)、issues(string数组，最多3项)、summary(string)。"
    )
    try:
        evaluation_message = deepseek_chat_turn([
            {"role": "system", "content": evaluation_prompt},
            {"role": "user", "content": f"用户任务：\n{user_content}\n\n待检查回答：\n{draft_answer}"},
        ], [], execution_context["model"], execution_context["max_output_tokens"])
    except RuntimeError:
        snapshot = {"applied": True, "passed": True, "issues": [], "summary": "质量检查暂不可用，保留原回答", "revision_count": 0}
        on_event("reflection_completed", snapshot)
        return draft_answer, snapshot
    assessment = parse_reflection(evaluation_message.get("content", ""))
    revision_count = 0
    answer = draft_answer
    if not assessment["passed"]:
        try:
            revision_message = deepseek_chat_turn([
                {"role": "system", "content": "根据质量检查修订回答。只输出修订后的最终回答，不展示检查过程或思维过程。"},
                {"role": "user", "content": f"用户任务：\n{user_content}\n\n原回答：\n{draft_answer}\n\n检查问题：\n" + "\n".join(assessment["issues"])},
            ], [], execution_context["model"], execution_context["max_output_tokens"])
            revised = (revision_message.get("content") or "").strip()
        except RuntimeError:
            revised = ""
        if revised:
            answer = revised
            revision_count = 1
            on_event("reflection_revised", {"summary": "已完成一次自动修订"})
    snapshot = {
        "applied": True,
        "passed": assessment["passed"],
        "issues": assessment["issues"],
        "summary": assessment["summary"],
        "revision_count": revision_count,
    }
    on_event("reflection_completed", snapshot)
    return answer, snapshot


def parse_reflection(content: str) -> dict:
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return {"passed": True, "issues": [], "summary": "质量检查未返回结构化结果，保留原回答"}
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"passed": True, "issues": [], "summary": "质量检查结果无法解析，保留原回答"}
    issues = payload.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    return {
        "passed": bool(payload.get("passed", True)),
        "issues": [str(issue)[:240] for issue in issues[:3]],
        "summary": str(payload.get("summary", "已完成质量检查"))[:240],
    }


def run_deepseek_agent(thread_id: str, system_prompt: str, execution_context: dict, on_event):
    messages = [{"role": "system", "content": system_prompt}] + recent_messages(thread_id)
    allowed_tool_ids = set(execution_context["allowed_tool_ids"])
    tools = LOCAL_TOOLS.callable_definitions(allowed_tool_ids)
    for _step in range(execution_context["max_tool_steps"]):
        message = deepseek_chat_turn(messages, tools, execution_context["model"], execution_context["max_output_tokens"])
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            content = (message.get("content") or "").strip()
            if not content:
                raise RuntimeError("DeepSeek 返回为空")
            yield from chunk_text(content, 12)
            return

        messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls})
        for call in tool_calls:
            function = call.get("function", {})
            tool_id = function.get("name", "")
            tool = LOCAL_TOOLS.get(tool_id)
            try:
                arguments = json.loads(function.get("arguments") or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("工具参数必须是对象")
                on_event("tool_call", {
                    "tool_id": tool_id,
                    "tool_name": tool.name if tool else tool_id,
                    "arguments": arguments,
                })
                result = LOCAL_TOOLS.execute(tool_id, arguments, allowed_tool_ids)
                on_event("tool_result", {
                    "tool_id": tool_id,
                    "tool_name": tool.name if tool else tool_id,
                    "summary": summarize_tool_result(result),
                })
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                result = {"error": str(exc)}
                on_event("tool_error", {
                    "tool_id": tool_id,
                    "tool_name": tool.name if tool else tool_id,
                    "error": str(exc),
                })
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", new_id("toolcall")),
                "content": json.dumps(result, ensure_ascii=False),
            })

    messages.append({"role": "system", "content": "工具调用已达到上限。请基于已获得的信息直接给出最终回答，不要再调用工具。"})
    message = deepseek_chat_turn(messages, [], execution_context["model"], execution_context["max_output_tokens"])
    content = (message.get("content") or "").strip()
    if not content:
        raise RuntimeError("工具调用达到上限且模型未返回最终回答")
    yield from chunk_text(content, 12)


def summarize_tool_result(result: dict) -> str:
    if "matches" in result:
        return f"找到 {result.get('count', len(result['matches']))} 个文件"
    if "service" in result:
        return "已读取平台状态"
    return "工具已返回结果"


def deepseek_chat_turn(messages: list[dict], tools: list[dict], model: str = DEEPSEEK_MODEL, max_output_tokens: int = MAX_RESPONSE_TOKENS) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.4,
        "max_tokens": max_output_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=deepseek_ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("choices", [{}])[0].get("message", {})
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"DeepSeek 请求失败：{exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        if "CERTIFICATE_VERIFY_FAILED" in reason:
            raise RuntimeError(
                "DeepSeek 请求失败：本机 HTTPS 证书校验失败。"
                "本地开发可在 .env 中设置 DEEPSEEK_SSL_VERIFY=false；"
                "生产环境建议安装正确 CA 证书后保持校验开启。"
            ) from exc
        raise RuntimeError(f"DeepSeek 请求失败：{reason}") from exc


def stream_deepseek(system_prompt: str, messages: list[dict]):
    request_messages = [{"role": "system", "content": system_prompt}]
    for message in messages:
        request_messages.append({"role": message["role"], "content": message["content"]})

    body = json.dumps(
        {
            "model": DEEPSEEK_MODEL,
            "messages": request_messages,
            "stream": False,
            "temperature": 0.4,
            "max_tokens": MAX_RESPONSE_TOKENS,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        ssl_context = deepseek_ssl_context()
        with urllib.request.urlopen(req, timeout=60, context=ssl_context) as response:
            payload = json.loads(response.read().decode("utf-8"))
            content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                raise RuntimeError("DeepSeek 返回为空")
            for piece in chunk_text(content, 12):
                yield piece
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"DeepSeek 请求失败：{exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        if "CERTIFICATE_VERIFY_FAILED" in reason:
            raise RuntimeError(
                "DeepSeek 请求失败：本机 HTTPS 证书校验失败。"
                "本地开发可在 .env 中设置 DEEPSEEK_SSL_VERIFY=false；"
                "生产环境建议安装正确 CA 证书后保持校验开启。"
            ) from exc
        raise RuntimeError(f"DeepSeek 请求失败：{reason}") from exc


def deepseek_ssl_context():
    if not DEEPSEEK_SSL_VERIFY:
        return ssl._create_unverified_context()
    if DEEPSEEK_CA_FILE:
        return ssl.create_default_context(cafile=DEEPSEEK_CA_FILE)
    if certifi:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


MODEL_ADAPTER = CallableModelAdapter(DEEPSEEK_MODEL, stream_deepseek)


def chunk_text(text: str, size: int):
    for index in range(0, len(text), size):
        yield text[index : index + size]


def main() -> None:
    init_db()
    port = int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), AgentPlatformHandler)
    print(f"Agent_Platform running at http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
