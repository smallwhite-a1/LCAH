# Real-model Evaluation Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the versioned, leak-resistant protocol, trajectory store, evaluation lock, and resumable paired-run foundation required before any official DeepSeek evaluation budget is spent.

**Architecture:** Add a new `lcah.evaluation.real_agent` package that is independent from scripted and module-direct evaluators. Dataset adapters emit an agent-visible `TaskSpec`; a content-addressed evidence store writes append-only attempt events; a frozen evaluation lock binds dataset, grader, runtime, model, budgets, and statistics; an orchestrator schedules paired attempts and resumes only terminal records.

**Tech Stack:** Python 3.10+, standard library dataclasses/json/hashlib/pathlib, pytest, existing LCAH provider/runtime interfaces.

## Global Constraints

- DeepSeek V4 Flash is the only model in v1; exact provider-returned model ID must be recorded.
- Formal budget is 80 tool steps, 64K cumulative output tokens, 1800 seconds per run, and 600 seconds per shell command.
- Agent-visible manifests must never contain gold patches, hidden tests, grader commands, or oracle output.
- Every file write is atomic; existing terminal attempts are immutable.
- Real secrets are never persisted; only secret type and redacted SHA-256 may be recorded.
- `REPORT.md` generated in later phases is Chinese.

---

### Task 1: Versioned real-agent task contracts

**Files:**
- Create: `lcah/evaluation/real_agent/__init__.py`
- Create: `lcah/evaluation/real_agent/contracts.py`
- Test: `tests/test_real_agent_contracts.py`

**Interfaces:**
- Produces: `TaskSpec.from_dict(value)`, `TaskSpec.to_agent_dict()`, `TaskSpec.to_dict()`, `RunBudget`, `AttemptIdentity`, and `ContractError`.
- Consumes: JSON-compatible mappings only.

- [ ] **Step 1: Write failing contract tests**

```python
def test_task_spec_excludes_grader_only_fields_from_agent_view():
    task = TaskSpec.from_dict(valid_task_payload())
    visible = task.to_agent_dict()
    assert visible["instruction"] == {"text": "Fix parser", "language": "en"}
    assert "grading" not in visible
    assert "oracle_patch" not in json.dumps(visible)

def test_task_spec_rejects_invalid_budget_and_unknown_module():
    payload = valid_task_payload()
    payload["budget"]["max_steps"] = 0
    with pytest.raises(ContractError, match="max_steps"):
        TaskSpec.from_dict(payload)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run pytest tests/test_real_agent_contracts.py -q`

Expected: import failure because `lcah.evaluation.real_agent.contracts` does not exist.

- [ ] **Step 3: Implement immutable validated contracts**

Implement dataclasses with explicit allowlists. `TaskSpec.to_agent_dict()` may expose only schema/task/source identifiers, repository reference, instruction, experiment module/condition family, budget, difficulty, and capabilities. Validate module in `compression|memory|recovery|security`, difficulty in `basic|composite|adversarial`, positive budgets, immutable commit/image identifiers, and required grader type without exposing grader payload.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/test_real_agent_contracts.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add lcah/evaluation/real_agent tests/test_real_agent_contracts.py
git commit -m "add real evaluation task contracts"
```

---

### Task 2: Dataset adapter boundary and leak detection

**Files:**
- Create: `lcah/evaluation/real_agent/adapters.py`
- Test: `tests/test_real_agent_adapters.py`

**Interfaces:**
- Consumes: SWE-bench JSON/JSONL rows or LCAH-native manifest mappings.
- Produces: `SWEbenchAdapter.load(path) -> tuple[TaskSpec, ...]`, `LCAHNativeAdapter.load(path) -> tuple[TaskSpec, ...]`, `scan_agent_view_for_leaks(task) -> list[str]`.

- [ ] **Step 1: Write failing adapter tests**

```python
def test_swebench_adapter_keeps_gold_fields_grader_only(tmp_path):
    source = write_swebench_row(tmp_path, patch="SECRET_GOLD_PATCH")
    task = SWEbenchAdapter(module="compression").load(source)[0]
    assert "SECRET_GOLD_PATCH" not in json.dumps(task.to_agent_dict())
    assert task.grading["oracle_patch"] == "SECRET_GOLD_PATCH"

