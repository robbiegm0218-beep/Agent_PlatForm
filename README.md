# Agent_Platform

一个面向个人与小团队的本地优先 Agent 平台。它保留了轻量技术栈：原生前端、Python 标准库 HTTP 服务、SQLite 和 DeepSeek；在不引入队列、Redis 或大型 Agent 框架的前提下，提供可流式交互、可审计、可恢复的单 Agent 执行闭环。

> 当前定位：可部署的单 Agent 平台，而不是多 Agent 编排或通用自动化平台。写入操作只覆盖受控的本地产物创建；已接入受限的只读 Remote MCP，外部写入与后台 Worker 尚未接入。

## 能力概览

| 面向用户的能力 | 底层保障 |
| --- | --- |
| 空间、任务、对话历史与 Markdown 回答渲染 | 空间可独立展开、排序，并在统一概览中查看关联任务、产物、知识库/网页来源和成员；任务可按空间归属或独立存在；空间成员支持本地邀请与移除（所有者受保护）；SQLite 持久化、PBKDF2-SHA256 密码散列、会话过期与按用户限流 |
| DeepSeek 默认模型与 OpenAI 兼容供应商接入、快速/标准/深度任务档位 | Provider 注册表、环境变量密钥隔离、确定性模型/工具路由、有限步 Agent Loop |
| Markdown、TXT、Word、PDF、Excel（XLSX）和图片知识库上传、检索与引用 | 仅注入命中片段；PDF 保留页码、Excel 保留工作表/单元格来源；PNG/JPG/WebP/TIFF 通过本机 Tesseract OCR 解析，不上传外部服务；资料按用户隔离，可删除 |
| JSON、Markdown、标准 Agent Skill ZIP 技能包管理 | 版本归档、启用/停用与回滚；ZIP 资源受限保存，脚本不会执行 |
| Markdown、Excel 文件产物 | 仅写入 `data/artifacts/` 受控目录；创建前必须确认；路径、类型与审计受限；“上面/上文内容生成文件”会复用上一条 Agent 回答作为文件正文；自动发现本机 Node 运行时以生成 Excel；可在所属空间聚合查看并追溯关联任务 |
| 运行详情、步骤、工具调用与取消 | Run 状态机、事件序号和版本、全局审计筛选；回答可评价“有帮助/没帮助”并记录原因；资料引用可逐文档评价准确性 |
| 平台状态、工作区文件名检索、可选网页检索 | 可解释的工具意图路由；优先 Tavily MCP、失败回退 REST；应用页可按 Schema 填参执行已注册的只读工具，失败可重试且保留安全审计摘要 |

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

每次对话都会建立一个 Run。对外状态使用 `running → awaiting_confirmation → running → completed / failed / cancelled` 的受限流转；内部阶段另行记录 `planning / retrieving / generating / executing_tool / reflecting` 等节点。每个步骤保留序列化输入输出、幂等键、超时、重试和恢复策略；事件带有稳定递增序号与版本，便于前端回放和问题排查。服务重启后，遗留的 `running` Run 会标记为可重试失败，待确认任务会保留。

## 前端结构与本地验证

前端保持原生 HTML/CSS/JavaScript，不依赖构建工具；`web/static/app.js` 负责页面入口与跨模块协调，具体能力按领域拆分：

- `core/`：共享状态、DOM 查询、请求封装与本地存储。
- `chat/`：输入区、流式 SSE、模型与执行方式、Markdown、运行过程及确认/重试。
- `knowledge/`、`space/`：资料库、项目空间成员、资料、对话与产物视图。
- `views/`：技能与应用、长期记忆、产物、设置及运行审计。
- `styles/`：按基础令牌、布局、组件、对话、项目空间、知识库和响应式规则分层；`styles.css` 仅负责按既有优先级加载这些层。

修改前端后可运行：

```bash
scripts/check-frontend.sh
```

该检查会校验所有前端模块语法，并验证令牌恢复、工作区状态、请求鉴权、SSE 解析与关键模块入口契约。

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
python3 -m server
# 端口被占用时，例如：PORT=8766 python3 -m server

# 由系统服务启动时使用 scripts/start-server.sh；它会切换到项目根目录后执行同一入口。
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

