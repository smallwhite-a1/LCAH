import json
from dataclasses import replace

from lcah.evaluation.compression_suite import (
    load_compression_manifest,
    run_compression_case,
)
from lcah.evaluation.module_suite import run_module_capability_evals


def test_module_capability_evals_emit_paired_discriminative_report(tmp_path):
    artifact = run_module_capability_evals(tmp_path / "module-evals", repetitions=1)

    assert set(artifact["modules"]) == {"compression", "memory", "recovery"}
    for name, module in artifact["modules"].items():
        assert module["task_count"] == 16
        assert module["analysis"]["sensitivity_check"]["detected"] is True, name
        calibration = module["analysis"]["calibration"]
        assert 0.60 <= calibration["production_pass_rate"] <= 0.85
        assert calibration["difficulty"]["basic"]["pass_rate"] >= 0.75
        assert len(calibration["mutations"]) == 4
        for mutation in calibration["mutations"].values():
            assert 1 <= len(mutation["flipped_task_ids"]) <= 6
            assert mutation["score_delta"] <= -0.0625
        assert "pass_rate_ci_95" in next(iter(module["analysis"]["variants"].values()))
        assert (tmp_path / "module-evals" / module["artifact"]).exists()

    persisted = json.loads((tmp_path / "module-evals" / "module-capability-summary.json").read_text())
    assert persisted == artifact


def test_module_capability_evals_are_reproducible(tmp_path):
    first = run_module_capability_evals(tmp_path / "first", repetitions=1)
    second = run_module_capability_evals(tmp_path / "second", repetitions=1)

    assert {
        name: module["analysis"] for name, module in first["modules"].items()
    } == {
        name: module["analysis"] for name, module in second["modules"].items()
    }


def test_expected_current_result_does_not_affect_grading():
    task = load_compression_manifest().tasks[0]
    inverted = replace(task, expected_current_result="fail")

    assert run_compression_case(task, 0, 7, "lcah_compression")["passed"] == run_compression_case(
        inverted, 0, 7, "lcah_compression"
    )["passed"]
