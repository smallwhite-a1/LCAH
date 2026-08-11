import json

import pytest
from test_real_agent_contracts import valid_task_payload

from lcah.evaluation.real_agent.adapters import (
    AdapterError,
    LCAHNativeAdapter,
    SWEbenchAdapter,
    scan_agent_view_for_leaks,
)
from lcah.evaluation.real_agent.contracts import TaskSpec


def test_swebench_adapter_keeps_gold_fields_grader_only(tmp_path):
    source = tmp_path / "swe.json"
    source.write_text(json.dumps([{
        "instance_id": "org__repo-1", "repo": "org/repo", "base_commit": "abc123",
        "problem_statement": "Fix parser", "version": "1", "patch": "SECRET_GOLD_PATCH",
        "FAIL_TO_PASS": ["test_parser"], "PASS_TO_PASS": ["test_other"],
    }]))
    task = SWEbenchAdapter(module="compression", image="sha256:image").load(source)[0]
    assert "SECRET_GOLD_PATCH" not in json.dumps(task.to_agent_dict())
    assert task.grading["oracle_patch"] == "SECRET_GOLD_PATCH"


def test_native_adapter_rejects_duplicate_ids(tmp_path):
    source = tmp_path / "native.json"
    source.write_text(json.dumps({"tasks": [valid_task_payload(), valid_task_payload()]}))
    with pytest.raises(AdapterError, match="duplicate"):
        LCAHNativeAdapter().load(source)


def test_leak_scanner_detects_oracle_overlap():
    payload = valid_task_payload()
    payload["instruction"]["text"] += " SECRET_ORACLE_PATCH"
    task = TaskSpec.from_dict(payload)
    assert scan_agent_view_for_leaks(task) == ["oracle_patch_overlap"]
