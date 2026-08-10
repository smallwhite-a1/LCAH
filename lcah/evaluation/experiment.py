"""Repeatable experiment orchestration for scripted and live LCAH runners."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import AttemptRecord, EvaluationTask, TaskManifest

Runner = Callable[[EvaluationTask, int, int, str], Mapping[str, object]]


@dataclass(frozen=True)
class ExperimentConfig:
    experiment_id: str
    variants: Mapping[str, Mapping[str, object]]
    attempts: int
    base_seed: int
    output_path: str | Path
    agent: Mapping[str, object]
    model: Mapping[str, object]
    budget: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.experiment_id.strip():
            raise ValueError("experiment_id is required")
        if self.attempts < 1:
            raise ValueError("attempts must be positive")
        if not self.variants:
            raise ValueError("variants must not be empty")


def _seed(base_seed: int, task_id: str, attempt_index: int) -> int:
    material = f"{base_seed}\0{task_id}\0{attempt_index}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big")


def _write_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _artifact(manifest: TaskManifest, config: ExperimentConfig, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_type": "evaluation_experiment",
        "experiment_id": config.experiment_id,
        "dataset": {"name": manifest.dataset_name, "version": manifest.dataset_version},
        "protocol": {
            "attempts_per_task": config.attempts,
            "base_seed": config.base_seed,
            "variants": {name: dict(flags) for name, flags in config.variants.items()},
            "agent": dict(config.agent),
            "model": dict(config.model),
            "budget": dict(config.budget),
        },
        "attempts": rows,
    }


def _record(
    manifest: TaskManifest,
    config: ExperimentConfig,
    task: EvaluationTask,
    variant: str,
    attempt_index: int,
    seed: int,
    result: Mapping[str, object],
) -> AttemptRecord:
    payload = {
        "schema_version": 1,
        "experiment_id": config.experiment_id,
        "dataset": {"name": manifest.dataset_name, "version": manifest.dataset_version},
        "task_id": task.task_id,
        "task_family": task.family,
        "difficulty": task.difficulty,
        "variant": variant,
        "attempt_index": attempt_index,
        "seed": seed,
        "agent": dict(config.agent),
        "model": dict(config.model),
        "budget": dict(config.budget),
        "feature_flags": dict(config.variants[variant]),
        "initial_workspace_hash": result.get("initial_workspace_hash", "sha256:unavailable"),
        "final_workspace_hash": result.get("final_workspace_hash", "sha256:unavailable"),
        "status": result.get("status", "pass" if result.get("passed") else "fail"),
        "passed": bool(result.get("passed")),
        "usage": result.get("usage", {}),
        "artifacts": result.get("artifacts", {}),
        "failure_category": result.get("failure_category", ""),
        "diagnostics": result.get("diagnostics", {}),
    }
    return AttemptRecord.from_dict(payload)


def run_experiment(
    manifest: TaskManifest,
    config: ExperimentConfig,
    runner: Runner,
) -> dict[str, Any]:
    """Run or resume all variant/task/attempt combinations."""

    output_path = Path(config.output_path)
    completed: dict[tuple[str, str, int], dict[str, Any]] = {}
    if output_path.exists():
        existing = json.loads(output_path.read_text(encoding="utf-8"))
        if existing.get("experiment_id") != config.experiment_id:
            raise ValueError("existing artifact belongs to a different experiment")
        for payload in existing.get("attempts", []):
            record = AttemptRecord.from_dict(payload)
            completed[record.key] = record.to_dict()

    ordered_keys = [
        (variant, task.task_id, attempt_index)
        for variant in config.variants
        for task in manifest.tasks
        for attempt_index in range(config.attempts)
    ]
    tasks_by_id = {task.task_id: task for task in manifest.tasks}
    for variant, task_id, attempt_index in ordered_keys:
        key = (variant, task_id, attempt_index)
        if key in completed:
            continue
        task = tasks_by_id[task_id]
        seed = _seed(config.base_seed, task_id, attempt_index)
        try:
            result = dict(runner(task, attempt_index, seed, variant))
        except Exception as exc:  # noqa: BLE001 - one attempt must not abort a batch
            result = {
                "status": "error",
                "passed": False,
                "initial_workspace_hash": "sha256:unavailable",
                "final_workspace_hash": "sha256:unavailable",
                "failure_category": "runner_error",
                "diagnostics": {"error": f"{type(exc).__name__}: {exc}"},
            }
        completed[key] = _record(
            manifest, config, task, variant, attempt_index, seed, result
        ).to_dict()
        rows = [completed[item] for item in ordered_keys if item in completed]
        _write_atomic(output_path, _artifact(manifest, config, rows))

    rows = [completed[item] for item in ordered_keys]
    artifact = _artifact(manifest, config, rows)
    _write_atomic(output_path, artifact)
    return artifact
