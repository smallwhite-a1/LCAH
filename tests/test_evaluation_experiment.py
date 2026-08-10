import json

from lcah.evaluation.contracts import TaskManifest
from lcah.evaluation.experiment import ExperimentConfig, run_experiment


def _manifest():
    return TaskManifest.from_dict(
        {
            "schema_version": 1,
            "dataset": {"name": "demo", "version": "v1"},
            "tasks": [
                {
                    "id": task_id,
                    "prompt": f"Run {task_id}",
                    "fixture": "fixture",
                    "grader": {"kind": "command", "command": "true"},
                    "family": "sanity",
                }
                for task_id in ("a", "b")
            ],
        }
    )


def _config(output_path, attempts=2):
    return ExperimentConfig(
        experiment_id="exp-demo",
        variants={"healthy": {"mode": "healthy"}, "degraded": {"mode": "degraded"}},
        attempts=attempts,
        base_seed=100,
        output_path=output_path,
        agent={"name": "lcah", "version": "test"},
        model={"provider": "test", "name": "scripted", "version": "v1"},
        budget={"max_steps": 10, "max_tokens": 1000, "timeout_seconds": 60},
    )


def test_run_experiment_repeats_tasks_and_aligns_seeds_across_variants(tmp_path):
    calls = []

    def runner(task, attempt_index, seed, variant):
        calls.append((variant, task.task_id, attempt_index, seed))
        return {
            "status": "pass",
            "passed": True,
            "initial_workspace_hash": "sha256:before",
            "final_workspace_hash": "sha256:after",
        }

    artifact = run_experiment(_manifest(), _config(tmp_path / "results.json"), runner)

    assert len(artifact["attempts"]) == 8
    seeds = {
        (row["task_id"], row["attempt_index"]): row["seed"]
        for row in artifact["attempts"]
        if row["variant"] == "healthy"
    }
    assert all(
        row["seed"] == seeds[(row["task_id"], row["attempt_index"])]
        for row in artifact["attempts"]
    )
    assert len(set(seeds.values())) == 4
    assert len(calls) == 8


def test_run_experiment_records_errors_and_resumes_completed_attempts(tmp_path):
    output_path = tmp_path / "results.json"
    calls = []

    def first_runner(task, attempt_index, seed, variant):
        calls.append((variant, task.task_id, attempt_index))
        if variant == "degraded" and task.task_id == "b":
            raise RuntimeError("injected")
        return {
            "status": "pass",
            "passed": True,
            "initial_workspace_hash": "sha256:before",
            "final_workspace_hash": "sha256:after",
            "usage": {"cost_usd": 0.1},
        }

    first = run_experiment(_manifest(), _config(output_path, attempts=1), first_runner)
    error = next(row for row in first["attempts"] if row["status"] == "error")
    assert error["failure_category"] == "runner_error"
    assert "RuntimeError: injected" in error["diagnostics"]["error"]
    assert json.loads(output_path.read_text(encoding="utf-8")) == first
    assert not output_path.with_suffix(".json.tmp").exists()

    run_experiment(
        _manifest(),
        _config(output_path, attempts=1),
        lambda *args: (_ for _ in ()).throw(AssertionError("must not rerun")),
    )
    assert len(calls) == 4


def test_run_experiment_passes_variant_feature_flags_to_records(tmp_path):
    artifact = run_experiment(
        _manifest(),
        _config(tmp_path / "results.json", attempts=1),
        lambda task, attempt_index, seed, variant: {
            "status": "fail" if variant == "degraded" else "pass",
            "passed": variant != "degraded",
            "initial_workspace_hash": "sha256:before",
            "final_workspace_hash": "sha256:after",
            "failure_category": "injected_regression" if variant == "degraded" else "",
            "artifacts": {"trace": f"runs/{variant}-{task.task_id}/trace.jsonl"},
        },
    )

    degraded = next(row for row in artifact["attempts"] if row["variant"] == "degraded")
    assert degraded["feature_flags"] == {"mode": "degraded"}
    assert degraded["failure_category"] == "injected_regression"
