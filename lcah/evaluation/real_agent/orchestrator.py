"""Deterministic paired schedule and resumable attempt execution."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from .contracts import AttemptIdentity, TaskSpec
from .evidence import EvidenceStore


@dataclass(frozen=True)
class ScheduledAttempt:
    task: TaskSpec
    identity: AttemptIdentity


def _seed(base: int, task_id: str, repetition: int) -> int:
    return int.from_bytes(hashlib.sha256(f"{base}\0{task_id}\0{repetition}".encode()).digest()[:4], "big")


def build_schedule(tasks, repetitions: int, seed: int) -> tuple[ScheduledAttempt, ...]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    pairs = []
    for task in tasks:
        for repetition in range(repetitions):
            pair_id = f"{task.task_id}:{repetition}"
            conditions = ["production"] if task.experiment["module"] == "security" else ["production", "control"]
            if repetition % 2:
                conditions.reverse()
            pair_seed = _seed(seed, task.task_id, repetition)
            pairs.append([ScheduledAttempt(task, AttemptIdentity(task.task_id, condition, repetition, pair_id, pair_seed)) for condition in conditions])
    random.Random(seed).shuffle(pairs)
    return tuple(item for pair in pairs for item in pair)


def run_schedule(schedule, runner, evidence_store: EvidenceStore):
    outcomes = []
    for item in schedule:
        if evidence_store.terminal(item.identity):
            continue
        attempt = evidence_store.start_attempt(item.identity, {"task": item.task.to_agent_dict()})
        outcome = dict(runner(item, attempt))
        if outcome.get("status") in {"pass", "fail"} and outcome.get("grader_complete") is True:
            evidence_store.finish_attempt(attempt, outcome)
        outcomes.append(outcome)
    return outcomes
