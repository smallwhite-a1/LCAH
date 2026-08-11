"""Immutable evaluation configuration lock."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


class LockMismatch(ValueError):
    pass


@dataclass(frozen=True)
class EvaluationLock:
    dataset_digest: str
    grader_digest: str
    image_digest: str
    runtime: dict
    model: dict
    budget: dict
    repetitions: int
    randomization_seed: int
    statistics_version: str

    def to_dict(self):
        return {"schema_version": 1, **asdict(self)}

    def write(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")
        os.replace(temporary, destination)

    @classmethod
    def verify(cls, path: str | Path, current: EvaluationLock) -> None:
        persisted = json.loads(Path(path).read_text())
        for key, value in current.to_dict().items():
            if persisted.get(key) != value:
                raise LockMismatch(f"evaluation lock mismatch: {key}")
