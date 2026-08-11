from pathlib import Path

import pytest
from test_real_agent_contracts import valid_task_payload

from lcah.evaluation.real_agent.contracts import TaskSpec
from lcah.evaluation.real_agent.environment import (
    EnvironmentError,
    NativeEnvironmentProvisioner,
)


def native_task(fixture: Path):
    payload = valid_task_payload()
    payload["grading"]["fixture_root"] = str(fixture)
    payload["grading"]["protected_paths"] = ["hidden_test.py"]
    return TaskSpec.from_dict(payload)


def test_native_environment_is_reproducible_and_excludes_grader_files(tmp_path):
    fixture = tmp_path / "fixture"; fixture.mkdir()
    (fixture / "app.py").write_text("VALUE = 1\n")
    grader = tmp_path / "hidden_test.py"; grader.write_text("assert False\n")
    provisioner = NativeEnvironmentProvisioner()
    first = provisioner.prepare(native_task(fixture), tmp_path / "attempt-a")
    second = provisioner.prepare(native_task(fixture), tmp_path / "attempt-b")
    assert (first.workspace / "app.py").exists()
    assert not (first.workspace / "hidden_test.py").exists()
    assert first.initial_digest == second.initial_digest
    assert (first.workspace / ".git").is_dir()


def test_native_environment_rejects_fixture_symlink(tmp_path):
    outside = tmp_path / "outside.txt"; outside.write_text("secret")
    fixture = tmp_path / "fixture"; fixture.mkdir()
    (fixture / "escape").symlink_to(outside)
    with pytest.raises(EnvironmentError, match="symlink"):
        NativeEnvironmentProvisioner().prepare(native_task(fixture), tmp_path / "attempt")
