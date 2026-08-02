import json

from lcah import LCAH, SessionStore, WorkspaceContext
from lcah.core.quality import QUALITY_BLOCKED, QUALITY_COMPLETED, QUALITY_IN_PROGRESS
from lcah.core.task_state import TaskState
from lcah.testing import ScriptedModelClient


def build_agent(tmp_path, outputs=None):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    return LCAH(
        model_client=ScriptedModelClient(outputs or []),
        workspace=WorkspaceContext.build(tmp_path),
        session_store=SessionStore(tmp_path / ".lcah" / "sessions"),
        approval_policy="auto",
    )


def add_history(agent, count=6):
    for index in range(count):
        agent.record(
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"history-{index}",
                "created_at": f"2026-08-01T10:0{index}:00+00:00",
            }
        )


def test_manual_compaction_quality_is_auditable_and_preserves_latest_turn(tmp_path):
    agent = build_agent(tmp_path)
    add_history(agent)

    result = agent.compact_history(trigger="acceptance_manual", keep_recent_turns=2)

    assert result["applied"] is True
    assert result["quality_verification"]["passed"] is True
    assert result["quality_verification"]["checks"]["recent_turns_preserved"] is True
    summary = agent.session["history"][0]["content"]
    assert "- Next step:" in summary
    assert agent.session["history"][-2]["content"] == "history-4"
    assert agent.session["history"][-1]["content"] == "history-5"


def test_failed_compaction_keeps_original_history_intact(tmp_path):
    agent = build_agent(tmp_path)
    add_history(agent)
    before = list(agent.session["history"])
    agent.compact_manager._summary_text = lambda items: "invalid summary"

    result = agent.compact_history(trigger="acceptance_invalid", keep_recent_turns=2)

    assert result["applied"] is False
    assert result["quality_verification"]["status"] == "repair_required"
    assert agent.session["history"] == before
    assert agent.session.get("compactions", []) == []


def test_compaction_repairs_summary_once_before_applying(tmp_path):
    agent = build_agent(tmp_path)
    add_history(agent)
    original_summary_text = agent.compact_manager._summary_text
    calls = {"count": 0}

    def summary_with_one_repair(items):
        calls["count"] += 1
        if calls["count"] == 1:
            return "invalid summary"
        return original_summary_text(items)

    agent.compact_manager._summary_text = summary_with_one_repair

    result = agent.compact_history(trigger="acceptance_repair", keep_recent_turns=2)

    assert result["applied"] is True
    assert result["quality_repair_attempts"] == 1
    assert calls["count"] == 2
    assert agent.session.get("compactions")


def test_compaction_repair_appends_missing_critical_evidence(tmp_path):
    agent = build_agent(tmp_path)
    agent.record(
        {
            "role": "tool",
            "name": "run_shell",
            "args": {"command": "pytest -q tests/test_quality.py"},
            "content": "2 passed",
            "turn_id": "old-command",
            "created_at": "2026-08-01T10:00:00+00:00",
        }
    )
    add_history(agent, count=6)
    original_summary_text = agent.compact_manager._summary_text

    def summary_without_critical_evidence(items):
        return original_summary_text(items).replace("pytest -q tests/test_quality.py", "pytest")

    agent.compact_manager._summary_text = summary_without_critical_evidence

    result = agent.compact_history(trigger="acceptance_evidence_repair", keep_recent_turns=2)

    assert result["applied"] is True
    assert result["quality_repair_attempts"] == 1
    assert "pytest -q tests/test_quality.py" in agent.session["history"][0]["content"]


def test_compaction_summary_retains_commands_and_test_outcomes(tmp_path):
    agent = build_agent(tmp_path)
    summary = agent.compact_manager._summary_text(
        [
            {
                "role": "user",
                "content": "Fix the parser and verify it with pytest.",
                "turn_id": "turn-1",
            },
            {
                "role": "tool",
                "name": "read_file",
                "args": {"path": "lcah/core/compact.py"},
                "content": "source",
                "turn_id": "turn-1",
            },
            {
                "role": "tool",
                "name": "run_shell",
                "args": {"command": "pytest -q tests/test_context_quality_acceptance.py"},
                "content": "1 passed",
                "turn_id": "turn-1",
            },
            {
                "role": "assistant",
                "content": "Decision: preserve the verifier before editing behavior.",
                "turn_id": "turn-1",
            },
        ]
    )

    assert "- Acceptance checks:" in summary
    assert "- Tests and outcomes:" in summary
    assert "pytest -q tests/test_context_quality_acceptance.py" in summary
    assert "1 passed" in summary
    assert "lcah/core/compact.py" in summary
    assert "- Evidence:" in summary


def test_quality_evidence_is_written_to_report_and_prompt_metadata(tmp_path):
    agent = build_agent(tmp_path, ["<final>Done.</final>"])

    assert agent.ask("Finish the task") == "Done."

    report = json.loads((agent.current_run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["task_state"]["quality_status"] == QUALITY_COMPLETED
    assert report["task_state"]["quality_verification"]["passed"] is True
    assert report["prompt_metadata"]["quality_verification"]["passed"] is True
    trace_events = [
        json.loads(line)
        for line in (agent.current_run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    checkpoint_event = [event for event in trace_events if event["event"] == "checkpoint_created"][-1]
    assert checkpoint_event["quality_status"] == QUALITY_COMPLETED
    assert checkpoint_event["quality_verification"] == "passed"


def test_intermediate_quality_states_are_not_reported_as_completed(tmp_path):
    agent = build_agent(tmp_path)
    running = TaskState.create("run_1", "task_1", "Continue")
    running.record_tool("read_file")
    blocked = TaskState.create("run_2", "task_2", "Continue")
    blocked.stop_model_error("provider unavailable")

    running_checkpoint = agent.create_checkpoint(running, "Continue", trigger="tool_executed")
    blocked_checkpoint = agent.create_checkpoint(blocked, "Continue", trigger="model_error")

    assert running_checkpoint["quality_status"] == QUALITY_IN_PROGRESS
    assert blocked_checkpoint["quality_status"] == QUALITY_BLOCKED
    assert blocked.stop_reason == "model_error"
    assert blocked_checkpoint["quality_status"] != QUALITY_COMPLETED
