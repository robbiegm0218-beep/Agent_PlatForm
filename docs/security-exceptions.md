# 安全风险例外记录

仅记录当前无可用修复、无法立即消除且经验证存在缓解边界的漏洞。例外不是忽略告警：每条必须有复审日期和退出条件。

## SE-2026-001：giflib CVE-2026-26740

- 状态：临时接受，待上游修复。
- 记录日期：2026-07-22。
- 复审日期：2026-08-21。
- 最近一次 Scout 扫描镜像：`agent-agent-platform:latest`，digest 前缀 `c5cc8aecf376`，linux/arm64。后续发布若改变基础镜像、系统包或运行依赖，必须重新扫描后再更新本记录。
- 扫描结论：Docker Scout 为 0 Critical、1 High；受影响包为 Alpine `giflib 5.2.2-r1`，当前 `not fixed`。
- 触发条件：处理恶意构造的 GIF 图像时可能触发缓冲区溢出并造成拒绝服务；详见 [NVD CVE-2026-26740](https://nvd.nist.gov/vuln/detail/CVE-2026-26740)。
- 引入原因：本地 OCR 的 Tesseract 通过 Leptonica 链接 `libgif.so.7`；删除该库会使 OCR 无法启动。
- 不可达证据：知识库图片上传只允许 PNG、JPEG、WebP、TIFF；GIF 扩展名不在允许列表内，且 PNG/JPEG/WebP/TIFF 均校验文件签名。自动化测试覆盖 GIF 直接上传与 GIF 伪装为 PNG 两种拒绝情形。
- 缓解措施：上传大小、提取文本和 OCR 执行时间均有限制；OCR 在本地子进程中执行；不提供 GIF 文件生成或下载入口。
- 退出条件：Alpine 发布含修复的 `giflib` 包后，更新基础镜像并重新执行 Docker Scout；若产品未来需要支持 GIF，必须先移除此例外并增加独立隔离的图像解码方案。
