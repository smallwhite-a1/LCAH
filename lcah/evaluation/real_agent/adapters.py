"""Dataset adapters for real-agent evaluation manifests."""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import ContractError, TaskSpec


class AdapterError(ValueError):
    """Raised when source data cannot produce a safe task manifest."""


def _records(path: str | Path) -> list[dict]:
    source = Path(path)
    if source.suffix == ".jsonl":
        data = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    else:
        data = json.loads(source.read_text())
        if isinstance(data, dict):
            data = data.get("tasks")
    if not isinstance(data, list) or not data:
        raise AdapterError("dataset must contain a non-empty task list")
    return data


def _unique(tasks: list[TaskSpec]) -> tuple[TaskSpec, ...]:
    ids = [task.task_id for task in tasks]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise AdapterError(f"duplicate task ids: {', '.join(duplicates)}")
    return tuple(tasks)


class LCAHNativeAdapter:
    def load(self, path: str | Path) -> tuple[TaskSpec, ...]:
        try:
            return _unique([TaskSpec.from_dict(row) for row in _records(path)])
        except ContractError as exc:
            raise AdapterError(str(exc)) from exc


class SWEbenchAdapter:
    def __init__(self, module: str, image: str, license_name: str = "MIT"):
        self.module = module
        self.image = image
        self.license_name = license_name

    def load(self, path: str | Path) -> tuple[TaskSpec, ...]:
        tasks = []
        for row in _records(path):
            instance_id = str(row.get("instance_id", "")).strip()
            repo = str(row.get("repo", "")).strip()
            payload = {
                "schema_version": 1,
                "task_id": f"{self.module}-swe-{instance_id}",
                "source": {"dataset": "swebench_lite", "source_id": instance_id, "license": self.license_name},
                "repository": {
                    "url": f"https://github.com/{repo}",
                    "base_commit": row.get("base_commit", ""),
                    "image": self.image,
                },
                "instruction": {"text": row.get("problem_statement", ""), "language": "en"},
                "experiment": {"module": self.module, "condition_family": f"{self.module}-v1", "intervention": {}},
                "budget": {"max_steps": 80, "max_output_tokens": 64000, "timeout_seconds": 1800, "shell_timeout_seconds": 600},
                "grading": {
                    "type": "swebench",
                    "fail_to_pass": row.get("FAIL_TO_PASS", []),
                    "pass_to_pass": row.get("PASS_TO_PASS", []),
                    "oracle_patch": row.get("patch", ""),
                    "version": row.get("version", ""),
                },
                "difficulty": "composite",
                "capabilities": [self.module, "repository_task"],
            }
            try:
                tasks.append(TaskSpec.from_dict(payload))
            except ContractError as exc:
                raise AdapterError(f"invalid SWE-bench task {instance_id}: {exc}") from exc
        return _unique(tasks)


def scan_agent_view_for_leaks(task: TaskSpec) -> list[str]:
    visible = json.dumps(task.to_agent_dict(), sort_keys=True)
    findings = []
    oracle = str(task.grading.get("oracle_patch", ""))
    if oracle and oracle in visible:
        findings.append("oracle_patch_overlap")
    hidden = str(task.grading.get("hidden_test_bundle", ""))
    if hidden and hidden in visible:
        findings.append("hidden_test_overlap")
    return findings
