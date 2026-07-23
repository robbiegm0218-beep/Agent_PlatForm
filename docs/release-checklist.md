# 个人托管发布前检查清单

适用范围：邀请制个人测试，不开放公共注册，不作为企业级 SLA 或多租户 SaaS 发布。

## 部署与账号

- [ ] `.env` 已设置 `AGENT_PLATFORM_ENV=production`、管理员邮箱和强且唯一的管理员密码。
- [ ] `.env` 不在 Git、截图、聊天记录或公开日志中；如曾泄露模型密钥或管理员密码，已完成轮换。
- [ ] `docker compose config` 通过，`docker compose up -d --build` 后 `docker compose ps` 显示 `healthy`。
- [ ] `curl http://127.0.0.1:8765/api/health` 返回 `ok: true`。
- [ ] 端口仅绑定 `127.0.0.1:8765`；如需外网访问，另行在受控 HTTPS 反向代理层配置认证与访问限制。

## 数据与恢复

- [ ] 已创建升级快照：`docker compose exec -T agent-platform python -m server.upgrade prepare --database /data/agent_platform.db --data-dir /data --backup-root /data/upgrade-backups`。
- [ ] 已执行隔离恢复演练，确认数据库、知识库、产物和登录均可恢复。
- [ ] 已确认 Docker 命名卷、快照目录的访问权限和保留周期；自动任务不会自行删除备份。
- [ ] 已运行 `scripts/docker-operational-check.sh`，没有 critical 告警。

## 安全与能力

- [ ] 已运行 `scripts/security-baseline.sh`。
- [ ] Docker Scout 最终结果为 0 Critical；High 仅允许有 [安全风险例外记录](./security-exceptions.md) 中可复审的条目。
- [ ] 已验证管理员登录、一次模型对话、知识库引用、Markdown/Excel 文件产物和容器重启后的数据持久化。
- [ ] 已确认每日/月度任务和 Token 预算符合承担费用的一方预期。

## 邀请与反馈

- [ ] 测试用户已获知数据存储位置、模型费用责任、数据导出/删除入口和已知限制。
- [ ] 仅通过邀请码或受控本机命令创建测试账号；不开放公共注册。
- [ ] 已约定问题反馈渠道，反馈默认不上传对话、知识资料、附件或密钥正文。
