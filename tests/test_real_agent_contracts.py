import json

import pytest

from lcah.evaluation.real_agent.contracts import ContractError, TaskSpec


def valid_task_payload():
    return {
        "schema_version": 1,
        "task_id": "compression-native-001",
        "source": {
            "dataset": "lcah-native",
            "source_id": "native-001",
            "license": "MIT",
        },
        "repository": {
            "url": "https://example.invalid/repo.git",
            "base_commit": "0123456789abcdef",
            "image": "sha256:image-digest",
        },
        "instruction": {"text": "Fix parser", "language": "en"},
        "experiment": {
            "module": "compression",
            "condition_family": "compression-v1",
            "intervention": {"trigger": "context_tokens", "threshold": 12000},
        },
        "budget": {
            "max_steps": 80,
            "max_output_tokens": 64000,
            "timeout_seconds": 1800,
            "shell_timeout_seconds": 600,
        },
        "grading": {
            "type": "native",
            "hidden_test_bundle": "grader-only/tests.tar.zst",
            "oracle_patch": "SECRET_ORACLE_PATCH",
        },
        "difficulty": "composite",
        "capabilities": ["state_update", "tool_use"],
    }


def test_task_spec_excludes_grader_only_fields_from_agent_view():
    task = TaskSpec.from_dict(valid_task_payload())

    visible = task.to_agent_dict()

    assert visible["instruction"] == {"text": "Fix parser", "language": "en"}
    assert "grading" not in visible
    assert "SECRET_ORACLE_PATCH" not in json.dumps(visible)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("max_steps", 0, "max_steps"),
        ("max_output_tokens", 0, "max_output_tokens"),
        ("timeout_seconds", 0, "timeout_seconds"),
        ("shell_timeout_seconds", 0, "shell_timeout_seconds"),
    ],
)
def test_task_spec_rejects_invalid_budget(field, value, message):
    payload = valid_task_payload()
    payload["budget"][field] = value

    with pytest.raises(ContractError, match=message):
        TaskSpec.from_dict(payload)


def test_task_spec_rejects_unknown_module_and_difficulty():
    payload = valid_task_payload()
    payload["experiment"]["module"] = "planning"
    with pytest.raises(ContractError, match="module"):
        TaskSpec.from_dict(payload)

    payload = valid_task_payload()
    payload["difficulty"] = "impossible"
    with pytest.raises(ContractError, match="difficulty"):
        TaskSpec.from_dict(payload)


def test_task_spec_round_trips_full_grader_contract():
    task = TaskSpec.from_dict(valid_task_payload())

    restored = TaskSpec.from_dict(task.to_dict())

    assert restored == task
    assert restored.grading["oracle_patch"] == "SECRET_ORACLE_PATCH"
