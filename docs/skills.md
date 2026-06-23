# Skills

Skill 是一段写在 markdown 文件里的可复用 prompt，可以通过 `/skill-name [args]` 调用。lcah 把它展开成一次普通 session 请求，沿用同一套工具、审批和事件链路。

## 内置 skill

- `/review` — 代码审查当前改动
- `/test` — 跑测试、整理失败原因
- `/commit` — 准备 commit 消息和拆分建议
- `/simplify` — 找代码冗余并修

```bash
lcah
> /review
↳ Bash(git diff) ✓
代码审查：3 处可简化，1 处有遗漏的错误处理...
```

## 加载顺序

后加载的同名 skill 覆盖前面的：

1. **内置 skill** — lcah 自带
2. **用户 skill** — `~/.lcah/skills/<name>/SKILL.md`
3. **项目 skill** — `<repo>/skills/<name>/SKILL.md` 或 `<repo>/.lcah/skills/<name>/SKILL.md`

## 自定义一个 skill

最小例子，新建 `~/.lcah/skills/deploy/SKILL.md`：

```markdown
---
name: deploy
description: 部署前清单
argument-hint: target
allowed-tools: read_file, search
---

请检查仓库是否满足部署到 $ARGUMENTS 环境的条件：

1. tests/ 通过
2. CHANGELOG 包含本次发布条目
3. 配置文件里 production endpoint 没有指向 dev
```

调用：

```text
> /deploy staging
```

`$ARGUMENTS` 会被替换为 `staging`。`${LCAH_SKILL_DIR}` 会被替换为 skill 文件所在目录的绝对路径。

## Frontmatter

```yaml
---
name: skill-name              # 必填，slash 命令名
description: 一句话描述        # 必填，/skills 列表显示
when-to-use: 适用场景          # 可选，给模型的提示
argument-hint: target          # 可选，help 提示用
arguments: target=str          # 可选，命名参数
context: inline                # inline（默认）| fork
allowed-tools: read_file, search  # 可选，限制本次 skill 调用能用的工具
paths: src/*.py, tests/*.py    # 可选，把这些路径作为相关文件提示给模型
disable-model-invocation: true # 可选，只渲染 prompt 不发请求
model: claude-sonnet-4-6       # 可选，强制使用特定模型
user-invocable: true           # 可选，是否允许用户从 REPL 直接调用
---
```

## context: inline vs fork

- `inline`（默认）：skill 内容直接 append 到当前 session 的下一轮请求里。模型记得之前对话。
- `fork`：起一个隔离 session 跑 skill，主 session 不受污染。适合"和当前对话无关的一次性查询"。

## allowed-tools

如果一个 skill 只需要只读分析（如 `/review`），可以加 `allowed-tools: read_file, search, list_files`，让 skill 调用时模型看不到 write/shell。提高执行安全。

## paths

帮模型快速找到相关文件：

```yaml
paths: src/**/*.py, !src/legacy/**
```

支持 glob，前缀 `!` 表示排除。

## 调试

- `/skills` 列出所有可用 skill 和加载来源
- `/auto-skills` 列出 `.lcah/skills/` 下由 auto-skills 工具维护的项目 skill
- skill 执行时，事件流里会有 `skill_invoked` / `skill_finished`
- 用 `disable-model-invocation: true` 配合 `lcah --tui` 可以在不发请求的情况下预览 skill 展开后的 prompt

## Auto-Skills

lcah 也支持一个轻量的 auto-skills 生命周期，参考 MUSE-Autoskill 的
creation、memory、management、evaluation、refinement 思路：

- `skill_create`：创建 `.lcah/skills/<name>/SKILL.md`，可同时写入 `tests/test_skill.py`
- `skill_eval`：运行该 skill 的 `tests/`，并把结果写入 `.memory.md`
- `find_skill`：按 query 检索 skill catalog 和 skill-level memory
- `read_skill`：按需读取完整 `SKILL.md` 和 `.memory.md`
- `update_skill`：根据反馈更新 skill 文档或测试
- `skill_note`：追加每个 skill 自己的经验记忆

创建成功后，lcah 会刷新 skill catalog，后续可直接通过 `/skill-name` 调用。
`.memory.md` 不进入 skill 本体迁移包，表示本 agent 在本仓库里积累的使用经验。

### 示例验证

运行离线示例，不需要真实模型 key：

```bash
uv run python scripts/run_auto_skill_examples.py
```

这个脚本会在临时工作区里创建两个领域 skill：

- `csv-summary`：CSV header、行数、缺失值总结流程
- `json-audit`：JSON required fields 和 malformed records 审计流程

它会输出 JSON 报告，验证几类提升信号：

- `created.*_passed`：新 skill 通过单元测试后才注册
- `retrieval.*_hits_*`：相似任务能命中对应 skill，减少重新探索
- `retrieval.json_memory_used_in_routing`：skill-level memory 会参与检索
- `reuse.skill_prompt_loaded`：slash 调用会加载已注册 skill 流程
- `safety_gate.broken_skill_not_registered`：失败 skill 被门禁挡在 catalog 外
