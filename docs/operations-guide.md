# 个人托管操作指南

本文只记录需要在部署机器本地执行、会修改账号或数据的受控操作。执行前请确认当前目录是 Agent_Platform 项目根目录，并且不要把密码、重置凭证或 `.env` 内容粘贴到聊天、日志或公开渠道。

本文命令默认针对非 Docker 本地运行。Docker Compose 部署时，使用同名模块的容器命令，并始终指向 `/data`：

```bash
docker compose exec -T agent-platform python -m server.<module> <arguments>
```

例如创建账号使用 `docker compose exec -T agent-platform python -m server.manage_account ...`；以下涉及快照、恢复和删除的章节均给出 Docker 版本。

## 创建受邀测试用户

平台默认不提供公共注册。需要邀请个人测试用户时，由管理员在服务器本机执行：

```bash
python3 -m server.manage_account create-invited-user \
  --email tester@example.com \
  --name 测试用户 \
  --password '请替换为强且唯一的初始密码'
```

要求：

- 邮箱必须未被使用。
- 密码至少 10 个字符，且不应复用管理员或其他服务的密码。
- 命令只在本机创建账号，不会发送邮件、不会开放注册页面，也不会把密码写入应用日志。

成功后，通过独立安全渠道把邮箱和初始密码交给测试用户。建议用户首次登录后，进入“个人设置 → 修改密码”立即更换密码；管理员不应长期保留初始密码。

若邮箱已存在，命令不会覆盖账号或密码。需要协助恢复访问时，使用一次性重置凭证：

```bash
python3 -m server.manage_account create-password-reset --email tester@example.com
```

该凭证只显示一次，默认 30 分钟后失效，使用后立即作废。

## 创建限时邀请码

若希望由受邀者自行设置昵称和密码，而不是由管理员创建初始密码，可在服务器本机生成邀请码：

```bash
python3 -m server.manage_account create-trial-invitation \
  --email tester@example.com \
  --ttl-seconds 604800
```

邀请码仅显示一次、绑定指定邮箱、默认 7 天有效，并且完成注册后立即失效。平台不会开放通用注册；受邀者必须通过受控注册表单提交邀请码。

交付给受邀者时，只需说明以下步骤，不要在公共群组或问题单中发送邀请码：

1. 打开平台登录页，点击“使用邀请码注册”。
2. 输入收到的邀请码、**被邀请的同一邮箱**、自己的昵称和至少 10 位的新密码。
3. 提交成功后系统会自动登录；邀请码随即失效，不能重复使用。
4. 开始试用后，可在每次回答下标记“有帮助/没帮助”；含知识库资料的回答还可以评价每份引用。运行、时延和反馈仅以当前用户的汇总元数据进入试用指标，不读取对话或资料正文。

常见失败原因：邀请码过期或已使用、邮箱与受邀邮箱不一致、该邮箱已存在账号，或密码不足 10 位。需要重新发放时，在服务器本机重新执行创建命令；新邀请码会使该邮箱尚未使用的旧邀请码失效。

## 查看邀请试用情况

管理员登录后，打开任意对话的“运行详情”，切换到“试用概览”。页面仅汇总每位已注册受邀者的账号、Run 数、完成率、P95 时延、Token 估算、回答反馈和引用准确率；不展示对话、资料、附件、反馈备注或文档名称。该入口只对平台管理员显示。

## 创建升级快照

服务启动时，如检测到应用版本或数据库迁移变化，会自动创建包含数据库、知识库和产物的快照。过程结果会记录在 `data/upgrade-state.json`，其中只包含版本、时间、结果和快照位置，不包含对话或资料正文。

升级或进行高风险维护前，也可手动创建快照：

```bash
python3 -m server.upgrade prepare \
  --database agent_platform.db \
  --data-dir data \
  --backup-root data/upgrade-backups
```

Docker Compose 版本：

```bash
docker compose exec -T agent-platform python -m server.upgrade prepare \
  --database /data/agent_platform.db \
  --data-dir /data \
  --backup-root /data/upgrade-backups
```

请将输出的快照目录保存在受访问控制的位置。快照可能包含用户数据，不应提交到 Git 或上传到公开位置。

## 隔离恢复演练

恢复默认不会覆盖当前实例：

```bash
python3 -m server.upgrade restore \
  --snapshot data/upgrade-backups/<snapshot-directory>
```

Docker Compose 版本：

```bash
docker compose exec -T agent-platform python -m server.upgrade restore \
  --snapshot /data/upgrade-backups/<snapshot-directory>
```

命令会创建隔离恢复目录。先验证数据库、知识文件、产物和登录流程；只有确认无误且服务已停止时，才允许增加 `--replace` 覆盖生产数据。

## 数据删除申请的到期执行

账号删除在等待期结束后仍需管理员本机执行。先预览：

```bash
python3 -m server.account_deletion
```

确认输出无误后才执行：

```bash
python3 -m server.account_deletion --execute --confirmation DELETE_DUE_ACCOUNTS
```

Docker Compose 版本（先移除 `--execute` 进行预览）：

```bash
docker compose exec -T agent-platform python -m server.account_deletion \
  --execute --confirmation DELETE_DUE_ACCOUNTS
```

拥有其他成员的项目空间会阻断删除，需先处理空间归属。该命令不可逆，应先创建升级快照。

## 用户退出或停止试用

用户可以自行在“个人设置”中导出数据、申请删除账号；导出文件不含密码、会话令牌、本机存储路径和知识原文件。管理员处理停止试用时，建议按以下顺序执行：

1. 提醒用户先完成数据导出并下载所需产物。
2. 确认账户不存在待处理的项目空间归属问题。
3. 让用户提交删除申请；等待期结束后按上一节的显式确认命令执行。
4. 若整个个人实例不再使用，先创建升级快照，再停止本地服务；仅在确认无需保留任何用户数据后，再由实例所有者按其操作系统方式删除实例目录和备份。

平台不会把用户的对话、资料或文件正文上传给维护者；退出不依赖人工读取这些内容。