# P45 智能执行闭环：默认全部关闭。先只启用 shadow 收集对比数据。
AGENT_INTELLIGENCE_V2="false"
AGENT_PLANNER_MODE="off"       # off | shadow | active
AGENT_EVIDENCE_MODE="off"      # off | shadow | active
AGENT_ORCHESTRATOR_MODE="off"  # off | shadow | active
AGENT_VERIFIER_MODE="off"      # off | shadow | active
```

| 变量 | 作用 | 默认值 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek 密钥；缺失时使用本地模拟回复 | 空 |
| `DEEPSEEK_MODEL` / `DEEPSEEK_DEEP_MODEL` | 快速/深度任务的模型 | `deepseek-v4-flash` / `deepseek-v4-pro` |
| `DEEPSEEK_SSL_VERIFY` | HTTPS 证书校验 | `true` |
| `SESSION_TTL_SECONDS` | 登录会话有效期 | 14 天 |
| `RATE_LIMIT_PER_MINUTE` | 单用户每分钟请求上限 | 30 |
| `MAX_TOOL_STEPS` | 单次 Run 最大工具循环步数 | 4 |
| `AGENT_INTELLIGENCE_V2` | P45 总开关；关闭即回退既有 V1 流程 | `false` |
| `AGENT_*_MODE` | Planner、Evidence、Orchestrator、Verifier 分别控制为关闭、Shadow 或受控 Active | `off` |

本地排查证书问题时可临时设置 `DEEPSEEK_SSL_VERIFY=false`；生产环境应配置正确 CA 并保持校验开启。

### P45 灰度顺序

先启用 `AGENT_INTELLIGENCE_V2=true`，并将四个 `AGENT_*_MODE` 均设为 `shadow`。Shadow 不改变用户最终回答或工具执行，只记录 TaskFrame、证据判断和状态预演。积累至少 30 个 V2 Run 后执行：

```bash
python3 -m server.evaluate_p45_rollout --database agent_platform.db --output data/evaluations/p45-rollout.json
```

报告仅会建议进入管理员灰度，不会自动开启 Active。出现 `rollback` 时将 `AGENT_INTELLIGENCE_V2=false` 并重启服务即可回到 V1，历史 Run 不受影响。只有报告为 `administrator_canary` 后，才可由管理员将相应模式逐项改为 `active`。

回答评价与逐文档引用评价都会保存为用户隔离的 Run 元数据和审计事件。它们用于后续质量诊断、候选检索策略实验和版本对比，不会因单条评价直接改写模型回答或线上检索结果。

### 可选：接入 OpenAI 兼容供应商

DeepSeek 保持默认稳定路径。若需要增加其他 OpenAI Chat Completions 兼容供应商，可将供应商目录写入 `AGENT_MODEL_PROVIDERS`，密钥仍只通过各自的环境变量提供：

```bash
OPENAI_API_KEY="your_api_key"
AGENT_MODEL_PROVIDERS='[
  {
    "provider_id": "openai",
    "display_name": "OpenAI",
    "api_key_env": "OPENAI_API_KEY",
    "base_url": "https://api.openai.com/v1",
    "models": ["gpt-4.1-mini"]
  }
]'
```

平台只接受 HTTPS 地址、合法的模型 ID 和大写环境变量名称；不会从 JSON 中读取或保存密钥。外部模型默认不参与工具调用，出现工具意图时会自动回退到 DeepSeek。未设置对应 Key 时不发送网络请求，并保持本地模拟回复路径。

### 可选：启用受控网页检索

网页检索默认关闭。平台通过可解释的工具意图路由识别 URL、明确联网请求、时效性公开信息（如天气、新闻、价格）和外部资料/来源需求；普通问答不会联网。本地文件或工作区范围优先使用本地工具。

```bash
WEB_SEARCH_ENABLED="true"
WEB_SEARCH_API_KEY_ENV="TAVILY_API_KEY"
TAVILY_API_KEY="your_api_key"
WEB_SEARCH_ENDPOINT="https://api.tavily.com/search" # 可选，必须为 HTTPS
WEB_SEARCH_TIMEOUT_SECONDS="8"                       # 1-20 秒
WEB_SEARCH_MAX_RESULTS="5"                           # 1-10 条
MAX_CONTEXT_TOKENS="8000"                            # 自动续聊阈值
```

搜索结果只保存标题、链接和摘要，并写入本次 Run 的来源审计。未配置、超时或上游异常时，平台不会伪造来源，也不会发送密钥到页面或日志。上下文超过预算时会自动创建“（续）”对话并携带安全交接摘要；原对话保持完整历史。

### 可选：接入 Tavily Remote MCP

平台支持标准 MCP Streamable HTTP 生命周期（初始化、工具发现与调用），并将 Remote MCP 服务限制在显式白名单中。Tavily 是首个接入服务；当前只开放 `tavily_search`，MCP 调用失败时自动回退到上方 REST 搜索配置。

```bash
TAVILY_MCP_ENDPOINT="https://mcp.tavily.com/mcp/"
MCP_SERVERS='[
  {
    "id": "tavily",
    "url_env": "TAVILY_MCP_ENDPOINT",
    "query_api_key_env": "TAVILY_API_KEY",
    "query_api_key_param": "tavilyApiKey",
    "tool_allowlist": ["tavily_search"],
    "timeout_seconds": 10
  }
]'
```

地址和密钥均只从环境变量读取；完整带密钥 URL 不应写入代码、数据库、前端或 Git。MCP 客户端使用 HTTPS、协议版本、会话 ID、超时和响应大小限制；运行详情会记录工具判断与实际工具事件。

### 技能包兼容性与安全边界

上传入口兼容平台原有的 JSON / Markdown 技能，以及标准 Agent Skill ZIP 包。标准包可使用根目录或单层包装目录，并以 `SKILL.md` 为入口：其 YAML frontmatter 必须至少包含 `name` 与 `description`。可选资源包括 `references/`、`assets/`、`agents/openai.yaml` 和 `scripts/`。

技能和应用页提供原生文件选择与拖放导入，不依赖浏览器对 ZIP MIME 类型的筛选；文件选中后再执行格式判断与后端安全校验。仓库内的 [`examples/research-brief/`](examples/research-brief/) 是可用于打包导入验证的标准 Skill 示例目录。

`scripts/` 中的 Python、Shell、Node 或其他代码只会作为技能资源保存到受控目录，**不会自动执行，也不会因此获得工具权限**。需要执行代码时，必须通过后续受控工具、超时限制和人工确认流程，而不是通过上传技能包绕过安全边界。

## 生产启动

生产模式不会创建默认管理员。服务会在打开或修改数据库前校验管理员凭据：

```bash
export AGENT_PLATFORM_ENV="production"
export ADMIN_EMAIL="owner@example.com"
export ADMIN_PASSWORD="请使用高强度且唯一的密码"
export ADMIN_NAME="平台管理员" # 可选
export PORT="8765"             # 可选
python3 -m server
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
  server.test_app \
  server.test_model_registry \
  server.test_provider_config \
  server.test_task_router \
  server.test_evaluate_routing \
  server.test_knowledge_retrieval \
  server.test_evaluate_knowledge_retrieval \
  server.test_structured_context \
  server.test_evaluate_structured_context \
  server.test_memory_policy \
  server.test_evaluate_memory_policy \
  server.test_tool_risk \
  server.test_safe_web_reader \
  server.test_skill_contract \
  server.test_evaluate_skill_contracts -v

