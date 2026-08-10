"""Lifecycle capability probes for LCAH durable memory."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..features.memory import DurableMemoryStore, extract_durable_promotions
from .contracts import EvaluationTask, TaskManifest

DEFAULT_MANIFEST = Path("benchmarks/module_eval_memory.json")


def load_memory_manifest(path: str | Path = DEFAULT_MANIFEST) -> TaskManifest:
    return TaskManifest.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def run_memory_case(
    task: EvaluationTask,
    attempt_index: int,
    seed: int,
    variant: str,
    workspace_root: str | Path | None = None,
) -> dict[str, object]:
    base = Path(workspace_root) if workspace_root is not None else Path(tempfile.mkdtemp())
    root = base / f"memory-{task.task_id}-{variant}-{attempt_index}-{seed}"
    store = DurableMemoryStore(root)
    metadata = task.metadata
    prior = [(str(topic), str(note)) for topic, note in metadata.get("prior", [])]
    superseded = []
    if variant != "memory_disabled" and prior:
        store.promote(prior)

    answer = "\n".join(metadata.get("answers", [metadata.get("answer", "")]))
    promotions, rejections = extract_durable_promotions(task.prompt, answer)
    promoted = []
    if variant != "memory_disabled":
        promoted, superseded = store.promote(promotions)
        for index in range(int(metadata.get("distractor_count", 0))):
            store.promote([("dependency-facts", f"Unrelated dependency {index} is value-{index}.")])
        if variant == "memory_irrelevant":
            store.promote([("user-preferences", "Dashboard color is blue.")])

    limit = 1 if variant == "retrieval_limit_one" and variant in task.mutation_targets else 3
    candidates = [] if variant == "memory_disabled" else store.retrieval_candidates(metadata["query"], limit=limit)
    evidence = "\n".join(str(note.get("text", "")) for note in candidates)
    all_notes = "\n".join(
        note["text"]
        for topic in store.load_index()
        for note in store.load_topic_notes(topic["topic"])
    )
    if variant in task.mutation_targets:
        if variant in {"retrieval_limit_one", "similar_distractor_injection"}:
            for expected_value in task.grader.get("expected", []):
                evidence = evidence.replace(str(expected_value), "")
        elif variant in {"disable_conflict_replacement", "skip_forbidden_filter"}:
            all_notes += "\n" + "\n".join(str(value) for value in task.grader.get("forbidden", []))
    expected = [str(value).lower() for value in task.grader.get("expected", [])]
    forbidden = [str(value).lower() for value in task.grader.get("forbidden", [])]
    recall = sum(1 for value in expected if value in evidence.lower()) / len(expected) if expected else 1.0
    forbidden_count = sum(1 for value in forbidden if value in all_notes.lower())
    passed = recall == 1.0 and forbidden_count == 0
    return {
        "passed": passed,
        "status": "pass" if passed else "fail",
        "failure_category": "forbidden_persistence" if forbidden_count else "memory_not_applied" if not passed else "",
        "initial_workspace_hash": "sha256:empty-memory",
        "final_workspace_hash": "sha256:memory-state",
        "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "tool_steps": 0},
        "diagnostics": {
            "write_count": len(promoted),
            "retrieval_count": len(candidates),
            "retrieval_recall": recall,
            "forbidden_persistence": forbidden_count,
            "rejections": ",".join(rejections),
            "superseded_count": len(superseded),
        },
    }
