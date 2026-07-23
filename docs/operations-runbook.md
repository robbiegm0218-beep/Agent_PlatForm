# 个人托管故障处理

先停止写入操作，记录健康接口的 `X-Request-ID`，再执行对应步骤；不要把 `.env`、对话正文或知识文件发到外部排障渠道。

| 场景 | 判断 | 处理 |
| --- | --- | --- |
| 模型不可用 | 健康接口仍正常但模型未配置/上游报错 | 检查 `.env` 的模型配置、网络与供应商状态；恢复前平台仍可查看历史。 |
| 数据库不可写 | 健康接口 `database_ready=false` 或目录不可写 | 停止服务，检查磁盘与目录权限；用隔离恢复验证快照后再显式 `--replace`。 |
| 磁盘不足 | 健康接口 `startup.disk_space.ok=false` | 删除可确认的临时文件或扩容；不要删除数据库、知识库和产物目录。 |
| OCR 缺失 | 启动检查 `image_ocr` 未配置 | 安装 Tesseract 或改传 Markdown/TXT；图片不会上传外部。 |
| 升级失败 | 服务未启动或迁移未就绪 | 保留故障现场，使用升级快照进行隔离恢复；确认数据一致后再覆盖恢复。 |

日常执行：`scripts/operational-check.sh`；恢复演练：`python3 -m server.recovery_drill --database agent_platform.db --data-dir data`。两者都不会修改源实例。
