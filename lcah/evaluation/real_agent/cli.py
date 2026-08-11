"""Validation and dry-run entry point for real-agent evaluations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from .adapters import LCAHNativeAdapter, scan_agent_view_for_leaks
from .lock import EvaluationLock
from .orchestrator import build_schedule


def _digest(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _atomic(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "dry-run"):
        command = sub.add_parser(name)
        command.add_argument("--manifest", required=True)
        command.add_argument("--output", required=True)
        command.add_argument("--repetitions", type=int, default=3)
        command.add_argument("--seed", type=int, default=20260810)
    args = parser.parse_args(argv)
    tasks = LCAHNativeAdapter().load(args.manifest)
    leaks = {task.task_id: scan_agent_view_for_leaks(task) for task in tasks
             if scan_agent_view_for_leaks(task)}
    if leaks:
        raise ValueError(f"agent-visible grader leakage: {leaks}")
    if args.command == "validate":
        return 0
    schedule = build_schedule(tasks, args.repetitions, args.seed)
    output = Path(args.output)
    lock = EvaluationLock(_digest(args.manifest), "sha256:unfrozen-grader",
                          "sha256:unfrozen-image", {"commit": "dry-run"},
                          {"provider": "deepseek", "model": "deepseek-v4-flash"},
                          tasks[0].budget.to_dict(), args.repetitions, args.seed, "v1")
    lock.write(output / "evaluation-lock.json")
    _atomic(output / "run-manifest.json", {"schema_version": 1, "dry_run": True,
            "task_count": len(tasks), "attempt_count": len(schedule),
            "schedule": [item.identity.to_dict() for item in schedule]})
    return 0
