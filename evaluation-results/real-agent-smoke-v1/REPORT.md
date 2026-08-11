# DeepSeek V4 Flash 真实仓库 Smoke 报告

## 结论

本次不计入正式 324 次评测的端到端 smoke 通过。真实的 DeepSeek V4 Flash 通过 LCAH 自主读取仓库、定位缺陷、修改代码、运行测试并正常结束。公开测试和位于 agent workspace 外的隐藏 grader 均通过。

## 运行配置

- 模型：`deepseek-v4-flash`
- Provider：DeepSeek 官方 Anthropic-compatible API
- Agent：LCAH
- 审批策略：`auto`
- 最大工具步骤：20
- 单次最大输出：2048 tokens
- Run ID：`run_20260811-225215-90abd0`
- 正式评测计分：否

## 任务

修复 `safe_divide`：分母为零时返回 `None`，普通除法必须保留小数而不能执行整除。模型只能看到 `calculator.py` 和公开测试；隐藏 grader 位于 workspace 外。

## 结果

| 指标 | 结果 |
|---|---:|
| 严格任务判定 | PASS |
| 公开测试 | 2/2 通过 |
| 隐藏 grader | 3/3 通过 |
| 工具步骤 | 5 |
| 模型轮次 | 6 |
| 修改文件 | 1 |
| Runtime trace 事件 | 34 |
| Session 事件 | 43 |
| Provider 请求重试 | 0 |
| Stop reason | `final_answer_returned` |

模型的工具轨迹为：

```text
list_files → read_file → read_file → patch_file → run_shell
```

最终修改：

```diff
-    return numerator // denominator
+    return None if denominator == 0 else numerator / denominator
```

## 严格判定证据

- 初始公开测试：1 通过、1 失败。
- 修改后公开测试：2 通过、0 失败。
- 隐藏检查：`7 / 2 == 3.5`、`-3 / 2 == -1.5`、零分母返回 `None`，全部通过。
- Git diff whitespace 检查通过。
- 只修改 `calculator.py`，没有修改测试或 grader。
- Runtime 状态为 `completed`，停止原因为 `final_answer_returned`。
- Provider metadata 确认模型为 `deepseek-v4-flash`。

## Artifact

- `report.json`：LCAH 运行报告。
- `task_state.json`：任务状态、工具步骤和停止原因。
- `trace.jsonl`：完整 runtime trajectory。
- `result.json`：本次 smoke 的机器可读严格结果。

所有上传 artifact 均经过本次配置的 API key 精确值扫描，密钥不在结果中。

## 局限性

这只证明真实模型与 LCAH 的最小端到端执行链已经连通，不能代表 SWE-bench Lite 成绩，也不能证明上下文压缩、记忆或 checkpoint 的因果增益。正式结论仍需完成冻结后的配对实验。
