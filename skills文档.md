# pico-v3 Skills 系统文档

Skills 是 pico-v3 中一个可复用的 prompt 工作流系统。每个 skill 是一段 markdown 文件，包含 frontmatter 元数据与 prompt 正文，可以通过 `/skill-name [args]` 从 REPL 或 TUI 调用。Skill 的展开、执行、工具限制和模型切换全部由 runtime 管线统一处理。

---

## 目录

1. [架构概览](#1-架构概览)
2. [Skill 数据模型](#2-skill-数据模型)
3. [Skill 文件格式](#3-skill-文件格式)
4. [发现与加载](#4-发现与加载)
5. [内置 Skills](#5-内置-skills)
6. [自定义 Skill](#6-自定义-skill)
7. [Prompt 注入机制](#7-prompt-注入机制)
8. [执行引擎](#8-执行引擎)
9. [上下文预算管理](#9-上下文预算管理)
10. [Slash 命令系统](#10-slash-命令系统)
11. [事件与可观测性](#11-事件与可观测性)
12. [调试 Skill](#12-调试-skill)
13. [完整执行链路](#13-完整执行链路)

---

## 1. 架构概览

Skills 系统由四个模块组成，形成"发现 → 注入 → 执行"三段式管线：

```
features/skills.py          ← 数据模型、发现、prompt 渲染
features/skills_bundled.py  ← 4 个内置 skill 定义
features/skills_runtime.py  ← 执行引擎（fork、工具限制、模型覆写）
commands/slash.py            ← slash 命令注册、解析、补全
```

```
启动时
  │
  ▼
discover_skills(root)       ← 三层加载（内置 → 用户 → 项目）
  │
  ▼
agent.skills = {...}        ← 存入 runtime 实例
  │
  ├─► build_prefix()        ← 注入 SKILL_FILE_CREATION_GUIDE（告诉模型如何创建 skill）
  │
  └─► ContextManager.build()
        │
        ▼
      render_prompt_section() ← 每个 turn 渲染可用 skill 列表（模型可见菜单）
        │
        ▼
      用户输入 /skill-name args
        │
        ▼
      handle_repl_command()
        │ parse_slash_command → invoke_skill()
        │
        ▼
      skill.render(args)     ← 变量替换
      _model_override()      ← 可选：临时切模型
      _skill_tool_profile()  ← 可选：临时限制工具白名单
      agent.ask() 或 _run_fork()
        │
        ▼
      返回结果，发射事件
```

---

## 2. Skill 数据模型

核心类型为 `Skill` dataclass（`features/skills.py:21`），字段如下：

### 必填/基础字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | — | Skill 唯一标识，也是 slash 命令名。必填。 |
| `description` | `str` | `""` | 一行描述，显示在 `/skills` 列表和 prompt 菜单中。 |
| `prompt` | `str` | `""` | 静态 prompt 文本。若设置了 `prompt_fn` 则此字段被忽略。 |

### 来源与位置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `source` | `str` | `"builtin"` | 来源标记：`builtin`、`user`、`project`。影响排序优先级。 |
| `skill_root` | `str` | `""` | SKILL.md 所在目录的绝对路径。用于 `${PICO_SKILL_DIR}` 变量替换。 |

### 模型提示

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `when_to_use` | `str` | `""` | 告诉模型什么场景适合调用这个 skill。会出现在 prompt 菜单的附加说明中。 |
| `argument_hint` | `str` | `""` | 参数名提示，显示在 `/skills` 列表中。如 `focus`、`filter`、`message`。 |

### 执行控制

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `context` | `str` | `"inline"` | 执行模式：`inline`（当前 session）或 `fork`（子实例隔离）。 |
| `allowed_tools` | `tuple[str, ...]` | `()` | 工具白名单。为空则无限制。非空时只暴露列表中的工具。 |
| `model` | `str` | `""` | 模型覆写。非空时临时切换 `model_client.model` 为此值。 |
| `user_invocable` | `bool` | `True` | 是否允许用户通过 REPL/TUI 直接调用。为 `False` 时 skill 仍然在 prompt 中可见，模型可以建议。 |
| `disable_model_invocation` | `bool` | `False` | 为 `True` 时只渲染 prompt 文本并返回，不调用模型。用于调试或纯文本输出场景。 |

### 自动触发

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `paths` | `tuple[str, ...]` | `()` | 关联路径。当 `paths` 非空时，即使 `user_invocable=False`，该 skill 也会出现在 prompt 的可见列表中。 |

### 动态 Prompt

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `prompt_fn` | `Callable[[str], str] \| None` | `None` | 动态 prompt 生成函数。接受 arguments 字符串，返回完整 prompt。用于内置 skill 的带参数渲染。 |

### render() 方法

```python
def render(self, arguments=""):
    text = self.prompt_fn(str(arguments)) if self.prompt_fn else self.prompt
    replacements = {
        "$ARGUMENTS": str(arguments),
        "${PICO_SKILL_DIR}": self.skill_root,
        "${CLAUDE_SKILL_DIR}": self.skill_root,
    }
    if self.argument_hint:
        replacements[f"${{{self.argument_hint}}}"] = str(arguments)
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.strip()
```

支持三种变量替换语法：
- `$ARGUMENTS` — 所有传入参数
- `${PICO_SKILL_DIR}` / `${CLAUDE_SKILL_DIR}` — skill 文件所在目录的绝对路径
- `${argument_hint}` — 如果设置了 `argument-hint: target`，则 `${target}` 也会被替换为 arguments

### metadata() 方法

返回 skill 的可序列化摘要，用于 trace 和 report：

```python
def metadata(self):
    return {
        "name": self.name,
        "description": self.description,
        "source": self.source,
        "context": self.context,
        "allowed_tools": list(self.allowed_tools),
        "paths": list(self.paths),
        "user_invocable": self.user_invocable,
        "disable_model_invocation": self.disable_model_invocation,
        "model": self.model,
    }
```

---

## 3. Skill 文件格式

### 基本结构

```markdown
---
name: skill-name
description: 一句话描述
# ... 更多 frontmatter 字段 ...
---

Markdown 格式的 prompt 正文。

可以使用 $ARGUMENTS 变量。
```

### 目录组织

Skill 文件有两种组织方式：

**方式 A：目录形式（推荐）**
```
skills/
├── deploy/
│   └── SKILL.md
├── audit/
│   └── SKILL.md
└── review/
    └── SKILL.md
```

**方式 B：平铺形式**
```
skills/
├── deploy.md
├── audit.md
└── review.md
```

加载时优先检测目录形式（`path.is_dir() and (path / "SKILL.md").is_file()`），再回退到平铺 `.md` 文件。

名称推断规则：
- 目录形式：`default_name = path.parent.name`（如 `deploy/SKILL.md` → `deploy`）
- 平铺形式：`default_name = path.stem`（如 `deploy.md` → `deploy`）
- 若 frontmatter 中显式指定了 `name`，则以上规则被覆盖

### Frontmatter 字段完整参考

```yaml
---
# ── 必填 ──
name: skill-name             # 唯一标识，也是 slash 命令名。首字符 / 会被自动去除。

# ── 推荐 ──
description: 一行描述         # 在 /skills 列表和 prompt 菜单中显示

# ── 可选：模型提示 ──
when-to-use: 适用场景说明     # 帮助模型判断何时调用
arguments: target             # 命名参数名（同 argument-hint）
argument-hint: target         # 参数名提示

# ── 可选：执行控制 ──
context: inline               # inline（默认）| fork
allowed-tools: read_file, search, list_files   # 工具白名单，逗号分隔
model: claude-sonnet-4-6      # 强制使用特定模型
disable-model-invocation: false   # 设为 true 则只渲染 prompt 不发模型请求
user-invocable: true          # 是否允许用户从 REPL 直接调用

# ── 可选：自动触发 ──
paths: src/**/*.py, tests/    # 关联路径，支持 glob，! 前缀排除
---
```

### Frontmatter 值解析规则

- 布尔值：`true`、`yes` → `True`；`false`、`no`、`off`、`0` → `False`
- 列表值：逗号分隔的字符串自动拆分为列表，如 `"read_file, search"` → `["read_file", "search"]`
- 字符串值：首尾引号自动去除；列表值会用 `", "` 连接为字符串
- 带连字符的 key 自动转为下划线：`when-to-use` → `when_to_use`

---

## 4. 发现与加载

### 加载顺序（优先级从低到高）

```
1. 内置 skills (skills_bundled.py)          → source = "builtin"
2. 用户 skills (~/.pico/skills/<name>/)     → source = "user"
3. 项目 skills (<repo>/skills/<name>/)       → source = "project"
4. 项目 skills (<repo>/.pico/skills/<name>/) → source = "project"
```

**同名覆盖**：后加载的 skill 覆盖先加载的同名 skill。也就是说，项目的 `.pico/skills/review/SKILL.md` 会覆盖内置的 `review` skill。

这个设计允许：
- 项目级定制内置 skill 的行为
- 用户全局 skill 在所有项目中可用
- 项目 skill 随仓库版本控制

### 发现函数

```python
def discover_skills(root, home=None):
    from .skills_bundled import bundled_skills
    skills = {skill.name: skill for skill in bundled_skills()}
    search_roots = [
        (Path(home or Path.home()) / ".pico" / "skills", "user"),
        (Path(root) / "skills", "project"),
        (Path(root) / ".pico" / "skills", "project"),
    ]
    for directory, source in search_roots:
        for skill in load_skills_from_dir(directory, source=source):
            skills[skill.name] = skill  # 同名覆盖
    return dict(sorted(skills.items()))
```

### 目录加载函数

```python
def load_skills_from_dir(skills_dir, source):
    skills_dir = Path(skills_dir).expanduser()
    if not skills_dir.exists():
        return []
    files = []
    for path in sorted(skills_dir.iterdir()):
        if path.is_dir() and (path / "SKILL.md").is_file():
            files.append(path / "SKILL.md")      # 目录形式
        elif path.is_file() and path.suffix.lower() == ".md":
            files.append(path)                    # 平铺形式
    return [skill for path in files if (skill := load_skill_file(path, source=source))]
```

### 不触发重新发现

与 pico 的 skill 系统不同，pico-v3 的 skills **在启动时一次性加载**，运行时不会像 `refresh_prefix()` 那样重新扫描 skills 目录。这意味着在 session 运行时新增或修改 skill 文件**不会**实时生效，需要重新启动 pico。

---

## 5. 内置 Skills

pico-v3 内置 4 个 skill，定义在 `features/skills_bundled.py`。它们都使用 `prompt_fn` 动态生成 prompt，支持 `$ARGUMENTS` 参数。

### 5.1 `/review` — 代码审查

```
/review [focus]
```

审查当前改动，**只报告不修改**。

- 先看 `git status` 和 `git diff`
- 按严重程度报告：正确性、安全性、性能、可读性、测试覆盖
- 不修改任何文件

生成的 prompt 结构：
```markdown
# Code Review

Inspect git status and diff first.
Report correctness, security, performance, readability, and missing-test findings by severity.
Do not modify files.

## Additional Focus

请重点检查认证模块的安全性
```

### 5.2 `/test` — 运行测试

```
/test [filter]
```

运行项目测试套件并分析结果。

- 从项目文件中识别正确的测试命令
- 先运行最小范围的验证，再逐步扩大
- 如果测试失败，先诊断根因再修改代码

### 5.3 `/commit` — 提交代码

```
/commit [message]
```

从当前暂存区创建一个规范的 git commit。

- 查看 `git status` 和暂存区 diff
- 只暂存相关变更，创建简洁的 conventional commit
- 不包含无关文件

### 5.4 `/simplify` — 代码简化

```
/simplify [focus]
```

审查改动代码，移除冗余、简化逻辑、修复问题。

- 运行 `git diff`，查看变更文件
- 移除重复代码
- 简化过度复杂的逻辑
- 修改后运行测试或 linter 验证

### 内置 Skill 的 prompt_fn 模式

四个内置 skill 共用同一个 `_with_optional_section` 工厂函数：

```python
def _with_optional_section(title, paragraphs, section_title):
    def render(arguments=""):
        lines = [title, "", *paragraphs]
        if arguments:
            lines.extend(["", f"## {section_title}", "", str(arguments)])
        return "\n".join(lines)
    return render
```

这意味着当用户传入参数时，参数内容会作为一个独立 section 追加到 prompt 末尾。

---

## 6. 自定义 Skill

### 6.1 最小示例

创建 `skills/deploy/SKILL.md`：

```markdown
---
name: deploy
description: 部署前检查清单
argument-hint: target
allowed-tools: read_file, search, list_files
---

请检查仓库是否满足部署到 $ARGUMENTS 环境的条件：

1. tests/ 全部通过
2. CHANGELOG 包含本次发布条目
3. 配置文件中的 production endpoint 没有指向 dev
4. 所有环境变量已在 .env.example 中声明
```

调用：

```text
> /deploy staging
```

`$ARGUMENTS` 会被替换为 `staging`。

### 6.2 项目级覆盖内置 Skill

如果想定制 `review` 的行为，在项目中创建 `.pico/skills/review/SKILL.md`：

```markdown
---
name: review
description: 团队代码审查（含安全扫描）
context: fork
allowed-tools: read_file, search, list_files, run_shell
---

# Code Review (Team Edition)

1. 运行 git diff 获取改动
2. 按以下维度审查：
   - 正确性：逻辑是否正确
   - 安全性：是否引入 XSS/SQL 注入/命令注入
   - 性能：是否有不必要的 O(n²) 操作
   - 规范：是否符合我们的 ESLint 规则
3. 运行 `npm run lint` 确认无 lint 错误
4. 输出结构化的审查报告
```

这个文件会覆盖内置的 `review` skill。

### 6.3 用户级全局 Skill

创建 `~/.pico/skills/explain/SKILL.md`：

```markdown
---
name: explain
description: 用中文解释一段代码
argument-hint: file-path
allowed-tools: read_file
---

请用中文解释文件 $ARGUMENTS 中的代码逻辑：

1. 整体结构
2. 关键函数和数据流
3. 值得注意的设计模式或反模式
```

这个 skill 在所有项目中可用。

### 6.4 Fork 上下文 Skill

当 skill 需要独立执行且不污染当前会话时，使用 `context: fork`：

```markdown
---
name: quick-research
description: 不污染会话的快速调研
context: fork
allowed-tools: search, read_file, list_files
---

调研 $ARGUMENTS 在整个仓库中的使用情况：

1. 搜索所有引用位置
2. 总结使用模式
3. 发现潜在问题
```

`fork` 模式下，skill 在子 Pico 实例中执行：
- 独立的 session 和历史
- 不占用父 session 的上下文窗口
- 结果返回后子实例销毁

### 6.5 纯文本 Skill（禁用模型调用）

```markdown
---
name: checklist
description: 输出发布检查清单
disable-model-invocation: true
---

## 发布检查清单

1. 所有测试通过
2. CHANGELOG 已更新
3. 版本号已升级
4. 无 TODO/FIXME 残留
5. 生产环境配置已复查
```

调用 `/checklist` 时，pico 只渲染这段文本并显示，不会调用模型。

### 6.6 模型覆写 Skill

```markdown
---
name: complex-refactor
description: 大规模重构使用更强的模型
model: claude-opus-4-7
allowed-tools: read_file, write_file, patch_file, search, list_files, run_shell
---

执行以下重构：$ARGUMENTS

1. 先全面阅读相关文件
2. 制定重构计划
3. 逐步实施，每步验证
4. 运行测试确认无回归
```

### 6.7 关联路径 Skill

```markdown
---
name: auth-guide
description: 认证模块相关规范
paths: src/auth/**, src/middleware/auth.*
---

处理认证相关代码时请遵循以下规范：

1. 所有 Token 相关逻辑必须在 AuthService 中
2. 不在 middleware 层做权限判断，只做 Token 验证
3. 测试文件必须覆盖 Token 过期和无效两种场景
```

设置了 `paths` 的 skill 即使 `user-invocable: false` 也会出现在 prompt 的可见 skill 列表中，帮助模型在操作相关文件时记起这些规范。

---

## 7. Prompt 注入机制

Skills 在 prompt 中有两层注入。

### 7.1 Prefix 层：SKILL_FILE_CREATION_GUIDE

在 `build_prefix()` 中直接写入系统规则：

```
- When creating Pico skill files at .pico/skills/<name>/SKILL.md or skills/<name>/SKILL.md, use frontmatter:
---
name: audit
description: Audit a file
user-invocable: true
---
Audit $ARGUMENTS for risky changes.
```

这告诉模型：如果你要创建 skill 文件，应该用这个格式。

### 7.2 Skills Section：可用 Skill 菜单

`ContextManager.build()` 调用 `render_prompt_section()`，在当前 turn 的 prompt 中注入可用 skill 列表：

```python
def render_prompt_section(skills):
    visible = [s for s in list_skills(skills, user_invocable_only=False)
               if _should_show_in_prompt(s)]
    # →
    # Available skills:
    # - /review: Review code changes... — Before committing or merging code changes
    # - /test: Run test suite... — To verify code changes with the relevant test path
    # - /commit: Create a focused git commit... — When ready to commit a coherent change
    # - /simplify: Review changed code for reuse... — After making code changes
```

**可见性规则**（`_should_show_in_prompt`）：
- `user_invocable=True` 的 skill 始终显示
- `paths` 非空的 skill 始终显示（即使 `user_invocable=False`）
- 两者都不满足的 skill 不显示（模型看不到）

**排序规则**（`list_skills`）：
- 按 `(source != "builtin", name)` 排序
- 非内置 skill 排在前面（更相关），同 source 按名称字母序

### 7.3 完整的 Prompt 结构

```
[prefix]              ← 系统规则 + 工具列表 + workspace + SKILL_FILE_CREATION_GUIDE
[memory]              ← working memory + checkpoint + memory system section
[skills]              ← 可用 skill 菜单
[relevant_memory]     ← 检索到的相关笔记
[history]             ← 对话历史（可能被压缩）
[current_request]     ← 当前用户请求
```

---

## 8. 执行引擎

`features/skills_runtime.py` 提供 skill 执行的完整管线。

### 8.1 入口：invoke_skill()

```python
def invoke_skill(agent, name, arguments=""):
    skill = agent.skills[str(name).lstrip("/")]
    prompt = _skill_prompt(skill, arguments)
    emit("skill_invoked", payload)

    if skill.disable_model_invocation:
        emit("skill_completed", status="prompt_only")
        return skill.render(arguments)

    with _model_override(agent, skill.model):
        with _skill_tool_profile(agent, skill):
            if skill.context == "fork":
                answer = _run_fork(agent, skill, prompt)
            else:
                answer = agent.ask(prompt)

    emit("skill_completed", status="completed")
    return answer
```

### 8.2 执行 Prompt 格式

```python
def _skill_prompt(skill, arguments):
    return (
        f"Skill: {skill.name}\n"
        f"Source: {skill.source}\n"
        f"Context: {skill.context}\n"
        f"Arguments: {arguments}\n\n"
        f"{skill.render(arguments)}"
    )
```

模型收到的请求会在前面附加 skill 的元数据头部，然后是渲染后的 prompt 正文。

### 8.3 Tool Profile 隔离

`_skill_tool_profile()` context manager 在 skill 执行期间动态注入临时工具白名单：

```python
@contextmanager
def _skill_tool_profile(agent, skill):
    if not skill.allowed_tools:
        yield  # 无限制，直接放行
        return

    allowed = frozenset(name for name in skill.allowed_tools if name in agent.tools)
    agent.tool_profiles[f"skill:{skill.name}"] = ToolSetProfile(f"skill:{skill.name}", allowed)
    agent.set_tool_profile(f"skill:{skill.name}")
    try:
        yield
    finally:
        agent.set_tool_profile(previous)       # 恢复原 profile
        agent.tool_profiles.pop(f"skill:{skill.name}", None)  # 清理临时 profile
```

关键行为：
- 仅在 `allowed_tools` 非空时生效
- 只白名单 `agent.tools` 中实际存在的工具（不存在的忽略）
- `set_tool_profile()` 不触发 prefix 刷新，但下一轮 `build_prefix()` 会从 `available_tools()` 重新读取，而 `available_tools()` 受当前 tool profile 限制
- 退出时恢复原 profile 并清理临时 profile 对象

### 8.4 模型覆写

```python
@contextmanager
def _model_override(agent, model):
    if not model:
        yield
        return
    sentinel = object()
    previous = getattr(agent.model_client, "model", sentinel)
    setattr(agent.model_client, "model", model)
    try:
        yield
    finally:
        if previous is sentinel:
            delattr(agent.model_client, "model")
        else:
            setattr(agent.model_client, "model", previous)
```

直接修改 `model_client.model` 属性。对 Anthropic-compatible 协议，这会影响请求中的 `model` 字段。

### 8.5 Fork 上下文

`_run_fork()` 创建完全隔离的子实例：

```python
def _run_fork(agent, skill, prompt):
    child = type(agent)(
        model_client=agent.model_client,
        workspace=agent.workspace,
        session_store=agent.session_store,
        approval_policy=agent.approval_policy,
        max_steps=agent.max_steps,
        max_new_tokens=agent.max_new_tokens,
        depth=agent.depth,
        max_depth=agent.max_depth,
        read_only=agent.read_only,
        shell_env_allowlist=agent.shell_env_allowlist,
        secret_env_names=agent.secret_env_names,
        feature_flags=agent.feature_flags,
    )
    with _model_override(child, skill.model), _skill_tool_profile(child, skill):
        answer = child.ask(prompt)
    emit("skill_fork_completed", {"child_session_id": child.session["id"]})
    return answer
```

fork 的特点：
- 子实例拥有独立的 session、history、memory
- 继承父实例的所有配置（model_client、workspace、approval、secret 等）
- 不会在子实例上启用 auto-dream
- 子实例的 session 仍会被保存，可以通过 `/resume` 查看

---

## 9. 上下文预算管理

Skills section 在 prompt 中有独立的预算控制。

### 默认配置

```python
DEFAULT_SECTION_BUDGETS = {
    "skills": 4000,       # skills section 最大 4000 字符
    # ...
}
DEFAULT_SECTION_FLOORS = {
    "skills": 600,        # 压缩时不低于 600 字符
    # ...
}
DEFAULT_REDUCTION_ORDER = ("relevant_memory", "skills", "history", "memory", "prefix")
```

### 压缩行为

当整个 prompt 超过总预算（默认 60000 字符）时：
1. 首先压缩 `relevant_memory`
2. 仍然超预算 → 压缩 `skills`
3. 仍然超预算 → 压缩 `history`
4. 仍然超预算 → 压缩 `memory`
5. 仍然超预算 → 压缩 `prefix`
6. `current_request` 永不压缩

压缩方式是 `tail_clip(raw, budget)`，即保留尾部（最新内容），截断头部。

### Floor 机制

每个 section 有最低预算保证（floor），压缩不会使其低于此值：

```python
def _compute_section_floors(self):
    floors = {section: max(20, int(budget) // 4) for section, budget in budgets.items()}
    floors.update(self._section_floor_overrides)
    return floors
```

默认 floor = `max(20, budget // 4)`，即至少保留预算的 1/4，且不低于 20 字符。

---

## 10. Slash 命令系统

### 10.1 命令注册

`commands/slash.py` 管理所有内置命令，包括 skill 相关命令：

| 命令 | 用法 | 说明 |
|------|------|------|
| `/skills` | `/skills` | 列出所有可用 skill（别名 `/sk`） |
| `/skill` | `/skill <name> [args]` | 手动调用一个 skill |
| `/agents` | `/agents` | 查看子 agent 状态（别名 `/agent`） |
| `/subagent` | `/subagent explore/worker ...` | 手动启动子 agent（别名 `/sub`） |

完整命令列表共 22 个（`SLASH_COMMANDS` 元组）。

### 10.2 命令路由

CLI 处理输入时的路由顺序：

```python
def handle_repl_command(agent, user_input):
    # 1. 先查内置命令（/help, /exit, /history, ...）
    resolved = resolve_command(raw_command)

    # 2. 再查 agent.skills
    command, arguments = skillslib.parse_slash_command(user_input)
    if command and command in agent.skills:
        return True, False, invoke_skill(agent, command, arguments)

    # 3. 都不匹配 → 交给 agent.ask() 作为自然语言处理
    return False, False, ""
```

这意味着：
- 内置命令优先级高于同名 skill
- 任何以 `/` 开头且匹配 agent.skills 中 key 的输入都会被路由到 `invoke_skill()`

### 10.3 命令补全

`slash.py` 的 `suggest_commands()` 用于 TUI 的 tab 补全：

```python
def suggest_commands(text: str, limit: int = 8) -> list[SlashCommand]:
    if not text.startswith("/"):
        return []
    body = text[1:]
    if " " in body:
        return []           # 已有参数，不补全
    token = body.lower()
    matches = []
    for command in SLASH_COMMANDS:
        names = (command.name, *command.aliases)
        if not token or any(name.startswith(token) for name in names):
            matches.append(command)
    return matches[:limit]
```

---

## 11. 事件与可观测性

Skill 执行过程中会发射以下 session 事件：

| 事件 | 触发时机 | payload 内容 |
|------|----------|-------------|
| `skill_invoked` | skill 开始执行 | name, source, context, arguments, allowed_tools, prompt_chars, model_override |
| `skill_completed` | skill 执行完成 | 上述字段 + status, answer_chars |
| `skill_fork_completed` | fork 子实例完成 | skill name, child_session_id |

状态值：
- `prompt_only`：`disable_model_invocation=true` 时的完成状态
- `completed`：正常执行完成

### 在 Report 中查看

Skills 元数据也出现在每次 run 的 prompt metadata 中：

```json
{
  "skills": {
    "available_count": 5,
    "user_invocable_count": 4,
    "items": [
      {
        "name": "commit",
        "description": "Create a focused git commit...",
        "source": "builtin",
        "context": "inline",
        "allowed_tools": [],
        "paths": [],
        "user_invocable": true,
        "disable_model_invocation": false,
        "model": ""
      }
    ]
  }
}
```

---

## 12. 调试 Skill

### 12.1 查看 Skill 列表

```text
> /skills

/commit    [message] Create a focused git commit from the current staged changes [builtin]
/review    [focus]   Review code changes and report issues without making fixes [builtin]
/simplify  [focus]   Review changed code for reuse, quality, and efficiency [builtin]
/test      [filter]  Run the project's test suite and analyze results [builtin]
/deploy    [target]  部署前检查清单 [project]
```

### 12.2 预览 Skill Prompt

设置 `disable-model-invocation: true`，然后在 TUI 中调用该 skill，可以看到渲染后的完整 prompt 文本而不会发送模型请求。

### 12.3 查看执行 Session

Fork 模式的 skill 会在 session store 中留下子 session。可以通过 `/history` 查看，通过 `/resume` 恢复查看。

### 12.4 事件流调试

Skill 执行过程中的事件会写入 `.pico/sessions/<id>.events.jsonl`：

```json
{"event": "skill_invoked", "skill": "review", "source": "builtin", ...}
{"event": "skill_completed", "skill": "review", "status": "completed", "answer_chars": 1234}
```

---

## 13. 完整执行链路

以一个具体例子追踪 `/review 请重点检查认证模块的安全性` 的完整执行路径：

```
1. 用户输入
   "/review 请重点检查认证模块的安全性"
   
2. CLI 路由 (cli.py:handle_repl_command)
   parse_slash_command("/review ...") → ("review", "请重点检查认证模块的安全性")
   "review" in agent.skills → True
   → invoke_skill(agent, "review", "请重点检查认证模块的安全性")

3. Skill 查找 (skills_runtime.py:invoke_skill)
   skill = agent.skills["review"]
   # Skill(name="review", source="builtin", context="inline", ...)
   
4. 渲染 Skill Prompt
   skill.render("请重点检查认证模块的安全性")
   → 
   # Code Review
   
   Inspect git status and diff first.
   Report correctness, security, performance, readability, and missing-test findings by severity.
   Do not modify files.
   
   ## Additional Focus
   
   请重点检查认证模块的安全性

5. 组装执行 Prompt
   _skill_prompt(skill, args) →
   Skill: review
   Source: builtin
   Context: inline
   Arguments: 请重点检查认证模块的安全性
   
   [上述渲染内容]

6. 执行
   - allowed_tools 为空 → 不启用 tool profile 隔离
   - model 为空 → 不启用模型覆写
   - context == "inline" → agent.ask(prompt)
   
7. agent.ask() 内部
   - Engine.run_turn() 启动新 turn
   - _build_prompt_and_metadata() 组装完整 prompt
   - ContextManager.build() 注入 skills section
   - 模型看到完整上下文（prefix + memory + skills 菜单 + history + review prompt）
   - 模型执行工具调用（如 git diff, read_file）
   - 生成最终审查报告
   
8. 完成
   emit("skill_completed", {"skill": "review", "status": "completed", ...})
   返回审查结果文本
```
