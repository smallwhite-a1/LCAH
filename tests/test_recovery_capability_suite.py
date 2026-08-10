from lcah.evaluation.recovery_suite import load_recovery_manifest, run_recovery_case


def test_recovery_manifest_covers_eight_recovery_capabilities():
    manifest = load_recovery_manifest()

    assert len(manifest.tasks) == 16
    assert [task.difficulty for task in manifest.tasks].count("basic") == 4
    assert [task.difficulty for task in manifest.tasks].count("composite") == 6
    assert [task.difficulty for task in manifest.tasks].count("adversarial") == 6


def test_checkpoint_resume_matches_uninterrupted_and_lossy_resume_is_detected(tmp_path):
    manifest = load_recovery_manifest()
    uninterrupted = [run_recovery_case(task, 0, 4, "uninterrupted", tmp_path) for task in manifest.tasks]
    resumed = [run_recovery_case(task, 0, 4, "checkpoint_resume", tmp_path) for task in manifest.tasks]
    lossy = [run_recovery_case(task, 0, 4, "lossy_resume", tmp_path) for task in manifest.tasks]

    assert all(row["passed"] for row in uninterrupted)
    assert 0.60 <= sum(row["passed"] for row in resumed) / 16 <= 0.85
    assert sum(row["passed"] for row in resumed) > sum(row["passed"] for row in lossy)
    assert any(row["diagnostics"]["lost_progress"] > 0 for row in lossy)


def test_recovery_detects_freshness_schema_and_duplicate_side_effects(tmp_path):
    manifest = load_recovery_manifest()
    rows = {
        task.metadata["capability"]: run_recovery_case(task, 0, 5, "checkpoint_resume", tmp_path)
        for task in manifest.tasks
    }

    assert rows["file_freshness"]["diagnostics"]["resume_status"] == "partial-stale"
    assert rows["schema_mismatch"]["diagnostics"]["resume_status"] == "schema-mismatch"
    assert rows["exactly_once"]["diagnostics"]["duplicate_operations"] == 0
