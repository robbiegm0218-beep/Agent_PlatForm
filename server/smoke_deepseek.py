#!/usr/bin/env python3
"""Minimal authenticated DeepSeek deployment smoke check; never prints credentials."""
import argparse
import json
import os
import sys

try:
    from server.model_provider import DeepSeekConfig, DeepSeekProvider
except ModuleNotFoundError:
    from model_provider import DeepSeekConfig, DeepSeekProvider


def load_config() -> DeepSeekConfig:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise ValueError("必须设置 DEEPSEEK_API_KEY")
    return DeepSeekConfig(
        api_key=api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        ssl_verify=os.environ.get("DEEPSEEK_SSL_VERIFY", "true").lower() not in {"0", "false", "no"},
        ca_file=os.environ.get("DEEPSEEK_CA_FILE", ""),
    )


def run_smoke(config: DeepSeekConfig, model: str, dry_run: bool = False) -> dict:
    if dry_run:
        return {"ok": True, "dry_run": True, "base_url": config.base_url, "model": model, "ssl_verify": config.ssl_verify}
    result = DeepSeekProvider(config).complete(
        [{"role": "user", "content": "请回复 OK"}],
        [],
        model,
        # Reasoning-capable models can consume a few dozen tokens before the
        # final answer. Keep this inexpensive while leaving room for `OK`.
        128,
    )
    content = result.get("content", "").strip()
    if not content:
        raise RuntimeError("模型未返回内容")
    return {"ok": True, "dry_run": False, "model": model, "response_length": len(content)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent_Platform DeepSeek smoke check")
    parser.add_argument("--dry-run", action="store_true", help="仅校验配置，不发送模型请求")
    args = parser.parse_args()
    try:
        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
        print(json.dumps(run_smoke(load_config(), model, args.dry_run), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
