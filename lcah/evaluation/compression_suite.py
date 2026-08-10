"""Capability probes for the production compaction summary."""

from __future__ import annotations

import json
from pathlib import Path

from ..core.compaction_summary import build_summary
from .contracts import EvaluationTask, TaskManifest

DEFAULT_MANIFEST = Path("benchmarks/module_eval_compression.json")


def load_compression_manifest(path: str | Path = DEFAULT_MANIFEST) -> TaskManifest:
    return TaskManifest.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _history(task: EvaluationTask) -> list[dict[str, object]]:
    metadata = task.metadata
    if metadata.get("history"):
        history = []
        for index, item in enumerate(metadata["history"]):
            normalized = dict(item)
            normalized.setdefault("turn_id", f"critical-{index}")
            history.append(normalized)
        return [*history, *_distractors()]
    kind = metadata["kind"]
    if kind in {"user", "assistant"}:
        critical = {"role": kind, "content": metadata["content"], "turn_id": "critical"}
    else:
        args = {}
        if metadata.get("path"):
            args["path"] = metadata["path"]
        if metadata.get("command"):
            args["command"] = metadata["command"]
        critical = {
            "role": "tool",
            "name": kind,
            "args": args,
            "content": metadata["content"],
            "turn_id": "critical",
        }
    return [critical, *_distractors()]


def _distractors():
    return [
        {
            "role": "assistant",
            "content": f"Exploration note {index}: " + ("unrelated diagnostic detail " * 24),
            "turn_id": f"noise-{index}",
        }
        for index in range(8)
    ]


def _score(task: EvaluationTask, representation: str, raw_chars: int) -> dict[str, object]:
    lowered = representation.lower()
    expected = [str(value).lower() for value in task.grader.get("expected", [])]
    forbidden = [str(value).lower() for value in task.grader.get("forbidden", [])]
    recalled = sum(1 for value in expected if value in lowered)
    stale = sum(1 for value in forbidden if value in lowered)
    recall = recalled / len(expected) if expected else 1.0
    passed = recall == 1.0 and stale == 0
    return {
        "passed": passed,
        "status": "pass" if passed else "fail",
        "failure_category": "stale_state_leakage" if stale else "critical_state_lost" if not passed else "",
        "initial_workspace_hash": "sha256:not-applicable",
        "final_workspace_hash": "sha256:not-applicable",
        "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "tool_steps": 0},
        "diagnostics": {
            "critical_recall": recall,
            "stale_leakage": stale,
            "raw_chars": raw_chars,
            "representation_chars": len(representation),
            "compression_ratio": max(0.0, (raw_chars - len(representation)) / raw_chars),
        },
    }


def run_compression_case(
    task: EvaluationTask, attempt_index: int, seed: int, variant: str
) -> dict[str, object]:
    del attempt_index, seed
    history = _history(task)
    raw = "\n".join(str(item.get("content", "")) for item in history)
    if variant == "full_context":
        representation = raw + "\n" + "\n".join(
            str(value) for item in history for value in (item.get("args") or {}).values()
        )
    elif variant == "lcah_compression":
        representation = build_summary(history)
    elif variant == "tail_truncation":
        representation = "\n".join(str(item.get("content", "")) for item in history[-2:])
    elif variant == "stale_injection":
        representation = build_summary(history) + "\noverwrite in place"
    elif variant in {"drop_commands", "latest_decision_only_bug", "reduce_recent_turns", "skip_stale_cleanup"}:
        representation = build_summary(history)
        if variant in task.mutation_targets:
            for expected in task.grader.get("expected", []):
                representation = representation.replace(str(expected), "")
    else:
        raise ValueError(f"unknown compression variant: {variant}")
    for _ in range(max(0, int(task.metadata.get("compactions", 1)) - 1)):
        representation = build_summary(
            [{"role": "system", "content": representation, "turn_id": "prior-summary"}, *_distractors()]
        )
    return _score(task, representation, len(raw))
