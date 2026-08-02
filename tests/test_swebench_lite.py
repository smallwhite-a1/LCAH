import json
import subprocess
import sys
from pathlib import Path

import pytest

from lcah.evaluation.swebench_lite import (
    build_manifest,
    load_task_records,
    run_batch,
    select_tasks,
    write_manifest,
)


def _record(index, **extra):
    record = {
        "instance_id": f"demo__repo-{index}",
        "repo": "demo/repo",
        "base_commit": f"commit-{index}",
        "problem_statement": f"Fix issue {index}.",
        "version": "1.0",
        "patch": "gold patch must not reach the agent",
        "test_patch": "gold test patch must not reach the agent",
        "FAIL_TO_PASS": [f"test_{index}"],
        "PASS_TO_PASS": [],
    }
    record.update(extra)
    return record


def test_load_task_records_strips_gold_and_grader_fields(tmp_path):
    source = tmp_path / "tasks.json"
    source.write_text(json.dumps({"tasks": [_record(1)]}), encoding="utf-8")

    task = load_task_records(source)[0]

    assert task == {
        "instance_id": "demo__repo-1",
        "repo": "demo/repo",
        "base_commit": "commit-1",
        "problem_statement": "Fix issue 1.",
        "version": "1.0",
    }


def test_selection_is_deterministic_and_smoke_subset_is_prefix_of_batch(tmp_path):
    source = tmp_path / "tasks.jsonl"
    source.write_text(
        "\n".join(json.dumps(_record(index)) for index in range(60)) + "\n",
        encoding="utf-8",
    )

    records = load_task_records(source)
    smoke = select_tasks(records, count=10, seed=42)
    batch = select_tasks(records, count=50, seed=42)

    assert [task["instance_id"] for task in smoke] == [
        task["instance_id"] for task in select_tasks(records, count=10, seed=42)
    ]
    assert [task["instance_id"] for task in smoke] == [
        task["instance_id"] for task in batch[:10]
    ]


def test_build_and_reload_manifest_has_exact_requested_count_and_no_gold_fields(tmp_path):
    source = tmp_path / "tasks.json"
    manifest_path = tmp_path / "manifest.json"
    source.write_text(json.dumps([_record(index) for index in range(12)]), encoding="utf-8")

    manifest = build_manifest(source, count=10, seed=7, source_name="test-fixture")
    write_manifest(manifest_path, manifest)
    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert persisted["benchmark"] == "swebench-lite"
    assert persisted["selection"] == {"count": 10, "seed": 7}
    assert len(persisted["tasks"]) == 10
    assert all(
        set(task) <= {"instance_id", "repo", "base_commit", "problem_statement", "version"}
        for task in persisted["tasks"]
    )


def test_swebench_cli_accepts_representative_100_task_batch(tmp_path):
    source = tmp_path / "tasks.json"
    manifest_path = tmp_path / "manifest-100.json"
    source.write_text(json.dumps([_record(index) for index in range(100)]), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_swebench_lite.py",
            "--tasks-file",
            str(source),
            "--count",
            "100",
            "--manifest-out",
            str(manifest_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["selection"]["count"] == 100


def test_build_manifest_rejects_count_larger_than_dataset(tmp_path):
    source = tmp_path / "tasks.json"
    source.write_text(json.dumps([_record(1)]), encoding="utf-8")

    with pytest.raises(ValueError, match="requested 10 tasks but dataset contains 1"):
        build_manifest(source, count=10, seed=0)


def test_load_manifest_rejects_gold_fields_reintroduced_after_generation(tmp_path):
    manifest_path = tmp_path / "unsafe-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark": "swebench-lite",
                "source": "test",
                "selection": {"count": 1, "seed": 0},
                "tasks": [_record(1)],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="outside the agent-visible"):
        from lcah.evaluation.swebench_lite import load_manifest

        load_manifest(manifest_path)


def test_run_batch_resumes_completed_rows_and_writes_summary(tmp_path):
    source = tmp_path / "tasks.json"
    manifest_path = tmp_path / "manifest.json"
    results_path = tmp_path / "results.json"
    source.write_text(json.dumps([_record(index) for index in range(3)]), encoding="utf-8")
    write_manifest(manifest_path, build_manifest(source, count=3, seed=0))

    calls = []

    def runner(task):
        calls.append(task["instance_id"])
        return {"status": "pass", "passed": True, "tool_steps": 2}

    first = run_batch(manifest_path, results_path, runner)
    second = run_batch(manifest_path, results_path, runner)

    assert len(calls) == 3
    assert first["summary"] == {
        "total_tasks": 3,
        "completed": 3,
        "passed": 3,
        "failed": 0,
        "pending": 0,
        "pass_rate": 1.0,
    }
    assert second["summary"] == first["summary"]
