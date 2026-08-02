from lcah.core.quality import (
    QUALITY_BLOCKED,
    QUALITY_COMPLETED,
    QUALITY_IN_PROGRESS,
    QUALITY_NO_PROGRESS,
    QUALITY_PASSED,
    QUALITY_REPAIR_REQUIRED,
    classify_progress,
    verify_checkpoint,
    verify_compaction_continuity,
    verify_prompt_continuity,
)
from lcah.core.task_state import TaskState


def checkpoint(**overrides):
    value = {
        "checkpoint_id": "ckpt_001",
        "current_goal": "Finish the task",
        "next_step": "Run the verifier",
        "current_blocker": "",
        "key_files": [{"path": "README.md", "freshness": "sha256:abc"}],
        "evidence": {"changed_paths": ["README.md"], "tool_steps": 1},
    }
    value.update(overrides)
    return value


def history_item(role, content, turn_id):
    return {"role": role, "content": content, "turn_id": turn_id}


def test_checkpoint_verifier_requires_actionable_state_and_evidence():
    result = verify_checkpoint(checkpoint())

    assert result["status"] == QUALITY_PASSED
    assert result["passed"] is True
    assert result["failures"] == []

    invalid = verify_checkpoint(checkpoint(next_step="", evidence=[]))

    assert invalid["status"] == QUALITY_REPAIR_REQUIRED
    assert invalid["passed"] is False
    assert "next_step" in invalid["failures"]
    assert "evidence" in invalid["failures"]


def test_compaction_verifier_preserves_recent_turns_and_summary_contract():
    old = [
        history_item("user", "old goal", "turn-1"),
        history_item("assistant", "old decision", "turn-1"),
        history_item("user", "latest request", "turn-2"),
        history_item("assistant", "latest answer", "turn-2"),
    ]
    summary = """Compacted session summary:
- Goal: old goal
- Prior user requests: old goal
- Constraints and preferences: -
- Acceptance checks: -
- Files read: README.md
- Files modified: -
- Key decisions: old decision
- Tests and outcomes: -
- Errors and blockers: -
- Dependencies and commands: -
- Current progress: compacted 2 history items
- Open blockers: -
- Next step: continue
- Evidence: -
- Critical context: preserve latest turns"""

    result = verify_compaction_continuity(
        old,
        [history_item("system", summary, "compact"), *old[2:]],
        summary,
        keep_recent_turns=1,
    )

    assert result["status"] == QUALITY_PASSED
    assert result["checks"]["recent_turns_preserved"] is True
    assert result["checks"]["summary_contract"] is True


def test_compaction_verifier_requires_critical_files_commands_and_outcomes():
    old = [
        history_item("user", "Implement the fix and run the test suite.", "turn-1"),
        {
            "role": "tool",
            "name": "read_file",
            "args": {"path": "lcah/core/runtime.py"},
            "content": "runtime implementation",
            "turn_id": "turn-1",
        },
        {
            "role": "tool",
            "name": "run_shell",
            "args": {"command": "pytest -q tests/test_quality.py"},
            "content": "2 passed",
            "turn_id": "turn-1",
        },
        history_item("assistant", "The verifier should preserve the runtime behavior.", "turn-1"),
        history_item("user", "Continue from the checkpoint.", "turn-2"),
    ]
    summary = """Compacted session summary:
- Goal: Implement the fix and run the test suite.
- Prior user requests: Implement the fix and run the test suite.
- Constraints and preferences: preserve the runtime behavior
- Acceptance checks: pytest -q tests/test_quality.py
- Files read: lcah/core/runtime.py
- Files modified: -
- Key decisions: preserve the runtime behavior
- Tests and outcomes: pytest -q tests/test_quality.py -> 2 passed
- Errors and blockers: -
- Dependencies and commands: pytest -q tests/test_quality.py
- Current progress: compacted 4 history items
- Open blockers: -
- Next step: continue from the latest preserved turn
- Evidence: files=lcah/core/runtime.py; tests=2 passed
- Critical context: lcah/core/runtime.py; pytest -q tests/test_quality.py; 2 passed"""

    result = verify_compaction_continuity(
        old,
        [history_item("system", summary, "compact"), old[-1]],
        summary,
        keep_recent_turns=1,
    )

    assert result["status"] == QUALITY_PASSED
    assert result["checks"]["critical_context_preserved"] is True

    incomplete = summary.replace("lcah/core/runtime.py", "runtime.py").replace("pytest -q tests/test_quality.py", "pytest")
    incomplete_result = verify_compaction_continuity(
        old,
        [history_item("system", incomplete, "compact"), old[-1]],
        incomplete,
        keep_recent_turns=1,
    )

    assert incomplete_result["status"] == QUALITY_REPAIR_REQUIRED
    assert "critical_context_preserved" in incomplete_result["failures"]


def test_compaction_verifier_requests_repair_when_recent_turn_is_lost():
    old = [
        history_item("user", "old goal", "turn-1"),
        history_item("user", "latest request", "turn-2"),
    ]
    summary = "Compacted session summary:\n- Goal: old goal\n- Next step: continue"

    result = verify_compaction_continuity(
        old,
        [history_item("system", summary, "compact")],
        summary,
        keep_recent_turns=1,
    )

    assert result["status"] == QUALITY_REPAIR_REQUIRED
    assert "recent_turns_preserved" in result["failures"]
    assert "summary_contract" in result["failures"]


def test_prompt_verifier_requires_exact_current_request_and_checkpoint():
    request = "Continue the implementation"
    checkpoint_text = "Task checkpoint:\n- Current goal: Finish the task\n- Next step: Run tests"
    result = verify_prompt_continuity(
        "Memory\n\n"
        + checkpoint_text
        + "\n\nCurrent user request:\n"
        + request,
        request,
        checkpoint_text,
    )

    assert result["status"] == QUALITY_PASSED

    invalid = verify_prompt_continuity("Current user request:\nContinue", request, checkpoint_text)

    assert invalid["status"] == QUALITY_REPAIR_REQUIRED
    assert "current_request" in invalid["failures"]
    assert "checkpoint" in invalid["failures"]


def test_progress_classifier_distinguishes_in_progress_blocked_no_progress_and_completed():
    running = TaskState.create("run_1", "task_1", "Keep working")
    assert classify_progress(running, trigger="tool_executed") == QUALITY_IN_PROGRESS

    blocked = TaskState.create("run_2", "task_2", "Keep working")
    blocked.stop_model_error("blocked")
    assert classify_progress(blocked, trigger="model_error") == QUALITY_BLOCKED

    unchanged = TaskState.create("run_3", "task_3", "Keep working")
    previous = {"evidence": {"tool_steps": 0, "changed_paths": []}}
    assert classify_progress(unchanged, previous, trigger="checkpoint") == QUALITY_NO_PROGRESS

    completed = TaskState.create("run_4", "task_4", "Finish")
    completed.finish_success("Done")
    assert classify_progress(completed, trigger="run_finished") == QUALITY_COMPLETED
