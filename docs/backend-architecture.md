# 后端架构边界

## 启动与入口

- 唯一服务启动入口：`python3 -m server`。
- 系统服务通过 `scripts/start-server.sh` 切换到项目根目录后执行同一入口。
- HTTP API 先经 `server/http_routes.py` 声明式路由表校验，再由 `server.app.AgentPlatformHandler` 做 HTTP/SSE 适配。

## 领域所有权

| 模块 | 负责内容 | 不应回流到 `app.py` 的内容 |
| --- | --- | --- |
| `auth_service.py` | 会话、登录、登出、邀请自动加入 | 用户/会话 SQL |
| `knowledge_service.py` | 资料作用域、存储、检索、编辑、删除 | 资料与分片 SQL |
| `space_service.py` | 项目空间、成员、邀请、聚合读取、访问控制 | 空间/成员 SQL |
| `chat_service.py` | 聊天请求校验、上下文冻结、Run 账本、运行终态、确认/取消 | Run、步骤、事件、确认状态机 SQL |
| `app.py` | HTTP 解析、响应序列化、SSE 写入、依赖装配、静态站点 | 上述领域写入与权限业务规则 |

## 禁止回流规则

1. 新增认证、知识库、空间或聊天状态机逻辑时，先扩展对应 Service，再由 Handler 调用；不得在 Handler 新增该领域 SQL。
2. 新增 API 必须先登记到 `http_routes.py`，再添加 Handler 适配；未登记路径必须返回 404。
3. 服务模块不得导入 `server.app`，以防循环依赖和全局状态回流；依赖通过构造参数或显式回调注入。
4. 新增可执行入口使用 `python -m server.<module>`；不得增加“包导入失败后退回本地导入”的兼容分支。
5. 任何 P41 后续改动至少运行对应领域回归、`py_compile`、`git diff --check`；涉及 HTTP 还需验证健康接口与静态首页。

## `app.py` 剩余职责

`app.py` 当前仍包含模型调用、工具执行、文件产物 I/O、提示词构建和 HTTP/SSE 适配。这些是下一阶段可继续拆分的技术编排能力；不得把已拆出的认证、资料、空间或 Run 状态机重新放回其中。
