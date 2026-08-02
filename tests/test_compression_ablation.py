import json

from lcah import LCAH, SessionStore, WorkspaceContext
from lcah.evaluation.evaluator import run_compression_ablation_v2
from lcah.testing import ScriptedModelClient


def _agent(tmp_path, feature_flags):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    agent = LCAH(
        model_client=ScriptedModelClient([]),
        workspace=WorkspaceContext.build(tmp_path),
        session_store=SessionStore(tmp_path / ".lcah" / "sessions"),
        approval_policy="auto",
        feature_flags=feature_flags,
    )
    for index in range(8):
        agent.record(
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"history-{index}-" + ("x" * 180),
                "created_at": f"2026-08-01T10:0{index}:00+00:00",
            }
        )
    agent.context_manager.total_budget = 120
    return agent


def test_context_compaction_can_be_disabled_for_ablation_control(tmp_path):
    agent = _agent(
        tmp_path,
        {"context_reduction": False, "context_compaction": False},
    )

    metadata = agent.prompt_metadata("Continue", "")

    assert metadata["prompt_over_budget"] is True
    assert metadata.get("auto_compacted") is not True
    assert agent.session.get("compactions", []) == []


def test_compression_ablation_writes_paired_quality_and_efficiency_metrics(tmp_path):
    artifact_path = tmp_path / "compression-ablation-v2.json"

    artifact = run_compression_ablation_v2(
        benchmark_path="benchmarks/coding_tasks.json",
        artifact_path=artifact_path,
        workspace_root=tmp_path / "workspaces",
    )

    assert artifact_path.exists()
    persisted = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert persisted == artifact
    assert artifact["artifact_type"] == "compression-ablation-v2"
    assert set(artifact["variants"]) == {"compression_on", "compression_off"}
    assert artifact["variants"]["compression_on"]["task_count"] == 32
    assert artifact["variants"]["compression_off"]["task_count"] == 32
    assert artifact["variants"]["compression_on"]["pass_rate"] == 1.0
    assert artifact["variants"]["compression_off"]["pass_rate"] == 1.0
    assert artifact["variants"]["compression_on"]["avg_prompt_chars"] <= artifact["variants"]["compression_off"]["avg_prompt_chars"]
    assert artifact["variants"]["compression_on"]["quality_verifier_pass_rate"] == 1.0
    assert artifact["variants"]["compression_off"]["compaction_count"] == 0
    assert artifact["variants"]["compression_on"]["triggered_task_count"] >= 20
    assert artifact["variants"]["compression_off"]["triggered_task_count"] == 0
    assert artifact["variants"]["compression_on"]["triggered_quality_verifier_pass_rate"] == 1.0
    assert artifact["variants"]["compression_off"]["quality_verifier_pass_rate"] == 1.0
    assert artifact["variants"]["compression_on"]["p95_prompt_chars"] >= 0
    assert artifact["variants"]["compression_on"]["p95_prompt_compression_ratio"] >= 0
    assert artifact["variants"]["compression_on"]["actual_input_token_coverage"] == 0.0

    triggered_rows = [
        row
        for row in artifact["rows"]
        if row["variant"] == "compression_on" and row["prompt_metrics"]["compression_triggered"]
    ]
    assert len(triggered_rows) >= 20
    assert all(row["prompt_metrics"]["compaction_count"] > 0 for row in triggered_rows)
    assert sum(row["category"] == "context-pressure" for row in triggered_rows) >= 20

    paired_ids = {
        variant: {row["id"] for row in artifact["rows"] if row["variant"] == variant}
        for variant in artifact["variants"]
    }
    assert paired_ids["compression_on"] == paired_ids["compression_off"]
