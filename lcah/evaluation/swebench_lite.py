"""Small, deterministic SWE-bench Lite task preparation utilities.

This module deliberately stops before the official SWE-bench Docker harness. It
prepares an agent-visible task manifest and provides a resumable batch runner
that can be connected to an LCAH session runner later.
"""

from __future__ import annotations

import json
import os
import random
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

MANIFEST_SCHEMA_VERSION = 1
BENCHMARK_NAME = "swebench-lite"
AGENT_VISIBLE_KEYS = (
    "instance_id",
    "repo",
    "base_commit",
    "problem_statement",
    "version",
)
TERMINAL_ROW_STATUSES = frozenset({"pass", "fail", "error", "skipped"})


def _read_records(path: Path) -> list[Mapping[str, object]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    payload = json.loads(text)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("tasks"), list):
        return payload["tasks"]
    raise ValueError("SWE-bench task source must be a list or an object with a tasks list")


def _normalize_task(record: Mapping[str, object], index: int) -> dict[str, str]:
    if not isinstance(record, Mapping):
        raise TypeError(f"SWE-bench task at index {index} must be an object")

    required = ("instance_id", "repo", "base_commit", "problem_statement")
    missing = [key for key in required if not str(record.get(key, "")).strip()]
    if missing:
        raise ValueError(
            f"SWE-bench task at index {index} is missing required fields: {', '.join(missing)}"
        )

    task = {
        key: str(record[key]).strip()
        for key in AGENT_VISIBLE_KEYS
        if key in record and str(record[key]).strip()
    }
    return task


def load_task_records(path: str | Path) -> list[dict[str, str]]:
    """Load task records while dropping gold patches and grader-only metadata."""

    source = Path(path)
    records = _read_records(source)
    normalized = [_normalize_task(record, index) for index, record in enumerate(records)]
    if not normalized:
        raise ValueError("SWE-bench task source must contain at least one task")

    ids = [task["instance_id"] for task in normalized]
    duplicates = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate SWE-bench instance_id: {', '.join(duplicates)}")
    return normalized


def select_tasks(
    tasks: Iterable[Mapping[str, object]], *, count: int, seed: int = 0
) -> list[dict[str, str]]:
    """Select a stable pseudo-random subset.

    Sorting before shuffling makes the same seed independent of source file
    ordering. Therefore a 10-task run is the prefix of the corresponding
    50-task run when both use the same source and seed.
    """

    if count < 1:
        raise ValueError("task count must be positive")
    normalized = sorted(
        (_normalize_task(task, index) for index, task in enumerate(tasks)),
        key=lambda task: task["instance_id"],
    )
    if count > len(normalized):
        raise ValueError(
            f"requested {count} tasks but dataset contains {len(normalized)}"
        )

    selected = list(normalized)
    random.Random(seed).shuffle(selected)
    return selected[:count]


def build_manifest(
    source_path: str | Path,
    *,
    count: int,
    seed: int = 0,
    source_name: str | None = None,
) -> dict[str, object]:
    """Build an agent-visible manifest for a 10- or 50-task experiment."""

    source = Path(source_path)
    tasks = select_tasks(load_task_records(source), count=count, seed=seed)
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "benchmark": BENCHMARK_NAME,
        "source": source_name or str(source),
        "selection": {"count": count, "seed": seed},
        "tasks": tasks,
    }


def _validate_manifest(manifest: Mapping[str, object]) -> dict[str, object]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported SWE-bench manifest schema_version")
    if manifest.get("benchmark") != BENCHMARK_NAME:
        raise ValueError("manifest benchmark must be swebench-lite")

    selection = manifest.get("selection")
    tasks = manifest.get("tasks")
    if not isinstance(selection, Mapping) or not isinstance(tasks, list):
        raise TypeError("manifest must contain selection and tasks")
    count = int(selection.get("count", 0))
    if count < 1 or len(tasks) != count:
        raise ValueError("manifest selection count does not match task count")

    for index, task in enumerate(tasks):
        if not isinstance(task, Mapping):
            raise TypeError(f"manifest task at index {index} must be an object")
        extra_fields = sorted(set(task) - set(AGENT_VISIBLE_KEYS))
        if extra_fields:
            raise ValueError(
                "manifest contains fields outside the agent-visible task schema: "
                + ", ".join(extra_fields)
            )

    normalized = [_normalize_task(task, index) for index, task in enumerate(tasks)]
    if len({task["instance_id"] for task in normalized}) != len(normalized):
        raise ValueError("manifest contains duplicate instance_id values")

    validated = dict(manifest)
    validated["tasks"] = normalized
    validated["selection"] = {"count": count, "seed": int(selection.get("seed", 0))}
    return validated


