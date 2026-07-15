# Agent_Platform

一个面向个人与小团队的本地优先 Agent 平台。它保留了轻量技术栈：原生前端、Python 标准库 HTTP 服务、SQLite 和 DeepSeek；在不引入队列、Redis 或大型 Agent 框架的前提下，提供可流式交互、可审计、可恢复的单 Agent 执行闭环。

> 当前定位：可部署的单 Agent 平台，而不是多 Agent 编排或通用自动化平台。写入操作只覆盖受控的本地产物创建；外部写入、通用 MCP 与后台 Worker 尚未接入。

## 能力概览

| 面向用户的能力 | 底层保障 |
| --- | --- |
| 登录、会话、文件夹、对话历史与 Markdown 回答渲染 | SQLite 持久化、PBKDF2-SHA256 密码散列、会话过期与按用户限流 |
| DeepSeek 流式对话、快速/标准/深度任务档位、技能启用 | Provider 与 SSE 解析独立、确定性模型/工具路由、有限步 Agent Loop |
| Markdown、TXT、Word、可选 PDF 知识库上传、检索与引用 | 仅注入命中片段；资料按用户隔离，可删除 |
| Markdown、Excel 文件产物 | 仅写入 `data/artifacts/` 受控目录；创建前必须确认；路径、类型与审计受限 |
| 运行详情、步骤、工具调用与取消 | Run 状态机、事件序号和版本、服务重启时遗留运行自动收敛 |
| 平台状态、工作区文件名检索 | 最小权限工具策略；当前只向模型暴露匹配意图的只读工具 |

## 架构与执行边界

```text
浏览器（原生 HTML / JS）
        │  SSE
Python HTTP 服务 ── Agent Loop ── DeepSeek Provider
        │              │
      SQLite        只读本地工具
        │
资料库 / 受控产物目录 / Run 审计事件
```

每次对话都会建立一个 Run。Run 使用 `running → awaiting_confirmation → running → completed / failed / cancelled` 的受限状态流转；事件带有稳定递增序号与版本，便于前端回放和问题排查。服务重启后，遗留的 `running` Run 会标记为可重试失败，待确认任务会保留。

## 快速开始（开发）

### 前置条件

- Python 3.10+
- Node.js 18+（仅 Excel 产物生成需要）

安装可选解析与 Excel 依赖：

```bash
python3 -m pip install python-docx pypdf certifi
npm install
```

其中 `python-docx` 用于 Word，`pypdf` 用于 PDF；未安装时对应文件类型不可用，其他能力不受影响。

启动服务：

```bash
python3 server/app.py
# 端口被占用时，例如：PORT=8766 python3 server/app.py
```

打开 `http://localhost:8765`。开发环境默认账号：

```text
邮箱：admin@example.com
密码：admin123
```

未配置 DeepSeek 时，平台使用本地模拟回复，前端、Run、知识库和审批流程仍可完整验证。

## 模型配置

在项目根目录创建 `.env`（已被 Git 忽略）或设置环境变量：

```bash
DEEPSEEK_API_KEY="your_api_key"
DEEPSEEK_BASE_URL="https://api.deepseek.com"
DEEPSEEK_MODEL="deepseek-v4-flash"
DEEPSEEK_DEEP_MODEL="deepseek-v4-pro"
DEEPSEEK_SSL_VERIFY="true"
# 可选：DEEPSEEK_CA_FILE="/path/to/ca.pem"
```

| 变量 | 作用 | 默认值 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek 密钥；缺失时使用本地模拟回复 | 空 |
| `DEEPSEEK_MODEL` / `DEEPSEEK_DEEP_MODEL` | 快速/深度任务的模型 | `deepseek-v4-flash` / `deepseek-v4-pro` |
| `DEEPSEEK_SSL_VERIFY` | HTTPS 证书校验 | `true` |
| `SESSION_TTL_SECONDS` | 登录会话有效期 | 14 天 |
| `RATE_LIMIT_PER_MINUTE` | 单用户每分钟请求上限 | 30 |
| `MAX_TOOL_STEPS` | 单次 Run 最大工具循环步数 | 4 |

本地排查证书问题时可临时设置 `DEEPSEEK_SSL_VERIFY=false`；生产环境应配置正确 CA 并保持校验开启。

## 生产启动

生产模式不会创建默认管理员。服务会在打开或修改数据库前校验管理员凭据：

```bash
export AGENT_PLATFORM_ENV="production"
export ADMIN_EMAIL="owner@example.com"
export ADMIN_PASSWORD="请使用高强度且唯一的密码"
export ADMIN_NAME="平台管理员" # 可选
export PORT="8765"             # 可选
python3 server/app.py
```

服务默认仅监听 `127.0.0.1`。对外部署时应通过反向代理提供 HTTPS、访问控制、进程守护和标准输出日志收集；不要直接暴露开发进程。

若未使用容器或进程管理器收集标准输出，可开启有界的本地日志轮转：

```bash
export AGENT_LOG_FILE="/var/log/agent-platform/app.log"
export AGENT_LOG_MAX_BYTES="10485760" # 单个文件上限，默认 10 MiB
export AGENT_LOG_BACKUP_COUNT="5"      # 轮转文件数量，默认 5
```

`GET /api/health` 不需要登录。SQLite 可用时返回 `200` 与 `database_ready: true`；不可用时返回 `503`，可直接作为部署健康探针。

## 数据、备份与部署验收

运行数据默认保存在项目根目录的 `agent_platform.db`；知识库和产物位于 `data/knowledge/`、`data/artifacts/`。这些路径及 `.env` 已被 Git 忽略，应纳入部署环境的备份策略。

```bash
# 创建或恢复一致性的 SQLite 备份
python3 server/backup.py backup ~/Agent_Backups/agent-platform.db
python3 server/backup.py restore ~/Agent_Backups/agent-platform.db

# 在临时目录执行备份→恢复→完整性与关键表计数校验，不修改源数据库
python3 server/recovery_drill.py --database agent_platform.db

# 仅校验 DeepSeek 配置，不发送网络请求
python3 server/smoke_deepseek.py --dry-run

# 在目标部署环境发送一次最小真实模型请求；不会输出密钥或对话内容
python3 server/smoke_deepseek.py
```

## 测试与评测

```bash
python3 -m unittest \
  server.test_agent_runtime \
  server.test_model_provider \
  server.test_tool_policy \
  server.test_agent_loop \
  server.test_extensions \
  server.test_operations \
  server.test_app -v

python3 server/evaluate.py
python3 server/evaluate.py \
  --baseline data/evaluations/latest.json \
  --output data/evaluations/after-change.json
```

回归测试使用临时数据库与本地模型替身，覆盖流式响应、工具边界、审批与取消、运行审计、重启恢复、生产凭据、健康检查和数据库恢复演练。评测集位于 `server/evals/personal_baseline.json`，不会记录 API Key 或私有资料正文。

## 当前限制与下一步

- 当前是单进程、单 Agent 运行模型，适合交互式与分钟内完成的任务；不适合长时间后台工作、跨进程等待或高并发 Worker。
- 当前工具仅包含平台状态和工作区文件名检索等只读能力。文件产物采用独立的受控审批流程；通用 `write_local`、`external_write`、`privileged` 工具审批将在真实工具接入时统一实现。
- 首个 MCP 服务尚未接入。接入时将先选择只读服务，并验证白名单、超时、审计与故障隔离。
- SQLite 适合当前单机部署；当需要多实例写入、高并发或分布式 Worker 时，再评估迁移到服务化数据库和持久化执行框架。

详细的完成项与迭代顺序见 [实施计划](docs/implementation-plan.md)。
