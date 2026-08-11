"""Reproducible, grader-isolated repository environments."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .contracts import TaskSpec


class EnvironmentError(RuntimeError):
    pass


def workspace_digest(root: str | Path) -> str:
    root = Path(root).resolve()
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in {".git", ".lcah"} for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


@dataclass(frozen=True)
class PreparedEnvironment:
    workspace: Path
    initial_digest: str
    image: str
    base_commit: str

    def cleanup(self) -> None:
        if self.workspace.exists():
            shutil.rmtree(self.workspace)


class NativeEnvironmentProvisioner:
    def prepare(self, task: TaskSpec, attempt_root: str | Path) -> PreparedEnvironment:
        fixture = Path(str(task.grading.get("fixture_root", ""))).resolve()
        if not fixture.is_dir():
            raise EnvironmentError(f"fixture_root is not a directory: {fixture}")
        for path in fixture.rglob("*"):
            if path.is_symlink():
                raise EnvironmentError(f"fixture symlink is not allowed: {path.relative_to(fixture)}")
        destination = Path(attempt_root).resolve() / "workspace"
        if destination.exists():
            raise EnvironmentError(f"attempt workspace already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(fixture, destination)
        protected = {Path(item).name for item in task.grading.get("protected_paths", [])}
        leaked = [path for path in destination.rglob("*") if path.is_file() and path.name in protected]
        if leaked:
            raise EnvironmentError(f"grader-only file leaked into workspace: {leaked[0].name}")
        commands = (["git", "init", "-q"], ["git", "add", "-A"],
                    ["git", "-c", "user.name=lcah-eval", "-c",
                     "user.email=eval@example.invalid", "commit", "-qm", "baseline"])
        for command in commands:
            result = subprocess.run(
                command, cwd=destination, capture_output=True, text=True, check=False
            )
            if result.returncode:
                raise EnvironmentError(result.stderr.strip() or "git initialization failed")
        return PreparedEnvironment(destination, workspace_digest(destination),
                                   str(task.repository["image"]), str(task.repository["base_commit"]))
