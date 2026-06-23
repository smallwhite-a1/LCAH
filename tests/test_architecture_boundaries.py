from pathlib import Path


def test_core_modules_stay_below_entropy_budget():
    root = Path(__file__).resolve().parents[1]
    budgets = {
        "lcah/core/runtime.py": 950,
        "lcah/core/runtime_events.py": 90,
        "lcah/core/runtime_consumers.py": 90,
        "lcah/core/artifacts.py": 130,
        "lcah/core/task_state.py": 140,
        "lcah/core/todo_ledger.py": 120,
        "lcah/core/worker_manager.py": 220,
        "lcah/core/context_manager.py": 420,
        "lcah/core/context_usage.py": 120,
        "lcah/core/compact.py": 180,
        "lcah/core/engine.py": 470,
        "lcah/core/model_errors.py": 100,
        "lcah/core/permissions.py": 140,
        "lcah/core/tool_policy.py": 90,
        "lcah/core/plan_mode.py": 140,
        "lcah/core/tool_executor.py": 181,
        "lcah/core/tool_profiles.py": 80,
        "lcah/core/turn_history.py": 250,
        "lcah/features/skills.py": 220,
        "lcah/features/skills_bundled.py": 120,
        "lcah/features/skills_runtime.py": 140,
        "lcah/tools/registry.py": 360,
        "lcah/tools/todos.py": 80,
        "lcah/tools/agents.py": 90,
    }

    for relative_path, max_lines in budgets.items():
        line_count = len((root / relative_path).read_text(encoding="utf-8").splitlines())
        assert line_count <= max_lines, f"{relative_path} has {line_count} lines, budget is {max_lines}"