def test_leak_scanner_rejects_agent_visible_oracle_material():
    task = TaskSpec.from_dict(native_payload(instruction="Apply SECRET_GOLD_PATCH"))
    assert scan_agent_view_for_leaks(task) == ["oracle_patch_overlap"]
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_real_agent_adapters.py -q`

Expected: adapter symbols are missing.

- [ ] **Step 3: Implement adapters and deterministic IDs**

Map SWE-bench `instance_id`, `repo`, `base_commit`, `problem_statement`, `version`, `FAIL_TO_PASS`, `PASS_TO_PASS`, `patch`, and environment reference into TaskSpec. Preserve original issue text. Put patch/test/oracle data only in `grading`. Reject duplicate task IDs and scan overlap between agent-visible text and oracle/hidden material.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/test_real_agent_adapters.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add lcah/evaluation/real_agent/adapters.py tests/test_real_agent_adapters.py
git commit -m "add real evaluation dataset adapters"
```

---

### Task 3: Content-addressed trajectory evidence

**Files:**
- Create: `lcah/evaluation/real_agent/evidence.py`
- Test: `tests/test_real_agent_evidence.py`

**Interfaces:**
- Produces: `EvidenceStore(root)`, `put_blob(bytes) -> str`, `start_attempt(identity, metadata)`, `append_event(attempt_path, event_type, payload)`, `finish_attempt(attempt_path, outcome)`.
- Event records contain `sequence`, UTC timestamp, event type, payload or payload ref, and previous-event hash.

- [ ] **Step 1: Write failing evidence tests**

```python
def test_evidence_store_deduplicates_blobs_and_hash_chains_events(tmp_path):
    store = EvidenceStore(tmp_path)
    first = store.put_blob(b"same")
    second = store.put_blob(b"same")
    assert first == second
    attempt = store.start_attempt(identity(), {"model": "deepseek-v4-flash"})
    store.append_event(attempt, "model_request", {"prompt": "hello"})
    store.append_event(attempt, "model_response", {"text": "world"})
    rows = read_jsonl(attempt / "trajectory.jsonl")
    assert [row["sequence"] for row in rows] == [1, 2]
    assert rows[1]["previous_event_sha256"] == event_digest(rows[0])

def test_secret_redaction_never_persists_secret_value(tmp_path):
    store = EvidenceStore(tmp_path, secret_values=["sk-live-secret"])
    attempt = store.start_attempt(identity(), {})
    store.append_event(attempt, "tool_result", {"output": "key=sk-live-secret"})
    assert "sk-live-secret" not in all_file_text(tmp_path)
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_real_agent_evidence.py -q`

Expected: evidence module is missing.

- [ ] **Step 3: Implement atomic JSON/JSONL and redaction**

Use SHA-256 blob paths, monotonic sequence validation, hash chaining, fsync plus atomic replace for metadata/outcome, and append+fsync for events. Recursively replace exact configured secret values with `{secret_detected, secret_type, redacted_sha256}` records before serialization.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/test_real_agent_evidence.py -q`

Expected: all tests pass, and an explicit repository search finds no test secret outside test source.

- [ ] **Step 5: Commit**

```bash
git add lcah/evaluation/real_agent/evidence.py tests/test_real_agent_evidence.py
git commit -m "add real evaluation trajectory evidence"
```

---

### Task 4: Evaluation lock and paired resumable scheduler

**Files:**
- Create: `lcah/evaluation/real_agent/lock.py`
- Create: `lcah/evaluation/real_agent/orchestrator.py`
- Test: `tests/test_real_agent_orchestrator.py`

**Interfaces:**
- Produces: `EvaluationLock.build(...)`, `EvaluationLock.verify(path, current)`, `build_schedule(tasks, repetitions, seed)`, `run_schedule(schedule, runner, evidence_store)`.
- Scheduler emits interleaved production/control attempts with a common `pair_id`; security tasks have only production condition.

- [ ] **Step 1: Write failing lock and schedule tests**

```python
def test_lock_rejects_dataset_or_budget_drift(tmp_path):
    lock = EvaluationLock.build(dataset_digest="sha256:a", grader_digest="sha256:b", runtime=runtime(), model=model(), budget=budget())
    lock.write(tmp_path / "evaluation-lock.json")
    changed = replace(lock, dataset_digest="sha256:changed")
    with pytest.raises(LockMismatch, match="dataset_digest"):
        EvaluationLock.verify(tmp_path / "evaluation-lock.json", changed)

