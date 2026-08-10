from lcah.evaluation.memory_suite import load_memory_manifest, run_memory_case


def test_memory_manifest_covers_eight_lifecycle_capabilities():
    manifest = load_memory_manifest()

    assert len(manifest.tasks) == 16
    assert [task.difficulty for task in manifest.tasks].count("basic") == 4
    assert [task.difficulty for task in manifest.tasks].count("composite") == 6
    assert [task.difficulty for task in manifest.tasks].count("adversarial") == 6


def test_actual_memory_beats_disabled_and_survives_irrelevant_distractors(tmp_path):
    manifest = load_memory_manifest()
    actual = [run_memory_case(task, 0, 2, "memory_on", tmp_path) for task in manifest.tasks]
    disabled = [run_memory_case(task, 0, 2, "memory_disabled", tmp_path) for task in manifest.tasks]
    irrelevant = [run_memory_case(task, 0, 2, "memory_irrelevant", tmp_path) for task in manifest.tasks]

    assert 0.60 <= sum(row["passed"] for row in actual) / 16 <= 0.85
    assert sum(row["passed"] for row in actual) > sum(row["passed"] for row in disabled)
    assert sum(row["passed"] for row in irrelevant) >= sum(row["passed"] for row in disabled)


def test_memory_rejects_forbidden_persistence_and_replaces_conflicts(tmp_path):
    manifest = load_memory_manifest()
    secret = next(task for task in manifest.tasks if task.task_id == "m03-secret")
    update = next(task for task in manifest.tasks if task.task_id == "m05-update")

    secret_row = run_memory_case(secret, 0, 3, "memory_on", tmp_path)
    update_row = run_memory_case(update, 0, 3, "memory_on", tmp_path)

    assert secret_row["passed"] is True
    assert secret_row["diagnostics"]["forbidden_persistence"] == 0
    assert "secret_shaped" in secret_row["diagnostics"]["rejections"]
    assert update_row["passed"] is True
    assert update_row["diagnostics"]["superseded_count"] == 1
