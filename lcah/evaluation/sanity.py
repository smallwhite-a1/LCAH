"""Sensitivity check proving the evaluation foundation can detect regression."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .analysis import paired_variant_summary, summarize_attempts
from .contracts import TaskManifest
from .experiment import ExperimentConfig, run_experiment

DEFAULT_MANIFEST = Path("benchmarks/evaluation_foundation_sanity.json")


def _write_atomic(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def run_sanity(output_path: str | Path, manifest_path: str | Path = DEFAULT_MANIFEST) -> dict[str, object]:
    manifest = TaskManifest.from_dict(json.loads(Path(manifest_path).read_text(encoding="utf-8")))
    config = ExperimentConfig(
        experiment_id="evaluation-foundation-sanity-v1",
        variants={"healthy": {"sanity_mode": "healthy"}, "degraded": {"sanity_mode": "degraded"}},
        attempts=2,
        base_seed=20260810,
        output_path=output_path,
        agent={"name": "deterministic-sanity-runner", "version": "1"},
        model={"provider": "none", "name": "deterministic", "version": "1"},
        budget={"max_steps": 1, "max_tokens": 0, "timeout_seconds": 5},
    )

    def runner(task, attempt_index, seed, variant):
        failed = variant == "degraded" and task.task_id == "injected-regression"
        return {
            "status": "fail" if failed else "pass",
            "passed": not failed,
            "initial_workspace_hash": "sha256:unchanged",
            "final_workspace_hash": "sha256:unchanged",
            "failure_category": "injected_regression" if failed else "",
            "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "tool_steps": 0},
            "diagnostics": {"attempt_index": attempt_index, "seed": seed},
        }

    artifact = run_experiment(manifest, config, runner)
    paired = paired_variant_summary(artifact["attempts"], baseline="healthy", treatment="degraded")
    artifact["analysis"] = {
        "variants": {
            variant: summarize_attempts(
                row for row in artifact["attempts"] if row["variant"] == variant
            )
            for variant in config.variants
        },
        "paired": paired,
        "sensitivity_check": {
            "detected": paired["treatment_minus_baseline"] < 0,
            "expected_direction": "degraded_below_healthy",
        },
    }
    _write_atomic(Path(output_path), artifact)
    return artifact
