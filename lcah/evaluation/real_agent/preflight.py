"""Model-free preflight gates for formal real-agent tasks."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .contracts import TaskSpec
from .environment import NativeEnvironmentProvisioner
from .grading import NativeGrader


def _argv(value, workspace):
    return [str(item).replace("{workspace}", str(workspace)) for item in value]


def validate_native_task(task: TaskSpec, output_root: str | Path) -> dict:
    root = Path(output_root)
    provisioner = NativeEnvironmentProvisioner()
    first = provisioner.prepare(task, root / "first")
    second = provisioner.prepare(task, root / "second")
    grader_only = {Path(item).name for item in task.grading.get("grader_only_paths", [])}
    leaked = [path for path in first.workspace.rglob("*")
              if path.is_file() and path.name in grader_only]
    public = subprocess.run(_argv(task.grading["public_command"], first.workspace),
                            cwd=first.workspace, capture_output=True, text=True,
                            timeout=int(task.grading.get("timeout_seconds", 60)), check=False)
    patch = str(task.grading.get("oracle_patch", ""))
    applied = subprocess.run(["git", "apply", "--whitespace=error-all", "-"],
                             cwd=first.workspace, input=patch, capture_output=True,
                             text=True, check=False)
    strict = NativeGrader().grade(task, first) if applied.returncode == 0 else None
    gates = {
        "deterministic_environment": first.initial_digest == second.initial_digest,
        "grader_isolated": not leaked,
        "initial_public_failure": public.returncode != 0,
        "oracle_patch_applied": applied.returncode == 0,
        "oracle_strict_pass": bool(strict and strict.passed),
        "protected_paths_unchanged": bool(strict and strict.checks.get("protected_paths_unchanged")),
    }
    return {"schema_version": 1, "task_id": task.task_id, "passed": all(gates.values()),
            "gates": gates, "diagnostics": {"initial_public_stderr": public.stderr,
            "oracle_apply_stderr": applied.stderr}}
