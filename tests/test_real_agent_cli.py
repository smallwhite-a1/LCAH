import json

from test_real_agent_contracts import valid_task_payload

from lcah.evaluation.real_agent.cli import main


def test_dry_run_builds_324_attempt_schedule_without_provider_calls(tmp_path):
    tasks = []
    for index in range(48):
        payload = valid_task_payload(); payload["task_id"] = f"task-{index:02d}"
        payload["source"]["source_id"] = payload["task_id"]
        payload["experiment"]["module"] = ("compression", "memory", "recovery")[index % 3]
        tasks.append(payload)
    for index in range(12):
        payload = valid_task_payload(); payload["task_id"] = f"security-{index:02d}"
        payload["source"]["source_id"] = payload["task_id"]
        payload["experiment"]["module"] = "security"
        tasks.append(payload)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"tasks": tasks}))
    output = tmp_path / "output"
    assert main(["dry-run", "--manifest", str(manifest), "--output", str(output)]) == 0
    run_manifest = json.loads((output / "run-manifest.json").read_text())
    assert run_manifest["attempt_count"] == 324
    assert not (output / "attempts").exists()
