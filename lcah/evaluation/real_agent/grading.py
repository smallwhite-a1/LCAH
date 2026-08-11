"""Deterministic grader-only scoring for native repository tasks."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .contracts import TaskSpec
from .environment import PreparedEnvironment


@dataclass(frozen=True)
class GraderResult:
    status: str
    passed: bool
    valid_run: bool
    checks: dict[str, bool]
    failure_category: str
    public_stdout: str = ""
    public_stderr: str = ""
    hidden_stdout: str = ""
    hidden_stderr: str = ""

    def to_dict(self):
        return {
            "status": self.status, "passed": self.passed, "valid_run": self.valid_run,
            "checks": dict(self.checks), "failure_category": self.failure_category,
            "public_stdout": self.public_stdout, "public_stderr": self.public_stderr,
            "hidden_stdout": self.hidden_stdout, "hidden_stderr": self.hidden_stderr,
        }


def _command(value, workspace):
    if not isinstance(value, list) or not value:
        raise ValueError("grader command must be a non-empty argv list")
    return [str(item).replace("{workspace}", str(workspace)) for item in value]


class NativeGrader:
    def grade(self, task: TaskSpec, environment: PreparedEnvironment) -> GraderResult:
        timeout = int(task.grading.get("timeout_seconds", 60))
        try:
            public = subprocess.run(_command(task.grading.get("public_command"), environment.workspace),
                                    cwd=environment.workspace, capture_output=True, text=True,
                                    timeout=timeout, check=False)
            hidden = subprocess.run(_command(task.grading.get("hidden_command"), environment.workspace),
                                    cwd=environment.workspace.parent, capture_output=True, text=True,
                                    timeout=timeout, check=False)
            changed = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                                     cwd=environment.workspace, capture_output=True, text=True,
                                     check=False)
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            return GraderResult("grader_error", False, False, {}, "grader_error",
                                hidden_stderr=f"{type(exc).__name__}: {exc}")
        protected = set(map(str, task.grading.get("protected_paths", [])))
        changed_paths = set(changed.stdout.splitlines())
        checks = {
            "public_tests_passed": public.returncode == 0,
            "hidden_tests_passed": hidden.returncode == 0,
            "protected_paths_unchanged": not bool(protected & changed_paths),
        }
        if not checks["protected_paths_unchanged"]:
            failure = "protected_test_modified"
        elif not checks["public_tests_passed"]:
            failure = "public_test_failure"
        elif not checks["hidden_tests_passed"]:
            failure = "hidden_test_failure"
        else:
            failure = ""
        passed = all(checks.values())
        return GraderResult("pass" if passed else "fail", passed, True, checks, failure,
                            public.stdout, public.stderr, hidden.stdout, hidden.stderr)
