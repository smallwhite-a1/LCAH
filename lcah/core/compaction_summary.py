"""Structured summaries for compacted session history."""

import re


def build_summary(items):
    files_read = []
    files_modified = []
    user_requests = []
    assistant_notes = []
    acceptance_checks = []
    commands = []
    test_outcomes = []
    errors_blockers = []
    tool_names = []
    changed_paths = []
    outcome_pattern = re.compile(
        r"\b(?:pytest|test[_\w.-]*|passed?|failed?|failure|error|exception|traceback)\b",
        re.IGNORECASE,
    )
    acceptance_pattern = re.compile(
        r"\b(?:must|should|required|verify|test|preserve|constraint)\b|必须|需要|验收|验证|保持|不要",
        re.IGNORECASE,
    )

    def add_unique(target, value, limit=240):
        value = " ".join(str(value or "").split()).strip()
        if value and value not in target:
            target.append(value[:limit])

    for item in items:
        if item.get("role") == "user":
            request = str(item.get("content", "")).strip()
            add_unique(user_requests, request)
            if acceptance_pattern.search(request):
                add_unique(acceptance_checks, request)
        elif item.get("role") == "assistant":
            add_unique(assistant_notes, item.get("content", ""))
        elif item.get("role") == "tool":
            add_unique(tool_names, item.get("name", ""))
            args = item.get("args", {}) or {}
            path = str(args.get("path", "")).strip()
            if item.get("name") == "read_file" and path:
                add_unique(files_read, path)
            if item.get("name") in {"write_file", "patch_file"} and path:
                add_unique(files_modified, path)
                add_unique(changed_paths, path)
            command = str(args.get("command", "")).strip()
            if command:
                add_unique(commands, command)
            content = " ".join(str(item.get("content", "")).split()).strip()
            if content and outcome_pattern.search(content):
                for fragment in re.split(r"\s*[;\n]\s*", content):
                    if outcome_pattern.search(fragment):
                        add_unique(test_outcomes, fragment)
                        if re.search(r"failed?|failure|error|exception|traceback", fragment, re.IGNORECASE):
                            add_unique(errors_blockers, fragment)

    decisions = [
        note
        for note in assistant_notes
        if re.search(r"decision|choose|preserve|保持|决定|选择", note, re.IGNORECASE)
    ]
    decisions = decisions or assistant_notes[-3:]
    constraints = acceptance_checks or ["-"]
    critical_context = [*files_read, *files_modified, *commands, *test_outcomes, *errors_blockers]
    evidence = [
        f"tools={len(tool_names)} ({', '.join(tool_names) or '-'})",
        f"changed_paths={', '.join(changed_paths) or '-'}",
        f"tests={len(test_outcomes)}",
    ]
    prior_user_requests = user_requests[-3:]
    return "\n".join(
        [
            "Compacted session summary:",
            f"- Goal: {user_requests[-1] if user_requests else '-'}",
            f"- Prior user requests: {' | '.join(prior_user_requests) or '-'}",
            f"- Constraints and preferences: {' | '.join(constraints)}",
            f"- Acceptance checks: {' | '.join(acceptance_checks) or '-'}",
            f"- Files read: {', '.join(sorted(set(files_read))) or '-'}",
            f"- Files modified: {', '.join(sorted(set(files_modified))) or '-'}",
            f"- Key decisions: {' | '.join(decisions) or '-'}",
            f"- Tests and outcomes: {' | '.join(test_outcomes) or '-'}",
            f"- Errors and blockers: {' | '.join(errors_blockers) or '-'}",
            f"- Dependencies and commands: {' | '.join(commands) or '-'}",
            f"- Current progress: compacted {len(items)} history items",
            f"- Open blockers: {' | '.join(errors_blockers) or '-'}",
            "- Next step: continue from the latest preserved turn",
            f"- Evidence: {'; '.join(evidence)}",
            f"- Critical context: {'; '.join(critical_context) or 'earlier turns were compacted; use preserved latest turns for exact wording'}",
        ]
    )
