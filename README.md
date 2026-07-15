# Agent_Platform

个人使用的 Codex 风格 Agent 平台 MVP。

## 当前功能

- 登录
- 新建对话
- 流式回复
- 对话历史
- 内置技能展示与启用
- 应用展示
- 个人设置
- DeepSeek API 配置、模型路由和任务档位
- 可审计 Run 生命周期、稳定事件顺序与服务重启故障收敛
- 本地知识库：Markdown、TXT、Word 上传、检索、引用和删除（PDF 需安装 `pypdf`）
- 未配置 DeepSeek 时本地模拟回复

## 启动

```bash
python3 server/app.py
```

打开：

```text
http://localhost:8765
```

默认账号：

```text
邮箱：admin@example.com
密码：admin123
```

## 生产启动

生产环境不会创建默认 `admin@example.com / admin123` 账号，必须显式配置首个管理员：

```bash
export AGENT_PLATFORM_ENV="production"
export ADMIN_EMAIL="owner@example.com"
export ADMIN_PASSWORD="请使用高强度且唯一的密码"
export ADMIN_NAME="平台管理员" # 可选
python3 server/app.py
```

`/api/health` 不需要登录，可供部署探针检查 SQLite 是否可用。应用默认只监听本机地址；正式对外服务时，应由反向代理提供 HTTPS、访问控制与日志留存，不要直接暴露开发进程。

若部署环境不由容器或进程管理器收集标准输出，可启用本地日志轮转：

```bash
export AGENT_LOG_FILE="/var/log/agent-platform/app.log"
export AGENT_LOG_MAX_BYTES="10485760" # 单个文件上限，默认 10 MiB
export AGENT_LOG_BACKUP_COUNT="5"      # 保留轮转文件数量，默认 5
```

## DeepSeek 配置

也可以在项目根目录创建 `.env`（已加入 Git 忽略规则）：

```bash
DEEPSEEK_API_KEY="your_api_key"
DEEPSEEK_BASE_URL="https://api.deepseek.com"
DEEPSEEK_MODEL="deepseek-v4-flash"
DEEPSEEK_DEEP_MODEL="deepseek-v4-pro"
DEEPSEEK_SSL_VERIFY="true"
# 可选：指定自定义 CA 证书文件
DEEPSEEK_CA_FILE="/path/to/ca.pem"
```

或通过当前终端环境变量配置：

```bash
export DEEPSEEK_API_KEY="your_api_key"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-v4-flash"
export DEEPSEEK_DEEP_MODEL="deepseek-v4-pro"
export DEEPSEEK_SSL_VERIFY="true"
# 可选：export DEEPSEEK_CA_FILE="/path/to/ca.pem"
python3 server/app.py
```

如果没有配置 `DEEPSEEK_API_KEY`，系统会使用本地模拟回复，前台交互仍然可完整测试。

如果本地 Python 环境出现 `CERTIFICATE_VERIFY_FAILED`，可以临时设置：

```bash
DEEPSEEK_SSL_VERIFY="false"
```

这只建议用于本地开发。正式部署时应安装正确 CA 证书，并保持 `DEEPSEEK_SSL_VERIFY="true"`。

## 部署验收命令

以下命令都不会输出 API Key 或私有对话内容：

```bash
# 仅校验 DeepSeek 配置，不发送请求
python3 server/smoke_deepseek.py --dry-run

# 在目标部署环境发送一次最小真实模型请求
python3 server/smoke_deepseek.py

# 备份、恢复到临时目录并校验 SQLite 完整性和关键表计数；不会修改源数据库
python3 server/recovery_drill.py --database agent_platform.db
```

## 回归测试

```bash
python3 -m unittest server.test_agent_runtime server.test_model_provider server.test_tool_policy server.test_agent_loop server.test_extensions server.test_operations server.test_app -v
```

该测试使用临时数据库和本地模拟模型，覆盖连续对话、运行审计、取消、审批、健康检查、生产启动凭据校验和数据库恢复演练。

## 本地评测

```bash
python3 server/evaluate.py
python3 server/evaluate.py --baseline data/evaluations/latest.json --output data/evaluations/after-change.json
```

评测集位于 `server/evals/personal_baseline.json`。默认只验证可重复的任务路由，并输出每条任务的人工质量评分标准，不会发送模型请求或记录 API Key、私有资料正文。

## 本地备份与恢复

```bash
python3 server/backup.py backup ~/Agent_Backups/agent-platform.db
python3 server/backup.py restore ~/Agent_Backups/agent-platform.db
```

密码会在用户下次成功登录时从旧格式自动迁移到 PBKDF2-SHA256。会话默认有效期为 14 天，可通过 `SESSION_TTL_SECONDS` 调整。
