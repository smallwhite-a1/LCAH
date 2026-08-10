"""Unified phase-two runner for module capability evaluations."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .analysis import paired_variant_summary, summarize_attempts, summarize_calibration
from .compression_suite import load_compression_manifest, run_compression_case
from .experiment import ExperimentConfig, run_experiment
from .memory_suite import load_memory_manifest, run_memory_case
from .recovery_suite import load_recovery_manifest, run_recovery_case


def _write_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _analysis(rows, variants, strong, weak, mutations):
    paired = paired_variant_summary(rows, baseline=strong, treatment=weak)
    calibration = summarize_calibration(rows, strong, mutations)
    mutation_checks = {
        name: {
            "detected": 1 <= len(result["flipped_task_ids"]) <= 6
            and result["score_delta"] <= -0.0625,
            **result,
        }
        for name, result in calibration["mutations"].items()
    }
    return {
        "variants": {
            variant: summarize_attempts(row for row in rows if row["variant"] == variant)
            for variant in variants
        },
        "paired": paired,
        "calibration": calibration,
        "mutation_checks": mutation_checks,
        "sensitivity_check": {
            "detected": paired["treatment_minus_baseline"] < 0
            and all(item["detected"] for item in mutation_checks.values()),
            "comparison": f"{weak}_below_{strong}",
        },
    }


def _module_metrics(rows, fields):
    result = {}
    for variant in sorted({row["variant"] for row in rows}):
        selected = [row for row in rows if row["variant"] == variant]
        result[variant] = {
            field: sum(float(row.get("diagnostics", {}).get(field, 0)) for row in selected) / len(selected)
            for field in fields
        }
    return result


def run_module_capability_evals(output_dir: str | Path, repetitions: int = 3) -> dict[str, object]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    shared = {
        "attempts": int(repetitions),
        "base_seed": 20260810,
        "agent": {"name": "lcah-module-direct", "version": "phase-two-v1"},
        "model": {"provider": "none", "name": "module-direct", "version": "1"},
        "budget": {"max_steps": 0, "max_tokens": 0, "timeout_seconds": 30},
    }

    compression_manifest = load_compression_manifest()
    compression_variants = {
        "full_context": {"representation": "full"},
        "lcah_compression": {"representation": "production-summary"},
        "tail_truncation": {"representation": "tail-only"},
        "drop_commands": {"mutation": "drop_commands"},
        "latest_decision_only_bug": {"mutation": "latest_decision_only_bug"},
        "reduce_recent_turns": {"mutation": "reduce_recent_turns"},
        "skip_stale_cleanup": {"mutation": "skip_stale_cleanup"},
    }
    compression_path = output / "compression-capability.json"
    compression = run_experiment(
        compression_manifest,
        ExperimentConfig(
            experiment_id="compression-capability-v1",
            variants=compression_variants,
            output_path=compression_path,
            **shared,
        ),
        run_compression_case,
    )

    memory_manifest = load_memory_manifest()
    memory_variants = {
        "memory_on": {"memory": True},
        "memory_disabled": {"memory": False},
        "memory_irrelevant": {"memory": True, "irrelevant_injection": True},
        "retrieval_limit_one": {"mutation": "retrieval_limit_one"},
        "disable_conflict_replacement": {"mutation": "disable_conflict_replacement"},
        "similar_distractor_injection": {"mutation": "similar_distractor_injection"},
        "skip_forbidden_filter": {"mutation": "skip_forbidden_filter"},
    }
    memory_path = output / "memory-capability.json"
    memory_workspace = output / "workspaces" / "memory"
    memory = run_experiment(
        memory_manifest,
        ExperimentConfig(
            experiment_id="memory-capability-v1",
            variants=memory_variants,
            output_path=memory_path,
            **shared,
        ),
        lambda task, attempt, seed, variant: run_memory_case(
            task, attempt, seed, variant, memory_workspace
        ),
    )

    recovery_manifest = load_recovery_manifest()
    recovery_variants = {
        "uninterrupted": {"checkpoint": False},
        "checkpoint_resume": {"checkpoint": True},
        "lossy_resume": {"checkpoint": True, "lossy": True},
        "drop_todos": {"mutation": "drop_todos"},
        "skip_freshness_check": {"mutation": "skip_freshness_check"},
        "replay_committed_operation": {"mutation": "replay_committed_operation"},
        "ignore_schema_mismatch": {"mutation": "ignore_schema_mismatch"},
    }
    recovery_path = output / "recovery-capability.json"
    recovery_workspace = output / "workspaces" / "recovery"
    recovery = run_experiment(
        recovery_manifest,
        ExperimentConfig(
            experiment_id="recovery-capability-v1",
            variants=recovery_variants,
            output_path=recovery_path,
            **shared,
        ),
        lambda task, attempt, seed, variant: run_recovery_case(
            task, attempt, seed, variant, recovery_workspace
        ),
    )

    artifact = {
        "schema_version": 1,
        "artifact_type": "module_capability_summary",
        "repetitions": int(repetitions),
        "modules": {
            "compression": {
                "task_count": len(compression_manifest.tasks),
                "artifact": compression_path.name,
                "analysis": _analysis(
                    compression["attempts"], compression_variants, "lcah_compression", "tail_truncation",
                    ("drop_commands", "latest_decision_only_bug", "reduce_recent_turns", "skip_stale_cleanup"),
                ),
                "metrics": _module_metrics(
                    compression["attempts"], ("critical_recall", "stale_leakage", "compression_ratio")
                ),
            },
            "memory": {
                "task_count": len(memory_manifest.tasks),
                "artifact": memory_path.name,
                "analysis": _analysis(
                    memory["attempts"], memory_variants, "memory_on", "memory_disabled",
                    ("retrieval_limit_one", "disable_conflict_replacement", "similar_distractor_injection", "skip_forbidden_filter"),
                ),
                "metrics": _module_metrics(
                    memory["attempts"],
                    ("write_count", "retrieval_recall", "forbidden_persistence", "superseded_count"),
                ),
            },
            "recovery": {
                "task_count": len(recovery_manifest.tasks),
                "artifact": recovery_path.name,
                "analysis": _analysis(
                    recovery["attempts"], recovery_variants, "checkpoint_resume", "lossy_resume",
                    ("drop_todos", "skip_freshness_check", "replay_committed_operation", "ignore_schema_mismatch"),
                ),
                "metrics": _module_metrics(
                    recovery["attempts"], ("state_equivalent", "lost_progress", "duplicate_operations")
                ),
            },
        },
    }
    _write_atomic(output / "module-capability-summary.json", artifact)
    return artifact
