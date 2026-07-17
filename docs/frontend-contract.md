# 前端契约基线

## 入口与资源

- HTML 入口：`web/index.html`
- JavaScript 入口：`web/static/app.js`
- 样式入口：`web/static/styles.css`
- 后端 API 前缀：`/api/*`，认证令牌存储于 `agent_platform_token`
- 工作区 UI 状态键：`agent_platform_workspace_state`

## 页面与 DOM 稳定标识

以下 ID 在 P42 拆分期间保持不变：

- 页面：`loginView`、`workspaceView`、`chatPage`、`spacePage`、`skillsPage`、`settingsPage`、`knowledgePage`、`memoriesPage`、`artifactsPage`
- 导航/任务：`newThreadButton`、`threadList`、`threadSearch`、`threadTitle`、`messages`
- 对话：`chatForm`、`chatInput`、`sendButton`、`skillPickerButton`、`modelSelect`、`taskModeSelect`、`sourceModeSelect`、`knowledgeModeSelect`、`webModeSelect`、`fileModeSelect`
- 空间：`spaceTitle`、`spaceDetail`
- 运行详情：`runDetailsButton`、`runDrawer`、`runList`、`runDetail`

## 前端状态字段

`state` 至少保留：认证用户、任务/空间、当前任务、消息/Runs、技能、模型、资料、长期记忆、当前视图、流式状态与项目空间上下文。拆分后各模块可拥有局部状态，但通过共享状态模块读写这些同名字段。

## 事件与接口

- 对话使用 `POST /api/chat` 的 SSE：`meta`、`reasoning_summary`、`status`、`delta`、`confirmation`、`done`、`error`、`cancelled`。
- 页面刷新依赖 `/api/me`、`/api/threads`、`/api/folders`、`/api/skills`、`/api/models`、`/api/apps`、`/api/knowledge`、`/api/memories`、`/api/artifacts`。
- 401 必须清除令牌并回到登录页；页面恢复依赖 `agent_platform_workspace_state`。

## P42 回归门槛

每次迁移必须通过：`scripts/check-frontend.sh`、浏览器登录恢复、新建任务、项目空间、知识库和窄屏冒烟检查。
