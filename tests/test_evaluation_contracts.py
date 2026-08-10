import json

import pytest

from lcah.evaluation.contracts import AttemptRecord, TaskManifest, stable_workspace_hash


def _manifest_payload():
    return {
        "schema_version": 1,
        "dataset": {"name": "phase-one", "version": "2026-08-10"},
        "tasks": [
            {
                "id": "task-a",
                "prompt": "Fix the bug.",
                "fixture": "tests/fixtures/bench_repo_patch",
                "grader": {"kind": "command", "command": "pytest -q"},
                "family": "bugfix",
                "difficulty": "basic",
                "capabilities": ["localization"],
                "expected_current_result": "pass",
                "failure_mode": "",
                "mutation_targets": ["drop_context"],
                "metadata": {"human_minutes": 15},
            }
        ],
    }


def test_task_manifest_round_trips_and_rejects_duplicate_ids():
    manifest = TaskManifest.from_dict(_manifest_payload())

    assert manifest.dataset_name == "phase-one"
    assert manifest.tasks[0].task_id == "task-a"
    assert manifest.tasks[0].difficulty == "basic"
    assert manifest.tasks[0].mutation_targets == ("drop_context",)
    assert TaskManifest.from_dict(json.loads(json.dumps(manifest.to_dict()))) == manifest

    duplicate = _manifest_payload()
    duplicate["tasks"].append(dict(duplicate["tasks"][0]))
    with pytest.raises(ValueError, match="duplicate task id"):
        TaskManifest.from_dict(duplicate)


def test_task_manifest_requires_evaluation_fields():
    payload = _manifest_payload()
    del payload["tasks"][0]["grader"]

    with pytest.raises(ValueError, match="grader"):
        TaskManifest.from_dict(payload)


def test_task_manifest_rejects_unknown_difficulty():
    payload = _manifest_payload()
    payload["tasks"][0]["difficulty"] = "impossible"

    with pytest.raises(ValueError, match="difficulty"):
        TaskManifest.from_dict(payload)


def test_attempt_record_normalizes_metadata_and_rejects_absolute_artifact_paths():
    record = AttemptRecord.from_dict(
        {
            "schema_version": 1,
            "experiment_id": "exp-1",
            "dataset": {"name": "phase-one", "version": "2026-08-10"},
            "task_id": "task-a",
            "task_family": "bugfix",
            "variant": "healthy",
            "attempt_index": 0,
            "seed": 42,
            "agent": {"name": "lcah", "version": "abc123"},
            "model": {"provider": "test", "name": "scripted", "version": "v1"},
            "budget": {"max_steps": 20, "max_tokens": 1000, "timeout_seconds": 60},
            "feature_flags": {"memory": True},
            "initial_workspace_hash": "sha256:before",
            "final_workspace_hash": "sha256:after",
            "status": "pass",
            "passed": True,
            "usage": {"input_tokens": 10, "output_tokens": 2, "cost_usd": 0.01, "tool_steps": 3},
            "artifacts": {"trace": "runs/task-a/trace.jsonl"},
            "failure_category": "",
            "diagnostics": {"grader": "passed"},
        }
    )

    assert record.key == ("healthy", "task-a", 0)
    assert AttemptRecord.from_dict(record.to_dict()) == record

    invalid = record.to_dict()
    invalid["artifacts"]["trace"] = "/tmp/trace.jsonl"
    with pytest.raises(ValueError, match="relative"):
        AttemptRecord.from_dict(invalid)


def test_stable_workspace_hash_ignores_lcah_outputs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".lcah" / "runs").mkdir(parents=True)
    (tmp_path / ".lcah" / "runs" / "trace.jsonl").write_text("first\n", encoding="utf-8")

    first = stable_workspace_hash(tmp_path)
    (tmp_path / ".lcah" / "runs" / "trace.jsonl").write_text("changed\n", encoding="utf-8")
    assert stable_workspace_hash(tmp_path) == first

    (tmp_path / "src" / "app.py").write_text("value = 2\n", encoding="utf-8")
    assert stable_workspace_hash(tmp_path) != first
