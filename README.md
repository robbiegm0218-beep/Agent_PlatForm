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

## 回归测试

```bash
python3 -m unittest server.test_app -v
```

该测试使用临时数据库和本地模拟模型，覆盖连续对话、历史消息顺序，以及模型失败后的重试行为。

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
