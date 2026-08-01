"""Deterministic quality checks for resumable tasks and compacted context."""

QUALITY_PASSED = "passed"
QUALITY_REPAIR_REQUIRED = "repair_required"

QUALITY_IN_PROGRESS = "in_progress"
QUALITY_BLOCKED = "blocked"
QUALITY_NO_PROGRESS = "no_progress"
QUALITY_COMPLETED = "completed"
QUALITY_FAILED = "failed"

CHECKPOINT_REQUIRED_FIELDS = (
    "checkpoint_id",
    "current_goal",
    "next_step",
    "key_files",
    "evidence",
)

SUMMARY_CONTRACT = (
    "- Goal:",
    "- Constraints and preferences:",
    "- Files read:",
    "- Files modified:",
    "- Key decisions:",
    "- Current progress:",
    "- Open blockers:",
    "- Next step:",
    "- Critical context:",
)

BLOCKING_TRIGGERS = {
    "approval_denied",
    "model_error",
    "persistence_error",
    "resume_load_error",
    "tool_timeout",
}


def _verification(checks):
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "status": QUALITY_PASSED if not failures else QUALITY_REPAIR_REQUIRED,
        "passed": not failures,
        "checks": checks,
        "failures": failures,
    }


def verify_checkpoint(checkpoint):
    """Verify that a checkpoint can drive a safe resume."""

    checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
    checks = {
        field: bool(str(checkpoint.get(field, "")).strip())
        for field in CHECKPOINT_REQUIRED_FIELDS
        if field not in {"key_files", "evidence"}
    }
    checks["key_files"] = isinstance(checkpoint.get("key_files"), list)
    checks["evidence"] = isinstance(checkpoint.get("evidence"), dict)
    checks["next_step_actionable"] = bool(str(checkpoint.get("next_step", "")).strip())
    return _verification(checks)


def _turn_groups(history):
    groups = []
    by_id = {}
    for item in list(history or []):
        turn_id = str(item.get("turn_id") or "legacy")
        if turn_id not in by_id:
            by_id[turn_id] = []
            groups.append(by_id[turn_id])
        by_id[turn_id].append(item)
    return groups


def _flatten(groups):
    return [item for group in groups for item in group]


def verify_compaction_continuity(before, after, summary_text, keep_recent_turns=2):
    """Verify that compaction only summarizes old turns and preserves recent ones."""

    before = list(before or [])
    after = list(after or [])
    groups = _turn_groups(before)
    keep_recent_turns = max(0, int(keep_recent_turns))
    compacted = len(groups) > keep_recent_turns
    kept_items = _flatten(groups[-keep_recent_turns:]) if keep_recent_turns else []
    actual_suffix = after[-len(kept_items):] if kept_items else []
    checks = {
        "recent_turns_preserved": actual_suffix == kept_items,
        "summary_contract": not compacted or all(marker in str(summary_text or "") for marker in SUMMARY_CONTRACT),
        "history_is_compact": len(after) < len(before)
        if compacted
        else True,
    }
    return _verification(checks)


def verify_prompt_continuity(prompt, current_request, checkpoint_text=""):
    """Verify that lossy prompt reduction preserved control-plane context."""

    prompt = str(prompt or "")
    current_request = str(current_request or "")
    expected_request = f"Current user request:\n{current_request}"
    checks = {
        "current_request": prompt.endswith(expected_request),
        "checkpoint": not str(checkpoint_text or "") or str(checkpoint_text) in prompt,
    }
    return _verification(checks)


def classify_progress(task_state, previous_checkpoint=None, trigger="", new_paths=None):
    """Classify an intermediate task without treating unfinished work as failure."""

    if getattr(task_state, "status", "") == "completed":
        return QUALITY_COMPLETED
    if str(trigger or "") in BLOCKING_TRIGGERS:
        return QUALITY_BLOCKED
    if str(trigger or "") == QUALITY_NO_PROGRESS:
        return QUALITY_NO_PROGRESS

    previous_evidence = dict((previous_checkpoint or {}).get("evidence", {}) or {})
    previous_steps = int(previous_evidence.get("tool_steps", 0) or 0)
    current_steps = int(getattr(task_state, "tool_steps", 0) or 0)
    previous_paths = set(previous_evidence.get("changed_paths", []) or [])
    current_paths = set(getattr(task_state, "changed_paths", []) or [])
    current_paths.update(str(path) for path in (new_paths or []) if str(path).strip())
    if previous_checkpoint and current_steps <= previous_steps and current_paths <= previous_paths:
        return QUALITY_NO_PROGRESS
    return QUALITY_IN_PROGRESS