def load_manifest(path: str | Path) -> dict[str, object]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise TypeError("SWE-bench manifest must be an object")
    return _validate_manifest(manifest)


def write_manifest(path: str | Path, manifest: Mapping[str, object]) -> None:
    validated = _validate_manifest(manifest)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(validated, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _summary(rows: list[Mapping[str, object]], total_tasks: int) -> dict[str, object]:
    completed = sum(1 for row in rows if row.get("completed") is True)
    passed = sum(
        1
        for row in rows
        if row.get("completed") is True
        and (row.get("passed") is True or row.get("status") == "pass")
    )
    failed = completed - passed
    return {
        "total_tasks": total_tasks,
        "completed": completed,
        "passed": passed,
        "failed": failed,
        "pending": total_tasks - completed,
        "pass_rate": passed / total_tasks if total_tasks else 0.0,
    }


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def run_batch(
    manifest_path: str | Path,
    results_path: str | Path,
    runner: Callable[[Mapping[str, str]], Mapping[str, object]],
) -> dict[str, object]:
    """Run each manifest task once and resume rows already marked completed.

    ``runner`` owns workspace provisioning and LCAH/model execution. Its return
    value can include ``status``, ``passed`` and any diagnostic evidence.
    Exceptions are recorded as error rows so one task cannot erase the batch.
    """

    manifest = load_manifest(manifest_path)
    tasks = list(manifest["tasks"])
    destination = Path(results_path)
    existing_rows: dict[str, dict[str, object]] = {}
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        for row in existing.get("rows", []):
            instance_id = str(row.get("instance_id", ""))
            if instance_id:
                existing_rows[instance_id] = dict(row)

    rows_by_id = dict(existing_rows)
    for task in tasks:
        instance_id = task["instance_id"]
        previous = existing_rows.get(instance_id)
        if previous and previous.get("completed") is True:
            continue

        try:
            result = dict(runner(task))
            status = str(result.get("status", "pass" if result.get("passed") else "fail"))
            if status not in TERMINAL_ROW_STATUSES:
                raise ValueError(f"runner returned unsupported status: {status}")
            row = {
                "instance_id": instance_id,
                **result,
                "status": status,
                "passed": bool(result.get("passed", status == "pass")),
                "completed": True,
            }
        except Exception as exc:  # noqa: BLE001 - isolate one failed task from the batch
            row = {
                "instance_id": instance_id,
                "status": "error",
                "passed": False,
                "completed": True,
                "error": f"{type(exc).__name__}: {exc}",
            }
        rows_by_id[instance_id] = row

        ordered_rows = [
            rows_by_id[item["instance_id"]]
            for item in tasks
            if item["instance_id"] in rows_by_id
        ]

        artifact = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "benchmark": BENCHMARK_NAME,
            "manifest": str(Path(manifest_path)),
            "selection": manifest["selection"],
            "summary": _summary(ordered_rows, len(tasks)),
            "rows": ordered_rows,
        }
        _write_json_atomic(destination, artifact)

    rows = [
        rows_by_id[item["instance_id"]]
        for item in tasks
        if item["instance_id"] in rows_by_id
    ]
    artifact = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "benchmark": BENCHMARK_NAME,
        "manifest": str(Path(manifest_path)),
        "selection": manifest["selection"],
        "summary": _summary(rows, len(tasks)),
        "rows": rows,
    }
    _write_json_atomic(destination, artifact)
    return artifact
