# 决策质量评测

P43 使用确定性、可复现的离线评测来判断 Planner、资料检索和路由是否需要调整。默认评测不会调用模型 API，也不会将对话正文、资料正文、用户 ID、令牌或密钥写入报告。

## 指标与边界

- 检索遗漏率：标注为“应检索”的用例中未触发检索的比例。
- 过检索率：标注为“不应检索”的用例中触发检索的比例。
- 澄清遗漏率：标注为“应澄清”的用例中未要求澄清的比例。
- 任务成功率：路由、检索、澄清与项目/通用空间边界均命中固定标签的比例。
- 引用准确率：仅使用用户显式提交的 `citation_correct` 聚合值；没有评价时不推断。

匿名 Run 导出只保留经盐化的 Run/任务标识、模型、状态、档位、资料路由、命中数量、空间类型和策略版本；不导出 prompt、回答、资料片段、用户 ID 或来源 URL。离线报告默认写入本机 `data/evaluations/`（已忽略），建议仅保留 30 天。

## 运行

```bash
python3 -m server.evaluate_decision_quality \
  --output data/evaluations/decision-quality.json

# 可选：添加本机 Run 与引用反馈的聚合统计；不读取消息正文。
python3 -m server.evaluate_decision_quality \
  --database agent_platform.db \
  --output data/evaluations/decision-quality-with-feedback.json
```

固定集位于 `server/evals/decision_quality.json`，其中包含应检索、不应检索、应澄清与项目空间隔离用例。每次策略调整只能声明一个变量；若任一质量门槛回退，则实验结论为 `rollback`。引用反馈少于 20 条或完成任务少于 30 条时，报告会明确标记“样本不足”，不得声称策略提升。

通过的策略由 `decision_policy.version` 冻结到每个 Run 的 `execution_context`，因此历史运行可追溯当时使用的决策规则。
