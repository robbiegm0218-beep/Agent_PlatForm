# 个人试用准入清单

仅在以下项目完成后创建受邀测试用户。此阶段不开放公共注册，不承诺团队、多租户或企业级 SLA。

## 部署者确认

- [ ] 已设置管理员邮箱与强且唯一的管理员密码。
- [ ] 已确认模型供应商账号、费用承担人和每日/月度预算。
- [ ] 已确认备份目录的位置、访问权限和保留周期。
- [ ] 已运行 `scripts/security-baseline.sh`。
- [ ] Docker 部署已运行 `scripts/docker-operational-check.sh`，并处理所有阻断项；非 Docker 部署使用 `scripts/operational-check.sh`。
- [ ] 已完成一次隔离恢复演练：Docker 使用 `docker compose exec -T agent-platform python -m server.recovery_drill --database /data/agent_platform.db --data-dir /data`；非 Docker 使用 `python3 -m server.recovery_drill --database agent_platform.db --data-dir data`。

## 测试用户说明

- [ ] 用户知道资料、对话和产物存储在该个人实例中。
- [ ] 用户知道可在“个人设置”导出数据、申请删除账号。
- [ ] 用户知道知识库资料只在命中时用于当前对话；图片 OCR 在本机完成。
- [ ] 用户知道模型、网络搜索和 OCR 依赖不可用时，平台会明确提示失败或降级。
- [ ] 用户已被告知不要在对话或知识库中输入密码、密钥、身份证号等高敏感信息。

## 试用反馈与最小指标

记录版本、Run ID、错误类型、任务是否完成、回答是否有帮助和引用评价；不要默认收集或上传对话正文、知识正文、附件或密钥。每周查看本地运行监测中的 Run 失败率、P95 时延、磁盘与备份状态。

受邀者注册步骤和常见问题见[操作指南](operations-guide.md#创建限时邀请码)。

## 退出

用户可导出个人数据、停止使用；管理员应先创建升级快照，再按 [操作指南](operations-guide.md) 执行到期删除或实例停用。
