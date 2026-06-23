# pico-v3 Memory 系统改进详解

本文档深入分析 pico-v3 在 pico 基础上的 Memory 系统改进，从架构设计、数据流、关键机制到具体代码实现逐层展开。

---

## 目录

1. [总览：从单层到三层体系](#1-总览从单层到三层体系)
2. [第一层：Working Memory（工作记忆）的增强](#2-第一层working-memory工作记忆的增强)
3. [第二层：Daily Logs（每日日志）](#3-第二层daily-logs每日日志)
4. [第三层：Durable Topics（持久主题）](#4-第三层durable-topics持久主题)
5. [核心机制：Auto-Dream（自动整合）](#5-核心机制auto-dream自动整合)
6. [Durable Promotion：从回答中提取长期记忆](#6-durable-promotion从回答中提取长期记忆)
7. [Memory System Section：注入给模型的记忆契约](#7-memory-system-section注入给模型的记忆契约)
8. [安全边界：Secret 检测与噪声过滤](#8-安全边界secret-检测与噪声过滤)
9. [内存与召回：跨层统一检索](#9-内存与召回跨层统一检索)
10. [事件与可观测性](#10-事件与可观测性)
11. [用户交互命令](#11-用户交互命令)
12. [总结对照表](#12-总结对照表)

---

## 1. 总览：从单层到三层体系

### pico 的记忆模型

```
┌──────────────────────────────────┐
│         Working Memory           │
│                                  │
│  task_summary  recent_files     │
│  episodic_notes  file_summaries │
│                                  │
│  全部存在 session JSON 中        │
│  session 结束 → 记忆消失         │
│  新 session → 从零开始           │
└──────────────────────────────────┘
```

pico 只有一层工作记忆。它是 session 内有效的短期记忆，session 结束后只能通过恢复旧 session 才能找回。所有记忆都是易失的，没有跨 session 的持久化机制。

### pico-v3 的记忆模型

```
┌────────────────────────────────────────────────────────────┐
│                     Durable Topics                          │
│              .pico/memory/topics/*.md                       │
│                                                             │
│  project-conventions   key-decisions                        │
│  dependency-facts      user-preferences                     │
│                                                             │
│  由 /dream 或 auto-dream 从 daily logs 整合                │
│  跨 session 持久，按主题组织，可检索                         │
└────────────────────────────────────────────────────────────┘
                          ▲
                          │  Dream 整合（手动或自动）
                          │
┌────────────────────────────────────────────────────────────┐
│                      Daily Logs                             │
│          .pico/memory/logs/YYYY/MM/YYYY-MM-DD.md            │
│                                                             │
│  由 /remember 或 <memory> 标签写入                          │
│  追加写入，时间戳标注，不可变                                │
└────────────────────────────────────────────────────────────┘
                          ▲
                          │  /remember, <memory> tags
                          │
┌────────────────────────────────────────────────────────────┐
│                    Working Memory                           │
│                                                             │
│  task_summary  recent_files  file_summaries                │
│  episodic_notes（含 kind 字段区分来源）                     │
│                                                             │
│  存在 session JSON 中，session 内有效                        │
└────────────────────────────────────────────────────────────┘
```

数据流向是单向的：**Working Memory → Daily Logs → Durable Topics**。每一层都是上一层信号的提炼和固化。

### 规模对比

| 维度 | pico | pico-v3 |
|------|------|---------|
| 代码行数 | ~410 行 | ~1227 行 |
| 记忆层数 | 1 层 | 3 层 |
| 持久化 | session JSON 内 | 独立文件系统目录 |
| 跨 session 保留 | 需手动恢复 session | 自动持久化 |
| 自动整合 | 无 | Auto-Dream 后台线程 |
| 记忆索引 | 无 | MEMORY.md |
| 秘密检测 | 无 | 正则 + redacted_value 检测 |
| 主题分类 | 无 | 4 种默认 + 自定义 |

---

## 2. 第一层：Working Memory（工作记忆）的增强

pico-v3 的 Working Memory 在 pico 的基础上进行了以下增强：

### 2.1 note 结构增加 `kind` 字段

pico 的 episodic note 结构：
```python
{
    "text": "...",
    "tags": [...],
    "source": "...",
    "created_at": "...",
    "note_index": 0
}
```

pico-v3 增加了 `kind` 字段：
```python
{
    "text": "...",
    "tags": [...],
    "source": "...",
    "created_at": "...",
    "note_index": 0,
    "kind": "episodic"  # 新增：episodic / process / durable
}
```

`kind` 字段用于区分笔记类型：
- `episodic`：普通跨轮笔记（默认）
- `process`：工具执行过程笔记（如 partial_success、error、rejected 状态）
- `durable`：从持久主题中加载的跨 session 笔记

### 2.2 Process Note（过程笔记）

v3 新增了 `record_process_note_for_tool()` 函数（在 `Pico` 类中），当工具执行返回 `partial_success`、`error`、`rejected` 状态时自动记录过程笔记：

```python
def record_process_note_for_tool(self, name, metadata):
    status = str(metadata.get("tool_status", "")).strip()
    if status not in {"partial_success", "error", "rejected"}:
        return
    # ...生成描述性文本...
    self.memory.append_note(text, tags=tuple(tags), source=name, kind="process")
```

这意味着工具执行中的异常状态会被自动沉淀到工作记忆，供下一轮模型参考。

### 2.3 File Summary 支持 freshness 检测

pico 的 file_summaries 存储了 freshness（文件 hash），但在工作记忆中缺乏主动失效机制。

pico-v3 增加了 `invalidate_stale_file_summaries()` 函数：在每次 `evaluate_resume_state()` 时主动检查所有 file summary 的 freshness 是否仍然匹配当前文件内容，将不匹配的标记为 expired。

```python
def invalidate_stale_file_summaries(state, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    invalidated = []
    for path, summary in list(state["file_summaries"].items()):
        current_freshness = file_freshness(path, workspace_root)
        if summary.get("freshness") == current_freshness:
            continue
        invalidated.append(path)
        state["file_summaries"].pop(path, None)
    return state, invalidated
```

### 2.4 Working Memory 中引用 Durable Topics

pico-v3 的 `normalize_memory_state()` 在末尾会读取 durable topics 的 slug 列表，将其注入到 working memory state 中：

```python
durable_root = Path(workspace_root) / ".pico" / "memory"
durable_store = DurableMemoryStore(durable_root)
state["durable_topics"] = durable_store.topic_slugs()
```

`render_memory_text()` 也会渲染这个字段，让模型在 prompt 中看到有哪些持久主题可用：

```
Memory:
- task: Fix login bug
- recent_files: src/auth.py, tests/test_auth.py
- file_summaries:
  - src/auth.py: def login(user, pass) -> Token | raises AuthError
- episodic_notes: 3
- durable_topics: project-conventions, key-decisions, user-preferences
```

### 2.5 is_effectively_empty() 判断

v3 新增了工具函数判断记忆是否实际为空：

```python
def is_effectively_empty(state, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    return (
        not str(state["working"]["task_summary"]).strip()
        and not state["working"]["recent_files"]
        and not state["episodic_notes"]
        and not state["file_summaries"]
    )
```

这是为了在 resume 等场景下判断记忆是否有实际价值。

---

## 3. 第二层：Daily Logs（每日日志）

Daily Logs 是 pico-v3 全新引入的记忆中间层，它是记忆系统的主要摄入通道。

### 3.1 数据模型

```
.pico/memory/logs/
├── 2026/
│   └── 05/
│       ├── 2026-05-14.md
│       ├── 2026-05-15.md
│       └── 2026-05-16.md
```

每个文件按日期组织，内容为带时间戳的条目列表：

```markdown
- [14:32] This project uses DeepSeek's Anthropic-compatible endpoint
- [15:10] The user prefers short commit messages without emoji
- [16:45] The auth middleware was rewritten due to legal/compliance requirements
```

### 3.2 写入方式

有三种方式写入 Daily Log：

**方式一：`/remember <text>` 命令**
```python
# cli.py → Pico.remember_durable_note()
def remember_durable_note(self, text):
    path = memorylib.append_to_daily_log(self.memory_dir, text)
    # ...emit session event...
```

**方式二：`<memory>` 标签自动提取**
模型在 final answer 中包裹 `<memory>...</memory>` 标签，由 `extract_memory_tags()` 在每轮 turn 结束时自动提取：

```python
def extract_memory_tags(text):
    return [match.strip() for match in re.findall(
        r"<memory>(.*?)</memory>", str(text), re.DOTALL
    ) if match.strip()]
```

**方式三：从 `promote_durable_memory()` 的 structured answer 中提取**
当模型在回答中使用 `Decision:`、`Convention:` 等前缀时，自动识别并提升到 daily log。

### 3.3 关键函数

```python
def daily_log_path(memory_dir, today=None):
    """生成当天日志文件路径，自动创建目录"""
    
def append_to_daily_log(memory_dir, entry, today=None):
    """以 [- HH:MM] text 格式追加一条到当天日志"""
```

Daily Logs 是**追加写入、不可变**的。一旦写入，内容不会被修改。只有在 Dream 整合时，整个日志文件的内容才会被"消化"成 durable topics。

---

## 4. 第三层：Durable Topics（持久主题）

Durable Topics 是长期记忆的最终形态，按主题分文件组织，跨 session 持久化。

### 4.1 数据模型

```
.pico/memory/
├── MEMORY.md                        # 索引文件
├── topics/
│   ├── project-conventions.md       # 项目约定
│   ├── key-decisions.md             # 关键决策
│   ├── dependency-facts.md          # 依赖信息
│   └── user-preferences.md          # 用户偏好
```

### 4.2 索引文件格式（MEMORY.md）

```markdown
# Durable Memory Index

- [project-conventions](topics/project-conventions.md): Project Conventions
  - summary: Stable repository conventions.
  - tags: convention
- [key-decisions](topics/key-decisions.md): Key Decisions
  - summary: Long-lived decisions and rationale anchors.
  - tags: decision
```

### 4.3 主题文件格式

```markdown
# Key Decisions

- topic: key-decisions
- summary: Long-lived decisions and rationale anchors.
- tags: decision
- updated_at: 2026-05-16T14:32:00

## Notes
- The auth middleware uses JWT with 15-minute expiry
- We chose SQLite over Postgres for local-only deployments
- The project follows trunk-based development with feature flags
```

### 4.4 DurableMemoryStore 类

这是持久记忆的核心操作类：

| 方法 | 功能 |
|------|------|
| `load_index()` | 解析 MEMORY.md，返回 topic 列表 |
| `load_topic_notes(topic)` | 读取 `topics/<topic>.md` 的 Notes 段 |
| `promote(promotions)` | 将 (topic, note_text) 提升到对应 topic 文件 |
| `retrieval_candidates(query, limit)` | 从所有 topic 中跨层检索相关笔记 |
| `_write_index(topics)` | 重写 MEMORY.md |
| `_write_topic(topic, notes)` | 重写 `topics/<topic>.md` |
| `_subject_key(text)` | 提取笔记的主题键（用于去重和替换） |

### 4.5 智能去重：subject-based supersede

`promote()` 方法在写入新笔记前，会提取每条笔记的 **subject key**。如果同一 topic 下已有相同 subject 的旧笔记，则新笔记**替换**旧笔记（而非追加重复条目）：

```python
@staticmethod
def _subject_key(text):
    # 匹配 "X is Y", "X should Y", "X是Y" 等模式，提取主语
    patterns = (
        r"^(.+?)\s+is\s+.+$",
        r"^(.+?)是.+$",
        # ...
    )
```

例如，如果已存在 "The auth middleware uses JWT with 15-minute expiry"，而新笔记是 "The auth middleware uses JWT with 30-minute expiry"，它们会被识别为同一 subject，旧笔记被替换。

### 4.6 四种默认主题分类

```python
DURABLE_TOPIC_DEFAULTS = {
    "project-conventions": {
        "title": "Project Conventions",
        "summary": "Stable repository conventions.",
        "tags": ["convention"],
    },
    "key-decisions": {
        "title": "Key Decisions",
        "summary": "Long-lived decisions and rationale anchors.",
        "tags": ["decision"],
    },
    "dependency-facts": {
        "title": "Dependency Facts",
        "summary": "Stable dependency and environment facts.",
        "tags": ["dependency"],
    },
    "user-preferences": {
        "title": "User Preferences",
        "summary": "Stable user preferences.",
        "tags": ["preference"],
    },
}
```

这些主题也在 `DURABLE_MEMORY_LINE_PATTERNS` 中通过正则匹配，支持中英文：

```python
DURABLE_MEMORY_LINE_PATTERNS = (
    ("project-conventions", re.compile(r"(?i)^Project convention:\s*(.+)$")),
    ("key-decisions",       re.compile(r"(?i)^Decision:\s*(.+)$")),
    ("dependency-facts",    re.compile(r"(?i)^Dependency:\s*(.+)$")),
    ("user-preferences",    re.compile(r"(?i)^Preference:\s*(.+)$")),
    ("project-conventions", re.compile(r"^项目约定：\s*(.+)$")),
    ("key-decisions",       re.compile(r"^决策：\s*(.+)$")),
    ("dependency-facts",    re.compile(r"^依赖：\s*(.+)$")),
    ("user-preferences",    re.compile(r"^偏好：\s*(.+)$")),
)
```

---

## 5. 核心机制：Auto-Dream（自动整合）

Auto-Dream 是 pico-v3 记忆系统最核心的创新：**一个后台线程中的独立 agent 实例，专门负责将 daily logs 整合成 durable topics**。

### 5.1 触发条件

Auto-Dream 由两个门控条件决定：

```python
def evaluate_auto_dream_gate(memory_dir, min_hours, min_sessions, 
                              current_session_id, sessions_dir=None):
    last = read_last_consolidated_at(memory_dir)  # 上次整合时间
    current = datetime.now().timestamp()
    hours_since = (current - last) / 3600 if last > 0 else float("inf")
    session_ids = list_sessions_since(last, sessions_dir=sessions_dir,
                                       current_session_id=current_session_id)
    # 条件 1: 距上次整合 >= min_hours（默认 24h）
    # 条件 2: 新 session 数 >= min_sessions（默认 5）
    should_run = hours_since >= min_hours and len(session_ids) >= min_sessions
    return result
```

两个条件必须同时满足，避免过于频繁的整合。

### 5.2 执行流程

```
用户 turn 完成
    │
    ▼
maintain_memory_after_turn(agent, final_answer)
    │
    ├── 提取 <memory> 标签 → 写入 daily log
    │
    ├── auto_dream disabled? → skip
    │
    ├── evaluate_auto_dream_gate()
    │   ├── 不满足条件 → skip (记录原因)
    │   └── 满足条件
    │       ├── try_acquire_lock() → 防止并发 dream
    │       └── 启动后台线程 _background_dream()
    │
    ▼
_background_dream() [daemon thread]
    │
    ├── _memory_file_snapshot(before)  # 记录整合前的文件状态
    │
    ├── run_dream(agent, quiet=True, session_ids=...)
    │   │
    │   ├── 创建独立的 dream_agent (Pico 子实例)
    │   │   - approval_policy="auto"
    │   │   - max_steps=max(agent.max_steps, 20)
    │   │   - max_new_tokens=max(agent.max_new_tokens, 4096)
    │   │   - feature_flags: memory=False (防止递归)
    │   │   - write_scope: 仅限 memory 目录
    │   │   - tool_profile="dream"
    │   │
    │   ├── 构建 build_dream_prompt()
    │   │   包含: Phase 1 Orient / Phase 2 Gather /
    │   │         Phase 3 Consolidate / Phase 4 Prune
    │   │
    │   └── dream_agent.ask(dream_prompt)
    │       dream agent 自行执行四阶段整合流程
    │
    ├── record_consolidation()  # 更新锁文件时间戳
    │
    ├── _changed_memory_files(before, after)  # 计算变更
    │
    ├── emit session event "dream_consolidated"
    │
    └── release_lock()
```

### 5.3 Dream Prompt 设计

Dream prompt（约 90 行）将整合任务拆为四个阶段：

**Phase 1 — Orient（定位）**
- 列出 memory 目录下现有文件
- 读取 MEMORY.md 了解当前索引
- 浏览已有 topic 文件

**Phase 2 — Gather（收集）**
- 阅读 daily logs
- 检查已有记忆是否过时
- 按需搜索 session transcripts（用 grep 精确查找，不整文件读取）

**Phase 3 — Consolidate（整合）**
- 按 memory 格式约定写入/更新 topic 文件
- 合并而非重复
- 将相对日期转为绝对日期
- 删除已被证伪的旧记忆
- 拒绝 secrets、raw output、stack trace、transient task state

**Phase 4 — Prune（裁剪）**
- 更新 MEMORY.md（控制行数和大小）
- 移除指向过期或错误记忆的索引条目
- 将冗余索引条目下放到 topic 文件

### 5.4 并发控制

使用基于文件的锁机制防止多个 dream 同时运行：

```python
LOCK_FILE_NAME = ".consolidate-lock"
HOLDER_STALE_S = 3600  # 锁持有超过 1 小时视为过期

def try_acquire_lock(memory_dir):
    # 检查锁文件是否存在且持有者进程仍存活
    # 如果持有者已死或锁过期，覆盖
    lock_path.write_text(str(current_pid))

def release_lock(memory_dir):
    # 更新时间戳（不删除文件，因为时间戳用于下次触发判断）

def record_consolidation(memory_dir):
    # 写入进程 PID + 更新时间戳
```

锁文件同时承担两个职责：
1. **互斥锁**：防止并发 dream
2. **时间记录**：`read_last_consolidated_at()` 通过读取锁文件的 mtime 判断上次整合时间

### 5.5 Dream Session Cap

防止过多 session 撑爆模型上下文：

```python
DREAM_SESSION_CAP = 30  # 单次 dream 最多展示 30 个 session ID
DREAM_MIN_NEW_TOKENS = 4096  # dream agent 的最小输出 token
```

超过 CAP 时，只列出最近的 30 个 session ID，并附注 "the next dream will pick up the rest"。

---

## 6. Durable Promotion：从回答中提取长期记忆

pico-v3 新增了从模型的 final answer 中自动识别并提升记忆内容的机制。

### 6.1 触发条件

当用户消息中包含记忆意图关键词时触发：

```python
DURABLE_MEMORY_INTENT_PATTERN = re.compile(
    r"(?i)\b(capture|remember|save|store|persist|note)\b"
)
DURABLE_MEMORY_INTENT_ZH_PATTERN = re.compile(
    r"(记住|保存|记录|沉淀|长期记忆|持久记忆)"
)
```

### 6.2 提取逻辑

`extract_durable_promotions()` 扫描 final answer 的每一行，匹配 `DURABLE_MEMORY_LINE_PATTERNS`：

```
模型回答：
Decision: We should migrate to JWT-based auth in Q3.

↓ 正则匹配

("key-decisions", "We should migrate to JWT-based auth in Q3")

↓ reject_durable_reason() 过滤

通过 → 加入 promotions 列表

↓ promote_durable_memory()

写入 topics/key-decisions.md
```

### 6.3 Rejection Filter（拒绝过滤器）

`reject_durable_reason()` 提供多层过滤，防止低质量内容进入持久记忆：

| 过滤条件 | 返回原因 | 说明 |
|----------|----------|------|
| 空文本 | `empty` | 无内容 |
| 含 `<redacted>` | `secret_shaped` | 已被脱敏 |
| 正则匹配 `api_key`, `token`, `secret`, `password`, `sk-*` | `secret_shaped` | 疑似秘密 |
| 以 checkpoint 前缀开头（current goal, next step 等） | `transient_task_state` | 属于瞬态任务状态 |
| 含 stdout/stderr/traceback/exit_code 或长度 > 220 | `noisy_output` | 噪声输出 |

### 6.4 Supersede（替换）机制

当同一 topic 下存在相同 subject 的笔记时，新笔记替换旧笔记：

```python
new_subject = self._subject_key(note_text)
if new_subject:
    for index, old_text in enumerate(list(existing)):
        if self._subject_key(old_text) == new_subject:
            superseded.append(f"{topic}: {old_text} -> {note_text}")
            existing[index] = note_text  # 替换
            replaced = True
            break
```

---

## 7. Memory System Section：注入给模型的记忆契约

pico-v3 通过 `build_memory_system_section()` 生成一段约 160 行的系统指令，作为 prompt 的一部分注入给模型（不仅对用户可见，也对 dream agent 可见）。

这段指令定义了：

- **记忆系统的目录结构**和文件位置
- **四种 memory 类型**（user, feedback, project, reference）及其适用场景
- **每种类型的保存时机**和结构化要求
- **What NOT to save**：排除清单（代码模式、git 历史、调试方案、secrets、原始输出、瞬态任务状态）
- **两种保存方式**：
  - `<memory>...</memory>` 标签（快速记录）
  - 直接写 topic 文件（结构化记忆）
- **Slash 命令**：`/remember`, `/memory`, `/dream` 的行为说明
- **Memory Index 约束**：每行 ~150 字符，是索引而非内容

这使得模型被"训练"成一个懂得如何管理自己记忆的 agent。

---

## 8. 安全边界：Secret 检测与噪声过滤

### 8.1 Secret 形状检测

```python
SECRET_SHAPED_TEXT_PATTERN = re.compile(
    r"(?i)(\b(api[_ -]?key|token|secret|password)\b|sk-[A-Za-z0-9_-]{6,})"
)
```

在 `reject_durable_reason()` 和 promotion 流程中被调用，防止 API key、token 等敏感信息被写入持久记忆。

### 8.2 Redacted Value 检测

如果文本中已经包含 `<redacted>`（运行时脱敏的占位符），也会被拒绝存储。

### 8.3 噪声检测

检测以下类型的文本并拒绝：
- 以 checkpoint 相关前缀开头的（current goal, current blocker, next step...）
- 包含 stdout/stderr/traceback/exit_code 等诊断输出的
- 长度超过 220 字符的长文本（通常是原始日志/输出）

---

## 9. 内存与召回：跨层统一检索

### 9.1 pico 的检索

pico 的 `retrieval_candidates()` 只在当前 session 的 episodic_notes 中检索：

```python
def retrieval_candidates(state, query, limit=3, workspace_root=None):
    ranked = []
    for note in state["episodic_notes"]:
        # 仅检索 ephemeral notes
        ...
    return [note for _, note in ranked[:limit]]
```

### 9.2 pico-v3 的跨层检索

pico-v3 的检索先查 episodic_notes，**再查 durable topics**，合并排序后返回：

```python
def retrieval_candidates(state, query, limit=3, workspace_root=None):
    # 1. 检索 episodic notes（短期）
    ranked = []
    for note in state["episodic_notes"]:
        ...
    
    # 2. 检索 durable topics（长期）
    if workspace_root is not None:
        durable_store = DurableMemoryStore(Path(workspace_root) / ".pico" / "memory")
        for note in durable_store.retrieval_candidates(query, limit=limit):
            ...
    
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [note for _, note in ranked[:limit]]
```

排分依据（与 pico 相同，保留了简单透明的设计原则）：
1. **exact_tag_match**：query tokens 是否命中了 note 的 tags（精确匹配权重最高）
2. **keyword_overlap**：query tokens 和 note 文本/source/tags 的重叠词数
3. **recency**：created_at 时间戳（越新越优先）
4. **note_index**：笔记序号

### 9.3 DurableMemoryStore 的独立检索

`DurableMemoryStore.retrieval_candidates()` 遍历所有 topic 的笔记，使用相同的排序逻辑，不依赖 embedding。

---

## 10. 事件与可观测性

pico-v3 将记忆操作全面接入 session event bus 和 trace 系统：

### 10.1 Session Events

| 事件 | 触发时机 |
|------|----------|
| `memory_note_appended` | 写入 daily log（/remember 或 <memory> 标签） |
| `auto_dream_started` | 后台 dream 线程启动 |
| `dream_consolidated` | Dream 完成（含 changed_files） |
| `memory_auto_dream_failed` | Dream 失败（含 error 信息） |

### 10.2 Trace Events

| 事件 | 触发时机 |
|------|----------|
| `memory_auto_dream_started` | Dream 启动 |
| `memory_auto_dream_finished` | Dream 完成 |
| `memory_auto_dream_failed` | Dream 失败 |
| `memory_auto_dream_skipped` | Dream 跳过（含 skip_reason） |

### 10.3 Memory Maintenance Report

每次 run 的 report 中包含 `memory_maintenance` 审计数据：

```json
{
  "memory_maintenance": {
    "memory_tags_appended": [...],
    "auto_dream": {
      "enabled": true,
      "triggered": true,
      "session_count": 8,
      "session_ids": [...],
      "changed_files": ["topics/key-decisions.md"],
      "status": "finished"
    },
    "errors": []
  }
}
```

---

## 11. 用户交互命令

pico-v3 新增了 4 个与记忆相关的 slash 命令：

| 命令 | pico | pico-v3 | 说明 |
|------|------|---------|------|
| `/memory` | 显示工作记忆 | 显示 durable memory index（MEMORY.md） | 行为改变 |
| `/working-memory` | 无 | 显示当前工作记忆 | 新增 |
| `/remember <text>` | 无 | 追加到 daily log | 新增 |
| `/dream` | 无 | 手动触发记忆整合 | 新增 |

---

## 12. 总结对照表

| 特性 | pico | pico-v3 |
|------|------|---------|
| **记忆架构** | 单层 Working Memory | 三层：Working + Daily Logs + Durable Topics |
| **跨 session 持久** | 需手动恢复 session | 自动文件持久化 |
| **记忆索引** | 无 | MEMORY.md |
| **自动整合** | 无 | Auto-Dream（后台线程） |
| **整合策略** | - | 四阶段：Orient → Gather → Consolidate → Prune |
| **并发控制** | - | 文件锁 + 进程存活检测 |
| **记忆分类** | 无 | 4 种主题（可扩展） |
| **note 类型** | 1 种（episodic） | 3 种（episodic / process / durable） |
| **写入方式** | 仅代码自动 | 自动 + /remember + <memory> 标签 |
| **智能提取** | 无 | 意图检测 + 模式匹配 promotion |
| **智能去重** | 无 | subject-based supersede |
| **Secret 检测** | 无 | 多模式正则 + redacted_value 检测 |
| **噪声过滤** | 无 | transient_task_state + noisy_output + empty |
| **跨层检索** | 仅 episodic notes | episodic notes + durable topics |
| **File freshness** | 写入时记录 | 主动失效检测（invalidate_stale） |
| **Prompt 注入** | 无 | Memory System Section 契约 |
| **事件可观测** | 无 | Session events + Trace events + Report audit |
| **用户/模型交互** | 仅 /memory | /memory, /working-memory, /remember, /dream |
| **Dream Agent** | - | 独立 Pico 子实例，受限 write_scope |
| **代码规模** | ~410 行 | ~1227 行（~3x） |
