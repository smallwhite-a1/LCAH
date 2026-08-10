"""Versioned, JSON-serializable contracts shared by capability evaluations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    normalized = dict(value)
    try:
        json.dumps(normalized)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field_name} must be JSON-serializable") from exc
    return normalized


def _required_text(mapping: Mapping[str, object], key: str) -> str:
    value = str(mapping.get(key, "")).strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


@dataclass(frozen=True)
class EvaluationTask:
    task_id: str
    prompt: str
    fixture: str
    grader: dict[str, Any]
    family: str
    difficulty: str = "basic"
    capabilities: tuple[str, ...] = ()
    expected_current_result: str = ""
    failure_mode: str = ""
    mutation_targets: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EvaluationTask:
        if "grader" not in value:
            raise ValueError("grader is required")
        difficulty = str(value.get("difficulty", "basic")).strip()
        if difficulty not in {"basic", "composite", "adversarial"}:
            raise ValueError("difficulty must be basic, composite, or adversarial")
        return cls(
            task_id=_required_text(value, "id"),
            prompt=_required_text(value, "prompt"),
            fixture=_required_text(value, "fixture"),
            grader=_mapping(value.get("grader"), "grader"),
            family=_required_text(value, "family"),
            difficulty=difficulty,
            capabilities=tuple(str(item).strip() for item in value.get("capabilities", []) if str(item).strip()),
            expected_current_result=str(value.get("expected_current_result", "")).strip(),
            failure_mode=str(value.get("failure_mode", "")).strip(),
            mutation_targets=tuple(
                str(item).strip() for item in value.get("mutation_targets", []) if str(item).strip()
            ),
            metadata=_mapping(value.get("metadata", {}), "metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.task_id,
            "prompt": self.prompt,
            "fixture": self.fixture,
            "grader": dict(self.grader),
            "family": self.family,
            "difficulty": self.difficulty,
            "capabilities": list(self.capabilities),
            "expected_current_result": self.expected_current_result,
            "failure_mode": self.failure_mode,
            "mutation_targets": list(self.mutation_targets),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class TaskManifest:
    dataset_name: str
    dataset_version: str
    tasks: tuple[EvaluationTask, ...]
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> TaskManifest:
        if int(value.get("schema_version", 0)) != SCHEMA_VERSION:
            raise ValueError("unsupported manifest schema_version")
        dataset = _mapping(value.get("dataset"), "dataset")
        raw_tasks = value.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise ValueError("tasks must be a non-empty list")
        tasks = tuple(EvaluationTask.from_dict(_mapping(item, "task")) for item in raw_tasks)
        ids = [task.task_id for task in tasks]
        duplicates = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate task id: {', '.join(duplicates)}")
        return cls(
            dataset_name=_required_text(dataset, "name"),
            dataset_version=_required_text(dataset, "version"),
            tasks=tasks,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset": {"name": self.dataset_name, "version": self.dataset_version},
            "tasks": [task.to_dict() for task in self.tasks],
        }


@dataclass(frozen=True)
class AttemptRecord:
    experiment_id: str
    dataset: dict[str, Any]
    task_id: str
    task_family: str
    difficulty: str
    variant: str
    attempt_index: int
    seed: int
    agent: dict[str, Any]
    model: dict[str, Any]
    budget: dict[str, Any]
    feature_flags: dict[str, Any]
    initial_workspace_hash: str
    final_workspace_hash: str
    status: str
    passed: bool
    usage: dict[str, Any]
    artifacts: dict[str, Any]
    failure_category: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    @property
    def key(self) -> tuple[str, str, int]:
        return self.variant, self.task_id, self.attempt_index

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> AttemptRecord:
        if int(value.get("schema_version", 0)) != SCHEMA_VERSION:
            raise ValueError("unsupported attempt schema_version")
        artifacts = _mapping(value.get("artifacts", {}), "artifacts")
        for name, artifact_path in artifacts.items():
            if artifact_path and Path(str(artifact_path)).is_absolute():
                raise ValueError(f"artifact path {name} must be relative")
        status = _required_text(value, "status")
        if status not in {"pass", "fail", "error", "skipped"}:
            raise ValueError(f"unsupported attempt status: {status}")
        return cls(
            experiment_id=_required_text(value, "experiment_id"),
            dataset=_mapping(value.get("dataset"), "dataset"),
            task_id=_required_text(value, "task_id"),
            task_family=_required_text(value, "task_family"),
            difficulty=str(value.get("difficulty", "")).strip(),
            variant=_required_text(value, "variant"),
            attempt_index=int(value.get("attempt_index", -1)),
            seed=int(value.get("seed", 0)),
            agent=_mapping(value.get("agent"), "agent"),
            model=_mapping(value.get("model"), "model"),
            budget=_mapping(value.get("budget"), "budget"),
            feature_flags=_mapping(value.get("feature_flags", {}), "feature_flags"),
            initial_workspace_hash=_required_text(value, "initial_workspace_hash"),
            final_workspace_hash=_required_text(value, "final_workspace_hash"),
            status=status,
            passed=bool(value.get("passed")),
            usage=_mapping(value.get("usage", {}), "usage"),
            artifacts=artifacts,
            failure_category=str(value.get("failure_category", "")).strip(),
            diagnostics=_mapping(value.get("diagnostics", {}), "diagnostics"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "dataset": dict(self.dataset),
            "task_id": self.task_id,
            "task_family": self.task_family,
            "difficulty": self.difficulty,
            "variant": self.variant,
            "attempt_index": self.attempt_index,
            "seed": self.seed,
            "agent": dict(self.agent),
            "model": dict(self.model),
            "budget": dict(self.budget),
            "feature_flags": dict(self.feature_flags),
            "initial_workspace_hash": self.initial_workspace_hash,
            "final_workspace_hash": self.final_workspace_hash,
            "status": self.status,
            "passed": self.passed,
            "usage": dict(self.usage),
            "artifacts": dict(self.artifacts),
            "failure_category": self.failure_category,
            "diagnostics": dict(self.diagnostics),
        }


def stable_workspace_hash(root: str | Path) -> str:
    """Hash agent-visible files while excluding LCAH's own run artifacts."""

    workspace = Path(root).resolve()
    digest = hashlib.sha256()
    files = sorted(
        (
            path
            for path in workspace.rglob("*")
            if path.is_file() and ".lcah" not in path.relative_to(workspace).parts
        ),
        key=lambda path: path.relative_to(workspace).as_posix(),
    )
    for path in files:
        relative = path.relative_to(workspace).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()