python3 server/evaluate.py
python3 server/evaluate.py \
  --baseline data/evaluations/latest.json \
  --output data/evaluations/after-change.json

python3 -m server.evaluate_routing
python3 -m server.evaluate_knowledge_retrieval
python3 -m server.evaluate_structured_context
python3 -m server.evaluate_memory_policy
python3 -m server.evaluate_skill_contracts
```

回归测试使用临时数据库与本地模型替身，覆盖流式响应、工具边界、审批与取消、运行审计、重启恢复、生产凭据、健康检查和数据库恢复演练。评测集位于 `server/evals/personal_baseline.json`，不会记录 API Key 或私有资料正文。

决策质量评测位于 [`docs/decision-quality.md`](docs/decision-quality.md)，用于固定评测 Planner、检索、澄清和项目空间边界；策略版本会冻结到每个 Run 的执行上下文中。

<!--
## 当前限制与下一步

- 当前是单进程、单 Agent 运行模型，适合交互式与分钟内完成的任务；不适合长时间后台工作、跨进程等待或高并发 Worker。
- 当前工具包含平台状态、工作区文件名与受限正文读取、安全 HTTPS 页面读取、Tavily 网页搜索和受限 Remote MCP 等只读能力。所有非只读工具默认不向模型暴露，必须通过风险策略和用户确认；文件产物已采用结构化、可恢复且幂等的审批流程。
- 工作区会在刷新完成认证、数据加载和原页面恢复后再显示，以避免页面闪烁；加载失败时会显示明确的错误状态。
- 当前仅接入 Tavily 的只读 Remote MCP 搜索工具；安全页面读取由本地受控读取器完成，不开放站点遍历。新增 MCP 服务前应验证白名单、超时、审计与故障隔离。
- SQLite 适合当前单机部署；当需要多实例写入、高并发或分布式 Worker 时，再评估迁移到服务化数据库和持久化执行框架。

详细的完成项与迭代顺序见 [实施计划](docs/implementation-plan.md)。
-->
