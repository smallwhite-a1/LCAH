from pathlib import Path

from test_real_agent_contracts import valid_task_payload

from lcah.evaluation.real_agent.contracts import TaskSpec
from lcah.evaluation.real_agent.preflight import validate_native_task

ROOT = Path(__file__).resolve().parents[1]


def smoke_task():
    payload = valid_task_payload()
    payload["task_id"] = "real-agent-smoke"
    payload["grading"].update({
        "fixture_root": str(ROOT / "benchmarks/fixtures/real_agent_smoke"),
        "grader_only_paths": ["real_agent_smoke.py"],
        "protected_paths": ["test_calculator.py"],
        "public_command": ["python", "-m", "pytest", "-q", "test_calculator.py"],
        "hidden_command": ["python", str(ROOT / "benchmarks/graders/real_agent_smoke.py"), "{workspace}"],
        "timeout_seconds": 20,
        "oracle_patch": """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,3 +1,3 @@
 def safe_divide(numerator, denominator):
     \"\"\"Return numerator divided by denominator, or None for a zero denominator.\"\"\"
-    return numerator // denominator
+    return None if denominator == 0 else numerator / denominator
""",
    })
    return TaskSpec.from_dict(payload)


def test_phase_b_gate_proves_initial_failure_oracle_success_and_isolation(tmp_path):
    result = validate_native_task(smoke_task(), tmp_path)
    assert result["passed"] is True
    assert result["gates"] == {
        "deterministic_environment": True,
        "grader_isolated": True,
        "initial_public_failure": True,
        "oracle_patch_applied": True,
        "oracle_strict_pass": True,
        "protected_paths_unchanged": True,
    }
