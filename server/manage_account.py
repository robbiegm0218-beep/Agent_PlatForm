#!/usr/bin/env python3
"""Local-only account recovery commands for a personal hosted instance."""
from __future__ import annotations

import argparse

from server import app


def main() -> int:
    parser = argparse.ArgumentParser(description="管理个人托管实例账号")
    subparsers = parser.add_subparsers(dest="command", required=True)
    reset = subparsers.add_parser("create-password-reset", help="创建 30 分钟有效的一次性密码重置凭证")
    reset.add_argument("--email", required=True)
    reset.add_argument("--ttl-seconds", type=int, default=1800)
    args = parser.parse_args()
    app.init_db()
    if args.command == "create-password-reset":
        if not 60 <= args.ttl_seconds <= 86400:
            parser.error("ttl-seconds 必须在 60 到 86400 之间")
        token = app.AUTH_SERVICE.create_password_reset(args.email.strip().lower(), args.ttl_seconds)
        if not token:
            print("未找到对应账号；未创建重置凭证。")
            return 1
        print("一次性密码重置凭证（只显示本次，请勿写入日志）：")
        print(token)
        print(f"有效期：{args.ttl_seconds} 秒。使用后立即失效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
