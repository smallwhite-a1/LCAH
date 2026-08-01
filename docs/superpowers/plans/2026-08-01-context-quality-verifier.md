# Context Quality Verifier Implementation Plan

> **For agentic workers:** Implement this plan task-by-task with test-first cycles and verification after each task.

**Goal:** Make context compression observable and recoverable by verifying compaction continuity, preserving checkpoint prompts, and recording intermediate quality evidence.

**Architecture:** Add pure deterministic quality functions in `lcah/core/quality.py`. Integrate them at the compaction boundary, prompt assembly boundary, and checkpoint creation boundary. Keep the final task verifier based on executable workspace evidence.

**Tech Stack:** Python 3.10+, pytest, existing LCAH session/checkpoint/run-store architecture.

## Global Constraints

- Do not modify or stage the existing untracked `bug_demo.py` or `tests/delivery.html` files.
- Preserve the exact current-request section and the latest preserved history turns.
- Keep checkpoint fields additive and retain the existing checkpoint schema version for compatibility.
- Run targeted tests after each implementation cycle, then the full test suite and benchmark suite before pushing.

### Task 1: Add deterministic quality primitives

**Files:**
- Create: `lcah/core/quality.py`
- Test: `tests/test_quality.py`

- [ ] Write failing tests for checkpoint field validation, compaction suffix preservation, prompt continuity, and progress classification.
- [ ] Run `pytest tests/test_quality.py -q` and confirm the new tests fail because the module is absent.
- [ ] Implement the smallest pure functions and quality constants needed by the tests.
- [ ] Run the targeted test file and confirm it passes.

### Task 2: Add quality state and evidence to checkpoints

**Files:**
- Modify: `lcah/core/task_state.py`
- Modify: `lcah/core/runtime_checkpoints.py`
- Modify: `lcah/core/runtime.py`
- Test: `tests/test_task_state.py`
- Test: `tests/test_lcah.py`

- [ ] Add additive task-state fields for quality status and latest quality verification.
- [ ] Add checkpoint quality status and evidence from the current task state.
- [ ] Validate the created checkpoint before persisting it and expose quality fields in checkpoint prompt text.
- [ ] Add tests for in-progress, blocked, completed, and evidence-bearing checkpoints.

### Task 3: Protect checkpoint prompt content

**Files:**
- Modify: `lcah/core/context_manager.py`
- Modify: `lcah/core/compact.py`
- Test: `tests/test_context_manager.py`
- Test: `tests/test_context_governance_acceptance.py`

- [ ] Add a dedicated checkpoint section excluded from ordinary reduction.
- [ ] Run tests to verify exact current request and checkpoint survive aggressive memory reduction.
- [ ] Verify compaction before persisting replacement history and keep the original history on verification failure.
- [ ] Record compaction quality in session summaries and prompt metadata.

### Task 4: Add deterministic context-quality test set

**Files:**
- Create: `tests/test_context_quality_acceptance.py`
- Modify: `tests/test_evaluator.py` only if benchmark assertions need additive coverage.

- [ ] Add a matrix covering manual compaction, automatic compaction, stale checkpoint recovery, blocked progress, no progress, and completed progress.
- [ ] Run the targeted acceptance tests and confirm all quality states and artifact fields are observable.

### Task 5: Full verification and publish

- [ ] Run `pytest -q` with the project virtual environment.
- [ ] Run the deterministic benchmark test and standalone benchmark command.
- [ ] Inspect the diff and ensure only intended files are staged.
- [ ] Commit, push `agent/context-quality-verifier`, and open a draft Merge Request targeting `main`.
