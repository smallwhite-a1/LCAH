from dataclasses import replace

import pytest
from test_real_agent_contracts import valid_task_payload

from lcah.evaluation.real_agent.contracts import TaskSpec
from lcah.evaluation.real_agent.evidence import EvidenceStore
from lcah.evaluation.real_agent.lock import EvaluationLock, LockMismatch
from lcah.evaluation.real_agent.orchestrator import build_schedule, run_schedule


def test_lock_rejects_dataset_drift(tmp_path):
    lock = EvaluationLock("sha256:a", "sha256:b", "sha256:c", {"commit": "abc"},
                          {"model": "deepseek-v4-flash"}, {"max_steps": 80}, 3, 7, "v1")
    path = tmp_path / "evaluation-lock.json"
    lock.write(path)
    with pytest.raises(LockMismatch, match="dataset_digest"):
        EvaluationLock.verify(path, replace(lock, dataset_digest="sha256:changed"))


def test_schedule_pairs_capability_and_single_conditions_security():
    capability = TaskSpec.from_dict(valid_task_payload())
    payload = valid_task_payload(); payload["task_id"] = "security-1"
    payload["experiment"]["module"] = "security"
    security = TaskSpec.from_dict(payload)
    schedule = build_schedule([capability, security], repetitions=3, seed=7)
    assert len(schedule) == 9
    assert {x.identity.condition for x in schedule if x.task.task_id == capability.task_id} == {"production", "control"}
    assert {x.identity.condition for x in schedule if x.task.task_id == security.task_id} == {"production"}


def test_resume_skips_terminal_attempts(tmp_path):
    task = TaskSpec.from_dict(valid_task_payload())
    schedule = build_schedule([task], repetitions=1, seed=7)
    calls = []
    def runner(item, attempt):
        calls.append(item.identity.condition)
        return {"status": "pass", "grader_complete": True}
    store = EvidenceStore(tmp_path)
    run_schedule(schedule, runner, store)
    run_schedule(schedule, runner, store)
    assert sorted(calls) == ["control", "production"]
