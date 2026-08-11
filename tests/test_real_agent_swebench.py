import json

import pytest

from lcah.evaluation.real_agent.swebench import (
    SWEbenchDependencyError,
    build_prediction,
    check_swebench_installation,
    parse_official_report,
)


def test_prediction_uses_official_fields_only():
    prediction = build_prediction("django__django-1", "diff --git a/a b/a", "lcah-deepseek-v4-flash")
    assert prediction == {
        "instance_id": "django__django-1",
        "model_name_or_path": "lcah-deepseek-v4-flash",
        "model_patch": "diff --git a/a b/a",
    }


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"resolved_ids": ["x"], "unresolved_ids": [], "error_ids": []}, "pass"),
        ({"resolved_ids": [], "unresolved_ids": ["x"], "error_ids": []}, "fail"),
        ({"resolved_ids": [], "unresolved_ids": [], "error_ids": ["x"]}, "grader_error"),
    ],
)
def test_parse_official_report_maps_terminal_status(tmp_path, payload, status):
    path = tmp_path / "report.json"; path.write_text(json.dumps(payload))
    result = parse_official_report(path, "x")
    assert result.status == status
    assert result.valid_run is (status != "grader_error")


def test_missing_harness_has_actionable_error(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    with pytest.raises(SWEbenchDependencyError, match="swebench"):
        check_swebench_installation()
