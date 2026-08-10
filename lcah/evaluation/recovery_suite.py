"""Fault-injection probes for checkpoint and session recovery."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..core.runtime import LCAH
from ..core.session_store import SessionStore
from ..core.task_state import TaskState
from ..core.workspace import WorkspaceContext
from ..testing import ScriptedModelClient
from .contracts import EvaluationTask, TaskManifest

DEFAULT_MANIFEST = Path("benchmarks/module_eval_recovery.json")


def load_recovery_manifest(path: str | Path = DEFAULT_MANIFEST) -> TaskManifest:
    return TaskManifest.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _agent(root: Path, store: SessionStore) -> LCAH:
    return LCAH(
        model_client=ScriptedModelClient([]),
        workspace=WorkspaceContext.build(root, repo_root_override=root),
        session_store=store,
        approval_policy="auto",
        auto_dream=False,
    )


def _score(capability: str, resumed: LCAH, root: Path) -> tuple[bool, dict[str, object]]:
    checkpoint = resumed.current_checkpoint() or {}
    todos = resumed.session.get("todos", {}).get("items", [])
    operation_count = int(resumed.session.get("operation_count", 0))
    status = resumed.resume_state.get("status", "")
    checks = {
        "goal": checkpoint.get("current_goal") == "Resume the parser repair.",
        "completed_work": "parser edit committed" in checkpoint.get("completed", []),
        "todo": any(item.get("content") == "run parser tests" for item in todos),
        "workspace_state": (root / "work.txt").exists() and "committed edit" in (root / "work.txt").read_text(encoding="utf-8"),
        "runtime_drift": status == "workspace-mismatch",
        "file_freshness": status == "partial-stale",
        "schema_mismatch": status == "schema-mismatch",
        "exactly_once": operation_count == 1,
        "model_drift": status == "workspace-mismatch",
        "tool_drift": status == "workspace-mismatch",
        "double_resume": status == "full-valid" and any(
            item.get("content") == "run parser tests" for item in todos
        ),
        "consecutive_stale": status == "partial-stale",
        "event_gap": False,
        "result_gap": "after.txt" in checkpoint.get("evidence", {}).get("changed_paths", []),
        "compatible_change": status == "full-valid",
        "partial_damage": status != "full-valid",
    }
    passed = bool(checks[capability])
    diagnostics = {
        "resume_status": status,
        "state_equivalent": passed,
        "lost_progress": 0 if passed else 1,
        "duplicate_operations": max(0, operation_count - 1),
        "checkpoint_present": bool(checkpoint),
    }
    return passed, diagnostics


def run_recovery_case(
    task: EvaluationTask,
    attempt_index: int,
    seed: int,
    variant: str,
    workspace_root: str | Path | None = None,
) -> dict[str, object]:
    base = Path(workspace_root) if workspace_root is not None else Path(tempfile.mkdtemp())
    root = base / f"recovery-{task.task_id}-{variant}-{attempt_index}-{seed}"
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("recovery fixture\n", encoding="utf-8")
    (root / "work.txt").write_text("committed edit\n", encoding="utf-8")
    store = SessionStore(root / ".lcah" / "sessions")
    agent = _agent(root, store)
    agent.memory.remember_file("work.txt")
    agent.session["memory"] = agent.memory.to_dict()
    agent.todo_ledger.add("run parser tests")
    agent.session["operation_count"] = 1
    state = TaskState.create(task.task_id, "Resume the parser repair.")
    state.changed_paths.append("work.txt")
    state.finish_success("parser edit committed")
    agent.create_checkpoint(state, "Resume the parser repair.", "fault_injection")

    capability = str(task.metadata["capability"])
    if variant == "uninterrupted":
        passed = True
        diagnostics = {
            "resume_status": "uninterrupted",
            "state_equivalent": True,
            "lost_progress": 0,
            "duplicate_operations": 0,
            "checkpoint_present": True,
        }
    else:
        checkpoint = agent.current_checkpoint()
        if capability == "runtime_drift":
            checkpoint["runtime_identity"]["max_steps"] = agent.max_steps + 1
        elif capability == "file_freshness":
            (root / "work.txt").write_text("external edit\n", encoding="utf-8")
        elif capability == "schema_mismatch":
            checkpoint["schema_version"] = "legacy-v0"
        elif capability == "model_drift":
            checkpoint["runtime_identity"]["model"] = "different-model"
        elif capability == "tool_drift":
            checkpoint["runtime_identity"]["tool_signature"] = "different-tools"
        elif capability == "result_gap":
            (root / "after.txt").write_text("tool result not checkpointed\n", encoding="utf-8")
        elif capability == "compatible_change":
            (root / "unrelated.txt").write_text("compatible addition\n", encoding="utf-8")
        elif capability == "partial_damage":
            checkpoint.pop("next_step", None)

        if variant == "lossy_resume":
            if capability == "goal":
                checkpoint["current_goal"] = ""
            elif capability == "completed_work":
                checkpoint["completed"] = []
            elif capability == "todo":
                agent.session["todos"]["items"] = []
            elif capability == "workspace_state":
                (root / "work.txt").unlink()
            elif capability == "runtime_drift":
                checkpoint["runtime_identity"]["max_steps"] = agent.max_steps
            elif capability == "file_freshness":
                checkpoint["key_files"] = []
            elif capability == "schema_mismatch":
                checkpoint["schema_version"] = "phase1-v1"
            elif capability == "exactly_once":
                agent.session["operation_count"] = 2
        elif variant in task.mutation_targets:
            if variant == "drop_todos":
                agent.session["todos"]["items"] = []
            elif variant == "skip_freshness_check":
                checkpoint["key_files"] = []
            elif variant == "replay_committed_operation":
                agent.session["operation_count"] = 2
            elif variant == "ignore_schema_mismatch":
                checkpoint["schema_version"] = "phase1-v1"

        store.save(agent.session)
        resumed = LCAH.from_session(
            ScriptedModelClient([]),
            WorkspaceContext.build(root, repo_root_override=root),
            store,
            agent.session["id"],
            approval_policy="auto",
            auto_dream=False,
        )
        if capability in {"double_resume", "consecutive_stale"}:
            if capability == "consecutive_stale":
                (root / "work.txt").write_text("changed after first resume\n", encoding="utf-8")
            store.save(resumed.session)
            resumed = LCAH.from_session(
                ScriptedModelClient([]),
                WorkspaceContext.build(root, repo_root_override=root),
                store,
                resumed.session["id"],
                approval_policy="auto",
                auto_dream=False,
            )
        passed, diagnostics = _score(capability, resumed, root)

    return {
        "passed": passed,
        "status": "pass" if passed else "fail",
        "failure_category": "recovery_state_loss" if not passed else "",
        "initial_workspace_hash": "sha256:checkpointed",
        "final_workspace_hash": "sha256:resumed" if passed else "sha256:diverged",
        "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "tool_steps": 0},
        "diagnostics": diagnostics,
    }
