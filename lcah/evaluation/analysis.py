"""Statistical summaries for repeated and paired agent evaluations."""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from statistics import mean


def classify_failure(row: Mapping[str, object]) -> str:
    explicit = str(row.get("failure_category", "")).strip()
    if explicit:
        return explicit
    if row.get("passed") is True or row.get("status") == "pass":
        return ""
    if row.get("status") == "error":
        return "runner_error"
    return "grader_failed"


def _task_rows(rows: Iterable[Mapping[str, object]]) -> dict[str, list[Mapping[str, object]]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["task_id"])].append(row)
    return dict(grouped)


def bootstrap_pass_rate_ci(
    rows: Iterable[Mapping[str, object]],
    *,
    samples: int = 2000,
    seed: int = 0,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Bootstrap whole tasks so attempts from one task stay correlated."""

    grouped = _task_rows(rows)
    if not grouped:
        return 0.0, 0.0
    if samples < 1:
        raise ValueError("samples must be positive")
    task_rates = [
        mean(1.0 if row.get("passed") is True else 0.0 for row in task_attempts)
        for task_attempts in grouped.values()
    ]
    rng = random.Random(seed)
    estimates = sorted(
        mean(rng.choice(task_rates) for _ in task_rates) for _ in range(samples)
    )
    tail = (1.0 - confidence) / 2.0
    lower = estimates[int(tail * (samples - 1))]
    upper = estimates[int((1.0 - tail) * (samples - 1))]
    return lower, upper


def summarize_attempts(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    rows = list(rows)
    grouped = _task_rows(rows)
    passed = sum(1 for row in rows if row.get("passed") is True)
    first_attempts = [
        min(task_rows, key=lambda row: int(row.get("attempt_index", 0)))
        for task_rows in grouped.values()
    ]
    strict_successes = sum(
        1 for task_rows in grouped.values() if all(row.get("passed") is True for row in task_rows)
    )
    total_cost = sum(float((row.get("usage") or {}).get("cost_usd", 0.0)) for row in rows)
    failures = Counter(classify_failure(row) for row in rows if row.get("passed") is not True)
    failures.pop("", None)
    ci_low, ci_high = bootstrap_pass_rate_ci(rows)
    return {
        "task_count": len(grouped),
        "attempt_count": len(rows),
        "passed_attempts": passed,
        "pass_rate": passed / len(rows) if rows else 0.0,
        "pass_rate_ci_95": [ci_low, ci_high],
        "pass_at_1": (
            sum(1 for row in first_attempts if row.get("passed") is True) / len(first_attempts)
            if first_attempts
            else 0.0
        ),
        "pass_power_k": strict_successes / len(grouped) if grouped else 0.0,
        "total_cost_usd": total_cost,
        "cost_per_success_usd": total_cost / passed if passed else None,
        "failure_categories": dict(sorted(failures.items())),
    }


def paired_variant_summary(
    rows: Iterable[Mapping[str, object]],
    *,
    baseline: str,
    treatment: str,
) -> dict[str, object]:
    indexed = {
        (str(row["variant"]), str(row["task_id"]), int(row.get("attempt_index", 0))): row
        for row in rows
    }
    baseline_keys = {(task_id, attempt) for variant, task_id, attempt in indexed if variant == baseline}
    treatment_keys = {(task_id, attempt) for variant, task_id, attempt in indexed if variant == treatment}
    if baseline_keys != treatment_keys:
        missing = sorted(baseline_keys.symmetric_difference(treatment_keys))
        raise ValueError(f"missing paired attempt: {missing[0] if missing else 'unknown'}")
    if not baseline_keys:
        raise ValueError("paired variants contain no attempts")

    baseline_wins = 0
    treatment_wins = 0
    ties = 0
    deltas = []
    for task_id, attempt in sorted(baseline_keys):
        baseline_pass = indexed[(baseline, task_id, attempt)].get("passed") is True
        treatment_pass = indexed[(treatment, task_id, attempt)].get("passed") is True
        delta = int(treatment_pass) - int(baseline_pass)
        deltas.append(delta)
        if delta > 0:
            treatment_wins += 1
        elif delta < 0:
            baseline_wins += 1
        else:
            ties += 1
    return {
        "baseline": baseline,
        "treatment": treatment,
        "pair_count": len(deltas),
        "baseline_pass_rate": mean(
            1.0 if indexed[(baseline, task_id, attempt)].get("passed") is True else 0.0
            for task_id, attempt in baseline_keys
        ),
        "treatment_pass_rate": mean(
            1.0 if indexed[(treatment, task_id, attempt)].get("passed") is True else 0.0
            for task_id, attempt in treatment_keys
        ),
        "treatment_minus_baseline": mean(deltas),
        "treatment_wins": treatment_wins,
        "baseline_wins": baseline_wins,
        "ties": ties,
    }


def summarize_calibration(
    rows: Iterable[Mapping[str, object]],
    production_variant: str,
    mutation_variants: Iterable[str],
) -> dict[str, object]:
    rows = list(rows)
    production = [row for row in rows if row.get("variant") == production_variant]
    if not production:
        raise ValueError("production variant contains no attempts")
    production_rate = sum(row.get("passed") is True for row in production) / len(production)
    difficulty = {}
    for tier in ("basic", "composite", "adversarial"):
        tier_rows = [row for row in production if row.get("difficulty") == tier]
        difficulty[tier] = {
            "task_count": len({str(row["task_id"]) for row in tier_rows}),
            "pass_rate": (
                sum(row.get("passed") is True for row in tier_rows) / len(tier_rows)
                if tier_rows
                else 0.0
            ),
        }
    mutations = {}
    production_by_key = {
        (str(row["task_id"]), int(row.get("attempt_index", 0))): row for row in production
    }
    for variant in mutation_variants:
        mutation_rows = [row for row in rows if row.get("variant") == variant]
        mutation_by_key = {
            (str(row["task_id"]), int(row.get("attempt_index", 0))): row for row in mutation_rows
        }
        if set(mutation_by_key) != set(production_by_key):
            raise ValueError(f"mutation {variant} does not match production attempts")
        flipped = sorted(
            {
                task_id
                for (task_id, attempt), production_row in production_by_key.items()
                if production_row.get("passed") is True
                and mutation_by_key[(task_id, attempt)].get("passed") is not True
            }
        )
        mutation_rate = sum(row.get("passed") is True for row in mutation_rows) / len(mutation_rows)
        mutations[variant] = {
            "pass_rate": mutation_rate,
            "score_delta": mutation_rate - production_rate,
            "flipped_task_ids": flipped,
        }
    return {
        "production_variant": production_variant,
        "production_pass_rate": production_rate,
        "difficulty": difficulty,
        "mutations": mutations,
    }
