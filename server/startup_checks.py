#!/usr/bin/env python3
"""Non-secret startup checks for a personal hosted instance."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path


def _directory_check(path: Path, create: bool = False) -> dict:
    try:
        if create:
            path.mkdir(parents=True, exist_ok=True)
        exists = path.is_dir()
        writable = exists and os.access(path, os.W_OK)
        return {"ok": bool(exists and writable), "exists": exists, "writable": writable}
    except OSError as exc:
        return {"ok": False, "exists": False, "writable": False, "error": str(exc)[:160]}


def build_startup_report(
    database: Path,
    knowledge_dir: Path,
    artifacts_dir: Path,
    model_configured: bool,
    node_binary: str = "",
    tesseract_binary: str = "",
    create_directories: bool = False,
) -> dict:
    checks = {
        "python": {"ok": sys.version_info >= (3, 10), "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"},
        "database_directory": _directory_check(database.parent, create_directories),
        "knowledge_directory": _directory_check(knowledge_dir, create_directories),
        "artifacts_directory": _directory_check(artifacts_dir, create_directories),
        "model": {"ok": model_configured, "required": False},
        "word_parser": {"ok": importlib.util.find_spec("docx") is not None, "required": False},
        "pdf_parser": {"ok": importlib.util.find_spec("pypdf") is not None, "required": False},
        "excel_runtime": {"ok": bool(node_binary and Path(node_binary).is_file()), "required": False},
        "image_ocr": {"ok": bool(tesseract_binary and Path(tesseract_binary).is_file()), "required": False},
    }
    required = ("python", "database_directory", "knowledge_directory", "artifacts_directory")
    return {
        "required_ready": all(checks[name]["ok"] for name in required),
        "optional_ready": all(item["ok"] for item in checks.values() if item.get("required") is False),
        "checks": checks,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    env_file = root / ".env"
    if env_file.exists():
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    data_dir = Path(os.environ.get("AGENT_DATA_DIR", root / "data")).expanduser()
    database = Path(os.environ.get("AGENT_DATABASE_PATH", root / "agent_platform.db")).expanduser()
    parser = argparse.ArgumentParser(description="检查个人托管实例的启动条件")
    parser.add_argument("--create-directories", action="store_true")
    args = parser.parse_args()
    report = build_startup_report(
        database,
        data_dir / "knowledge",
        data_dir / "artifacts",
        bool(os.environ.get("DEEPSEEK_API_KEY", "").strip()),
        shutil.which("node") or "",
        shutil.which("tesseract") or "",
        args.create_directories,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["required_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
