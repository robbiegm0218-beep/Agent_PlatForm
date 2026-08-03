# 个人托管发布前检查清单

适用范围：邀请制个人测试，不开放公共注册，不作为企业级 SLA 或多租户 SaaS 发布。

## 本地源码配置中心门禁

- [ ] `scripts/check-knowledge-configuration-release.sh` 全部通过。
- [ ] 普通用户只看到“概览 / 我的检索 / 索引与迁移”，且全局治理 API 返回 403。
- [ ] 知识库管理员可维护处理预设，但不能创建、发布或回滚全局检索策略。
- [ ] 平台管理员已演练候选评测、发布与回滚；活动策略最终恢复到预期稳定版本。
- [ ] Embedding 默认关闭时不发起外部请求，页面明确显示 FTS5/BM25 回退。
- [ ] 历史迁移已演练暂存、Shadow、25%、回滚和 100%，文档数量及 ACL 指纹不变。
- [ ] 桌面和窄屏下左侧导航固定、配置区独立滚动、无横向溢出和控制台错误。
- [ ] 本地灰度通过前不更新 Docker；是否构建镜像由实例所有者另行确认。

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
