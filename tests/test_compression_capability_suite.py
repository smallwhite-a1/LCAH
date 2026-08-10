from lcah.evaluation.compression_suite import (
    load_compression_manifest,
    run_compression_case,
)


def test_compression_manifest_covers_eight_state_capabilities():
    manifest = load_compression_manifest()

    assert len(manifest.tasks) == 16
    assert [task.difficulty for task in manifest.tasks].count("basic") == 4
    assert [task.difficulty for task in manifest.tasks].count("composite") == 6
    assert [task.difficulty for task in manifest.tasks].count("adversarial") == 6


def test_production_compression_preserves_state_better_than_tail_truncation():
    manifest = load_compression_manifest()
    production = [run_compression_case(task, 0, 1, "lcah_compression") for task in manifest.tasks]
    truncation = [run_compression_case(task, 0, 1, "tail_truncation") for task in manifest.tasks]

    assert 0.60 <= sum(row["passed"] for row in production) / 16 <= 0.85
    assert sum(row["passed"] for row in production) > sum(row["passed"] for row in truncation)
    assert all(row["diagnostics"]["compression_ratio"] > 0 for row in production)


def test_compression_grader_detects_stale_state_leakage():
    task = next(
        task for task in load_compression_manifest().tasks if task.task_id == "c07-decision"
    )

    row = run_compression_case(task, 0, 1, "stale_injection")

    assert row["passed"] is False
    assert row["failure_category"] == "stale_state_leakage"
    assert row["diagnostics"]["stale_leakage"] > 0
