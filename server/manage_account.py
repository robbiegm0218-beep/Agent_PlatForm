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
    create = subparsers.add_parser("create-invited-user", help="在服务器本机创建受邀测试账号，不开放公共注册")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--password", required=True)
    invite = subparsers.add_parser("create-trial-invitation", help="创建限时、单次使用的邀请码")
    invite.add_argument("--email", required=True)
    invite.add_argument("--ttl-seconds", type=int, default=7 * 24 * 60 * 60)
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
    if args.command == "create-invited-user":
        email, name, password = args.email.strip().lower(), args.name.strip(), args.password
        if not email or "@" not in email or not name:
            parser.error("email 和 name 必须有效")
        error = app.validate_new_password(password)
        if error:
            parser.error(error)
        with app.db() as conn:
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                print("该邮箱已存在；未创建账号。")
                return 1
            user_id = app.new_id("user")
            conn.execute("INSERT INTO users (id, email, password_hash, name, created_at, is_admin) VALUES (?, ?, ?, ?, ?, 0)", (user_id, email, app.hash_password(password), name, app.now()))
            for skill in app.skill_snapshot():
                conn.execute("INSERT INTO user_enabled_skills (user_id, skill_id, enabled, updated_at) VALUES (?, ?, ?, ?)", (user_id, skill["id"], 1 if skill["default_enabled"] else 0, app.now()))
        print("受邀测试账号已创建。请通过独立安全渠道交付初始密码，并建议用户首次登录后修改密码。")
    if args.command == "create-trial-invitation":
        try:
            token = app.create_trial_invitation(args.email, args.ttl_seconds)
        except ValueError as exc:
            parser.error(str(exc))
        print("试用邀请码（只显示本次，请通过独立安全渠道交付）：")
        print(token)
        print(f"仅限 {args.email.strip().lower()} 使用；有效期：{args.ttl_seconds} 秒；注册后立即失效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
