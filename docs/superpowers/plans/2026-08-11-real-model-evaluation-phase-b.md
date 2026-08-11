# Real-model Evaluation Phase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reproducible repository environments and deterministic, grader-only scoring for SWE-bench Lite, LCAH-native, and security tasks.

**Architecture:** Environment provisioners prepare immutable workspaces without exposing grader data. Graders run outside the agent container/workspace and emit one normalized `GraderResult`; the official SWE-bench bridge delegates official test semantics to the upstream harness while native and security graders share the same output contract.

**Tech Stack:** Python 3.10+, Docker 29+, official `swebench` harness as an optional integration dependency, pytest, standard library subprocess/json/pathlib.

## Global Constraints

- Gold patches, hidden tests, grader commands, and canary values are grader-only.
- Docker images are referenced by immutable digest in formal locks.
- Graders never use model self-assessment.
- `environment_error` and `grader_error` are invalid runs, not task failures.
- Agent changes to tests or grader paths make the task fail.

---

### Task 1: Environment provisioner contract and LCAH-native workspace

**Files:**
- Create: `lcah/evaluation/real_agent/environment.py`
- Test: `tests/test_real_agent_environment.py`

**Interfaces:** `PreparedEnvironment`, `NativeEnvironmentProvisioner.prepare(task, attempt_root)`, `cleanup()`, and `workspace_digest()`.

- [ ] Write failing tests proving the fixture is copied at the pinned commit, `.git` is initialized, grader-only paths are absent, and two preparations have identical initial digests.
- [ ] Run `uv run pytest tests/test_real_agent_environment.py -q` and observe missing-module RED.
- [ ] Implement a provisioner that copies only declared fixture files, initializes a clean Git baseline, records runtime/image metadata, and rejects symlinks or paths escaping the fixture root.
- [ ] Run the tests and require GREEN.
- [ ] Commit `add native evaluation environments`.

### Task 2: Normalized strict grader and hidden-test isolation

**Files:**
- Create: `lcah/evaluation/real_agent/grading.py`
- Test: `tests/test_real_agent_grading.py`

**Interfaces:** `GraderResult`, `NativeGrader.grade(task, environment)`, `verify_protected_paths()`, and `classify_grader_failure()`.

- [ ] Write failing tests for pass, public regression, hidden failure, modified test, timeout, and grader execution error.
- [ ] Confirm RED.
- [ ] Implement subprocess grading outside workspace with explicit command argv, timeout, captured stdout/stderr blob references, protected-file hashes, and strict conjunction of public/hidden/regression checks.
- [ ] Require GREEN and commit `add strict native evaluation grader`.

### Task 3: Official SWE-bench harness bridge

**Files:**
- Create: `lcah/evaluation/real_agent/swebench.py`
- Test: `tests/test_real_agent_swebench.py`
- Modify: `scripts/run_real_agent_eval.py`

**Interfaces:** `SWEbenchHarness`, `check_swebench_installation()`, `build_prediction(instance_id, patch, model_name)`, and `parse_official_report(path)`.

- [ ] Write failing tests that assert the prediction JSONL contains only instance ID, model/agent name, and patch; official resolved/unresolved/error reports map correctly; missing harness yields an actionable dependency error.
- [ ] Confirm RED.
- [ ] Implement a subprocess bridge to the upstream harness without reimplementing `FAIL_TO_PASS`/`PASS_TO_PASS` semantics. Pin dataset name/version and image namespace in the evaluation lock.
- [ ] Require GREEN and commit `add official swebench grader bridge`.

### Task 4: Security canary and policy grader

**Files:**
- Create: `lcah/evaluation/real_agent/security.py`
- Test: `tests/test_real_agent_security.py`

**Interfaces:** `SecurityCanary`, `SecurityGrader.grade(attempt, trajectory, protected_root)`, and six boolean result axes from the approved design.

- [ ] Write failing tests for path escape, symlink escape, protected-file mutation, secret in trajectory, malicious checkpoint authorization, and a safe refusal that still completes the allowed task.
- [ ] Confirm RED.
- [ ] Implement canaries outside the workspace, exact pre/post digests, recursive secret scanning, permission-event inspection, and `overall_pass = all(applicable axes)`.
- [ ] Require GREEN and commit `add real evaluation security grader`.

### Task 5: Phase-B validation gate

**Files:**
- Create: `scripts/validate_real_eval_task.py`
- Test: `tests/test_real_agent_phase_b_gate.py`
- Modify: `README.md`

**Interfaces:** CLI validates initial failure, oracle success, regression stability, grader isolation, deterministic environment digest, and safety canary reachability without calling a model.

- [ ] Write a failing integration test around the committed smoke fixture and hidden grader.
- [ ] Confirm RED.
- [ ] Implement validation output with one row per gate and a nonzero exit when any gate fails.
- [ ] Run all `tests/test_real_agent_*.py`, focused Ruff, `git diff --check`, and a Docker-backed native fixture gate.
- [ ] Commit `add phase b evaluation gate`.

## Phase-B completion checkpoint

Phase B is complete when a native task passes every preflight gate, hidden tests are demonstrably absent from the workspace, protected-test modification is rejected, security canaries detect all tested attacks, the official SWE-bench bridge parses upstream reports, Docker is available, and the only remaining work is selecting/auditing the 24 public plus authoring/auditing the 36 LCAH-native tasks.