def test_schedule_interleaves_pairs_and_resume_skips_only_terminal_attempts(tmp_path):
    schedule = build_schedule(two_capability_tasks(), repetitions=3, seed=20260810)
    assert len(schedule) == 12
    assert all(pair_conditions(schedule, pair) == {"production", "control"} for pair in pair_ids(schedule))
    runner = CountingRunner()
    run_schedule(schedule, runner, EvidenceStore(tmp_path))
    run_schedule(schedule, runner, EvidenceStore(tmp_path))
    assert runner.calls == 12
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_real_agent_orchestrator.py -q`

Expected: lock/orchestrator modules are missing.

- [ ] **Step 3: Implement immutable lock and scheduler**

Hash canonical JSON. Include dataset/grader/image/runtime/model/budget/repetitions/randomization/statistics versions. The scheduler deterministically randomizes pair order, alternates the first condition within pairs, records shared seeds, and treats only `pass|fail` plus a complete grader outcome as terminal. Errors remain resumable.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/test_real_agent_orchestrator.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add lcah/evaluation/real_agent/lock.py lcah/evaluation/real_agent/orchestrator.py tests/test_real_agent_orchestrator.py
git commit -m "add frozen paired evaluation scheduler"
```

---

### Task 5: DeepSeek factory, dry-run CLI, and Phase-A gate

**Files:**
- Create: `lcah/evaluation/real_agent/provider.py`
- Create: `scripts/run_real_agent_eval.py`
- Test: `tests/test_real_agent_provider.py`
- Test: `tests/test_real_agent_cli.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `build_deepseek_client(config, env)`, CLI modes `validate`, `dry-run`, and later `run`.
- `dry-run` uses an injected test runner and performs zero provider calls.

- [ ] **Step 1: Write failing provider/CLI tests**

```python
def test_deepseek_factory_requires_exact_model_and_does_not_serialize_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-value")
    client, metadata = build_deepseek_client({"model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com/anthropic"}, os.environ)
    assert metadata["model"] == "deepseek-v4-flash"
    assert "secret-value" not in json.dumps(metadata)

def test_dry_run_writes_lock_schedule_and_no_provider_attempts(tmp_path):
    code = main(["dry-run", "--manifest", fixture_manifest(), "--output", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "evaluation-lock.json").exists()
    assert (tmp_path / "run-manifest.json").exists()
    assert not list((tmp_path / "attempts").glob("**/trajectory.jsonl"))
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_real_agent_provider.py tests/test_real_agent_cli.py -q`

Expected: provider/CLI symbols are missing.

- [ ] **Step 3: Implement safe provider factory and dry-run CLI**

Resolve the DeepSeek profile through existing configuration conventions, require model `deepseek-v4-flash`, use the existing Anthropic-compatible client for the configured endpoint, and expose only sanitized metadata. `validate` checks contracts/leaks; `dry-run` validates, freezes, builds all schedule rows, and reports expected call count without calling the model. Reject `run` until Phase B supplies an environment provisioner and strict grader.

- [ ] **Step 4: Run the Phase-A gate**

Run:

```bash
uv run pytest tests/test_real_agent_contracts.py tests/test_real_agent_adapters.py tests/test_real_agent_evidence.py tests/test_real_agent_orchestrator.py tests/test_real_agent_provider.py tests/test_real_agent_cli.py -q
uv run ruff check lcah/evaluation/real_agent scripts/run_real_agent_eval.py tests/test_real_agent_*.py
git diff --check
```

Expected: all tests pass, lint is clean, and diff check exits 0.

- [ ] **Step 5: Commit**

```bash
git add lcah/evaluation/real_agent scripts/run_real_agent_eval.py tests/test_real_agent_provider.py tests/test_real_agent_cli.py README.md
git commit -m "add real evaluation dry-run gate"
```

## Phase-A completion checkpoint

Phase A is complete only when a canonical fixture manifest validates, a 48-task capability plus 12-task security schedule dry-runs to exactly 324 formal attempts, no provider call occurs in dry-run, lock drift is rejected, interrupted non-terminal attempts resume, terminal attempts remain immutable, and all evidence passes secret scanning.
