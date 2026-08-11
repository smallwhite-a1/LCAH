"""Versioned contracts for real-model repository-task evaluations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1
MODULES = frozenset({"compression", "memory", "recovery", "security"})
DIFFICULTIES = frozenset({"basic", "composite", "adversarial"})


class ContractError(ValueError):
    """Raised when an evaluation contract is incomplete or unsafe."""


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be an object")
    result = dict(value)
    try:
        json.dumps(result)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{name} must be JSON-serializable") from exc
    return result


def _text(value: Mapping[str, object], key: str, context: str = "") -> str:
    result = str(value.get(key, "")).strip()
    if not result:
        prefix = f"{context}." if context else ""
        raise ContractError(f"{prefix}{key} is required")
    return result


@dataclass(frozen=True)
class RunBudget:
    max_steps: int
    max_output_tokens: int
    timeout_seconds: int
    shell_timeout_seconds: int

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RunBudget:
        budget = _object(value, "budget")
        fields = {}
        for name in ("max_steps", "max_output_tokens", "timeout_seconds", "shell_timeout_seconds"):
            try:
                fields[name] = int(budget.get(name, 0))
            except (TypeError, ValueError) as exc:
                raise ContractError(f"budget.{name} must be an integer") from exc
            if fields[name] <= 0:
                raise ContractError(f"budget.{name} must be positive")
        if fields["shell_timeout_seconds"] > fields["timeout_seconds"]:
            raise ContractError("budget.shell_timeout_seconds cannot exceed timeout_seconds")
        return cls(**fields)

    def to_dict(self) -> dict[str, int]:
        return {
            "max_steps": self.max_steps,
            "max_output_tokens": self.max_output_tokens,
            "timeout_seconds": self.timeout_seconds,
            "shell_timeout_seconds": self.shell_timeout_seconds,
        }


@dataclass(frozen=True)
class AttemptIdentity:
    task_id: str
    condition: str
    repetition: int
    pair_id: str
    seed: int

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.condition.strip() or not self.pair_id.strip():
            raise ContractError("attempt identity text fields are required")
        if self.repetition < 0:
            raise ContractError("attempt repetition must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "condition": self.condition,
            "repetition": self.repetition,
            "pair_id": self.pair_id,
            "seed": self.seed,
        }


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    source: dict[str, Any]
    repository: dict[str, Any]
    instruction: dict[str, Any]
    experiment: dict[str, Any]
    budget: RunBudget
    grading: dict[str, Any]
    difficulty: str
    capabilities: tuple[str, ...]
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> TaskSpec:
        payload = _object(value, "task")
        if int(payload.get("schema_version", 0)) != SCHEMA_VERSION:
            raise ContractError("unsupported schema_version")
        source = _object(payload.get("source"), "source")
        repository = _object(payload.get("repository"), "repository")
        instruction = _object(payload.get("instruction"), "instruction")
        experiment = _object(payload.get("experiment"), "experiment")
        grading = _object(payload.get("grading"), "grading")
        for field in ("dataset", "source_id", "license"):
            _text(source, field, "source")
        for field in ("url", "base_commit", "image"):
            _text(repository, field, "repository")
        _text(instruction, "text", "instruction")
        _text(instruction, "language", "instruction")
        module = _text(experiment, "module", "experiment")
        if module not in MODULES:
            raise ContractError(f"experiment.module must be one of {sorted(MODULES)}")
        _text(experiment, "condition_family", "experiment")
        _text(grading, "type", "grading")
        difficulty = str(payload.get("difficulty", "")).strip()
        if difficulty not in DIFFICULTIES:
            raise ContractError(f"difficulty must be one of {sorted(DIFFICULTIES)}")
        raw_capabilities = payload.get("capabilities", [])
        if not isinstance(raw_capabilities, list):
            raise ContractError("capabilities must be a list")
        capabilities = tuple(str(item).strip() for item in raw_capabilities if str(item).strip())
        return cls(
            task_id=_text(payload, "task_id"),
            source=source,
            repository=repository,
            instruction=instruction,
            experiment=experiment,
            budget=RunBudget.from_dict(_object(payload.get("budget"), "budget")),
            grading=grading,
            difficulty=difficulty,
            capabilities=capabilities,
        )

    def to_agent_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "source": dict(self.source),
            "repository": dict(self.repository),
            "instruction": dict(self.instruction),
            "experiment": dict(self.experiment),
            "budget": self.budget.to_dict(),
            "difficulty": self.difficulty,
            "capabilities": list(self.capabilities),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.to_agent_dict(), "grading": dict(self.grading)}
