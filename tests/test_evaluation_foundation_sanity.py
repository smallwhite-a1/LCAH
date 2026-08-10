import json

from lcah.evaluation.sanity import run_sanity


def test_sanity_eval_detects_injected_regression_and_is_reproducible(tmp_path):
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"

    first = run_sanity(first_path)
    second = run_sanity(second_path)

    assert first["analysis"] == second["analysis"]
    assert first["analysis"]["paired"]["pair_count"] == 4
    assert first["analysis"]["paired"]["treatment_minus_baseline"] == -0.5
    assert first["analysis"]["sensitivity_check"] == {
        "detected": True,
        "expected_direction": "degraded_below_healthy",
    }
    assert {
        (row["task_id"], row["attempt_index"])
        for row in first["attempts"]
        if row["variant"] == "healthy"
    } == {
        (row["task_id"], row["attempt_index"])
        for row in first["attempts"]
        if row["variant"] == "degraded"
    }
    assert json.loads(first_path.read_text(encoding="utf-8")) == first
