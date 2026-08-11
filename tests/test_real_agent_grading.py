
from test_real_agent_contracts import valid_task_payload

from lcah.evaluation.real_agent.contracts import TaskSpec
from lcah.evaluation.real_agent.environment import NativeEnvironmentProvisioner
from lcah.evaluation.real_agent.grading import NativeGrader


def task_and_environment(tmp_path, hidden_body="import sys; assert True"):
    fixture = tmp_path / "fixture"; fixture.mkdir()
    (fixture / "app.py").write_text("VALUE = 1\n")
    (fixture / "test_public.py").write_text("from app import VALUE\ndef test_value(): assert VALUE == 1\n")
    hidden = tmp_path / "hidden.py"; hidden.write_text(hidden_body)
    payload = valid_task_payload()
    payload["grading"].update({
        "fixture_root": str(fixture), "protected_paths": ["test_public.py"],
        "public_command": ["python", "-m", "pytest", "-q", "test_public.py"],
        "hidden_command": ["python", str(hidden), "{workspace}"],
        "timeout_seconds": 20,
    })
    task = TaskSpec.from_dict(payload)
    environment = NativeEnvironmentProvisioner().prepare(task, tmp_path / "attempt")
    return task, environment


def test_native_grader_requires_public_hidden_and_protected_integrity(tmp_path):
    task, environment = task_and_environment(tmp_path)
    result = NativeGrader().grade(task, environment)
    assert result.passed is True
    assert all(result.checks.values())

    (environment.workspace / "test_public.py").write_text("def test_fake(): assert True\n")
    result = NativeGrader().grade(task, environment)
    assert result.passed is False
    assert result.checks["protected_paths_unchanged"] is False
    assert result.failure_category == "protected_test_modified"


def test_native_grader_classifies_hidden_failure_and_execution_error(tmp_path):
    task, environment = task_and_environment(tmp_path, "raise AssertionError('hidden fail')")
    result = NativeGrader().grade(task, environment)
    assert result.failure_category == "hidden_test_failure"

    payload = task.to_dict(); payload["grading"]["hidden_command"] = ["missing-grader-command"]
    broken = NativeGrader().grade(TaskSpec.from_dict(payload), environment)
    assert broken.status == "grader_error"
    assert broken.valid_run is False
