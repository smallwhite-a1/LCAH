import pytest

from lcah.evaluation.analysis import (
    bootstrap_pass_rate_ci,
    classify_failure,
    paired_variant_summary,
    summarize_attempts,
    summarize_calibration,
)


def _row(task_id, attempt, variant, passed, cost=0.1, failure_category=""):
    return {
        "task_id": task_id,
        "task_family": "sanity",
        "attempt_index": attempt,
        "variant": variant,
        "status": "pass" if passed else "fail",
        "passed": passed,
        "usage": {"cost_usd": cost, "tool_steps": 2},
        "failure_category": failure_category,
    }


def test_summarize_attempts_reports_repeated_reliability_and_cost():
    rows = [
        _row("a", 0, "healthy", True),
        _row("a", 1, "healthy", True),
        _row("b", 0, "healthy", True),
        _row("b", 1, "healthy", False, failure_category="grader_failed"),
    ]

    summary = summarize_attempts(rows)

    assert summary["task_count"] == 2
    assert summary["attempt_count"] == 4
    assert summary["pass_rate"] == 0.75
    assert summary["pass_at_1"] == 1.0
    assert summary["pass_power_k"] == 0.5
    assert summary["cost_per_success_usd"] == pytest.approx(0.4 / 3)
    assert summary["failure_categories"] == {"grader_failed": 1}


def test_bootstrap_pass_rate_ci_is_deterministic_and_handles_edges():
    rows = [_row("a", 0, "v", True), _row("b", 0, "v", False)]

    assert bootstrap_pass_rate_ci(rows, samples=500, seed=9) == bootstrap_pass_rate_ci(
        rows, samples=500, seed=9
    )
    low, high = bootstrap_pass_rate_ci(rows, samples=500, seed=9)
    assert low == 0.0
    assert high == 1.0
    assert bootstrap_pass_rate_ci([_row("a", 0, "v", True)], samples=50) == (1.0, 1.0)


def test_paired_variant_summary_reports_delta_and_win_loss_ties():
    rows = [
        _row("a", 0, "healthy", True),
        _row("b", 0, "healthy", True),
        _row("c", 0, "healthy", False),
        _row("a", 0, "degraded", False, failure_category="injected_regression"),
        _row("b", 0, "degraded", True),
        _row("c", 0, "degraded", False, failure_category="grader_failed"),
    ]

    summary = paired_variant_summary(rows, baseline="healthy", treatment="degraded")

    assert summary["pair_count"] == 3
    assert summary["treatment_minus_baseline"] == pytest.approx(-1 / 3)
    assert summary["treatment_wins"] == 0
    assert summary["baseline_wins"] == 1
    assert summary["ties"] == 2

    with pytest.raises(ValueError, match="missing paired attempt"):
        paired_variant_summary(rows[:-1], baseline="healthy", treatment="degraded")


def test_classify_failure_prefers_explicit_category_and_has_stable_fallbacks():
    assert classify_failure({"failure_category": "injected_regression"}) == "injected_regression"
    assert classify_failure({"status": "error"}) == "runner_error"
    assert classify_failure({"status": "fail", "passed": False}) == "grader_failed"
    assert classify_failure({"status": "pass", "passed": True}) == ""


def test_summarize_calibration_reports_tiers_and_mutation_flips():
    production = [
        {**_row("a", 0, "production", True), "difficulty": "basic"},
        {**_row("b", 0, "production", True), "difficulty": "composite"},
        {**_row("c", 0, "production", False), "difficulty": "adversarial"},
        {**_row("d", 0, "production", True), "difficulty": "adversarial"},
    ]
    mutation = [
        {**row, "variant": "drop_state", "passed": row["task_id"] not in {"b", "c"}}
        for row in production
    ]

    summary = summarize_calibration(production + mutation, "production", ["drop_state"])

    assert summary["production_pass_rate"] == 0.75
    assert summary["difficulty"]["basic"]["pass_rate"] == 1.0
    assert summary["mutations"]["drop_state"]["flipped_task_ids"] == ["b"]
    assert summary["mutations"]["drop_state"]["score_delta"] == -0.25
