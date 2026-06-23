import json
import os
import subprocess
import sys

from lcah.testing import ScriptedModelClient
from lcah import LCAH, SessionStore, WorkspaceContext
from lcah.cli import handle_repl_command
from lcah.features import skills as skillslib


def build_agent(tmp_path, outputs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    return LCAH(
        model_client=ScriptedModelClient(outputs),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".lcah" / "sessions"),
        approval_policy="auto",
    )


def test_builtin_skills_are_available_in_context(tmp_path):
    agent = build_agent(tmp_path, [])

    names = [skill.name for skill in skillslib.list_skills(agent.skills)]
    assert {"review", "test", "commit", "simplify"}.issubset(names)

    prompt = agent.prompt("what can you do?")
    assert "Available skills:" in prompt
    assert "/review" in prompt
    assert prompt.index("Memory:") < prompt.index("Available skills:") < prompt.index("Relevant memory:")


def test_prompt_includes_auto_memory_policy_and_index(tmp_path):
    memory_root = tmp_path / ".lcah" / "memory"
    memory_root.mkdir(parents=True)
    (memory_root / "MEMORY.md").write_text(
        "# Durable Memory Index\n\n- [Project](project.md): Project facts\n",
        encoding="utf-8",
    )
    agent = build_agent(tmp_path, [])

    prompt = agent.prompt("What should you remember?")

    assert "# Auto Memory" in prompt
    assert "/remember <text>" in prompt
    assert "/dream" in prompt
    assert "Current Memory Index" in prompt
    assert "Project facts" in prompt


def test_prompt_documents_project_skill_frontmatter_contract(tmp_path):
    agent = build_agent(tmp_path, [])

    prompt = agent.prompt("Create .lcah/skills/audit/SKILL.md")

    assert "When creating LCAH skill files" in prompt
    assert ".lcah/skills/<name>/SKILL.md" in prompt
    assert "user-invocable: true" in prompt
    assert "Audit $ARGUMENTS for risky changes." in prompt


def test_project_skill_slash_invocation_runs_inline_session(tmp_path):
    skill_dir = tmp_path / ".lcah" / "skills" / "deploy"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: deploy
description: Deploy checklist
argument-hint: target
---
Use target $ARGUMENTS from ${LCAH_SKILL_DIR}.
""",
        encoding="utf-8",
    )
    agent = build_agent(tmp_path, ["<final>deploy checked</final>"])

    handled, should_exit, output = handle_repl_command(agent, "/deploy staging")

    assert handled is True
    assert should_exit is False
    assert output == "deploy checked"
    model_prompt = agent.model_client.prompts[-1]
    assert "Skill: deploy" in model_prompt
    assert "Use target staging from" in model_prompt
    assert str(skill_dir) in model_prompt

    events = agent.session_store.event_path(agent.session["id"]).read_text(encoding="utf-8")
    assert '"event": "skill_invoked"' in events


def test_memory_slash_commands_use_kairos_assets(tmp_path):
    agent = build_agent(tmp_path, [])

    handled, should_exit, output = handle_repl_command(agent, "/remember I prefer concise reports")

    assert handled is True
    assert should_exit is False
    assert "Saved to daily log" in output
    log_files = list((tmp_path / ".lcah" / "memory" / "logs").rglob("*.md"))
    events = agent.session_store.event_path(agent.session["id"]).read_text(encoding="utf-8")
    assert len(log_files) == 1
    assert "I prefer concise reports" in log_files[0].read_text(encoding="utf-8")
    assert "memory_note_appended" in events
    assert "slash_command" in events

    handled, should_exit, output = handle_repl_command(agent, "/memory")
    assert handled is True
    assert should_exit is False
    assert "No durable memories yet" in output

    (tmp_path / ".lcah" / "memory" / "MEMORY.md").write_text(
        "# Durable Memory Index\n\n- [User](user.md): User preferences\n",
        encoding="utf-8",
    )

    handled, should_exit, output = handle_repl_command(agent, "/memory")
    assert handled is True
    assert should_exit is False
    assert "User preferences" in output


def test_dream_slash_command_consolidates_daily_log_into_memory_files(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":".lcah/memory/MEMORY.md","start":1,"end":50}}</tool>',
            '<tool>{"name":"write_file","args":{"path":".lcah/memory/MEMORY.md","content":"# Durable Memory Index\\n\\n- [User Preferences](topics/user-preferences.md): User preferences\\n"}}</tool>',
            '<tool>{"name":"write_file","args":{"path":".lcah/memory/topics/user-preferences.md","content":"# User Preferences\\n\\n## Notes\\n- Prefers concise reports.\\n"}}</tool>',
            "<final>Dream consolidation complete.</final>",
        ],
    )
    handle_repl_command(agent, "/remember Prefers concise reports.")

    handled, should_exit, output = handle_repl_command(agent, "/dream")

    assert handled is True
    assert should_exit is False
    assert "Dream consolidation complete" in output
    assert "User preferences" in (tmp_path / ".lcah" / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert "Prefers concise reports" in (tmp_path / ".lcah" / "memory" / "topics" / "user-preferences.md").read_text(encoding="utf-8")
    # dream prompt 是发给 dream 子 agent 的，加了 read step 后总 prompt 数 +1，索引相应调整
    assert "Dream: Memory Consolidation" in agent.model_client.prompts[-4]


def test_dream_cannot_write_outside_memory_directory(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"write_file","args":{"path":"README.md","content":"bad\\n"}}</tool>',
            "<final>Dream stopped.</final>",
        ],
    )

    handled, should_exit, output = handle_repl_command(agent, "/dream")

    assert handled is True
    assert should_exit is False
    assert output == "Dream stopped."
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "demo\n"


def test_skill_frontmatter_metadata_and_argument_substitution(tmp_path):
    skill_dir = tmp_path / ".lcah" / "skills" / "audit"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: audit
description: Audit target files
when-to-use: Before risky edits
context: fork
allowed-tools: read_file, search
disable-model-invocation: true
model: gpt-5.4
paths: src/*.py, tests/*.py
arguments: target
user-invocable: false
---
Audit ${target} with $ARGUMENTS in ${CLAUDE_SKILL_DIR}.
""",
        encoding="utf-8",
    )

    agent = build_agent(tmp_path, [])
    skill = agent.skills["audit"]

    assert skill.context == "fork"
    assert skill.allowed_tools == ("read_file", "search")
    assert skill.disable_model_invocation is True
    assert skill.model == "gpt-5.4"
    assert skill.paths == ("src/*.py", "tests/*.py")
    assert skill.user_invocable is False
    assert "Audit src/app.py with src/app.py" in skill.render("src/app.py")
    assert str(skill_dir) in skill.render("src/app.py")


def test_fork_skill_runs_in_isolated_session_and_records_completion(tmp_path):
    skill_dir = tmp_path / ".lcah" / "skills" / "inspect"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: inspect
description: Isolated inspection
context: fork
---
Inspect $ARGUMENTS.
""",
        encoding="utf-8",
    )
    agent = build_agent(tmp_path, ["<final>fork result</final>"])
    agent.record({"role": "user", "content": "keep me", "created_at": "2026-05-12T10:00:00+00:00"})
    before_history = list(agent.session["history"])

    handled, should_exit, output = handle_repl_command(agent, "/inspect README.md")

    assert handled is True
    assert should_exit is False
    assert output == "fork result"
    assert agent.session["history"] == before_history


def test_auto_skill_create_evaluate_register_and_invoke(tmp_path):
    agent = build_agent(tmp_path, ["<final>csv summary used</final>"])

    result = agent.run_tool(
        "skill_create",
        {
            "name": "csv-summary",
            "description": "Summarize CSV row counts and headers",
            "body": "# CSV Summary\n\nRead $ARGUMENTS and report row count plus headers.",
            "tests": "from pathlib import Path\n\n\ndef test_skill_doc_mentions_headers():\n    skill = Path(__file__).resolve().parents[1] / 'SKILL.md'\n    assert 'headers' in skill.read_text(encoding='utf-8')\n",
            "notes": "Distilled from a successful CSV inspection trajectory.",
            "run_tests": True,
        },
    )

    assert "created .lcah/skills/csv-summary" in result
    assert "evaluation: passed" in result
    assert "csv-summary" in agent.skills
    assert (tmp_path / ".lcah" / "skills" / "csv-summary" / ".memory.md").exists()

    handled, should_exit, output = handle_repl_command(agent, "/csv-summary data.csv")

    assert handled is True
    assert should_exit is False
    assert output == "csv summary used"
    assert "Skill: csv-summary" in agent.model_client.prompts[-1]


def test_auto_skill_find_read_note_and_status(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.run_tool(
        "skill_create",
        {
            "name": "json-audit",
            "description": "Audit JSON structure and required fields",
            "body": "# JSON Audit\n\nCheck required fields and malformed values.",
            "run_tests": False,
        },
    )

    note_result = agent.run_tool(
        "skill_note",
        {
            "name": "json-audit",
            "note": "Works best after reading the schema file first.",
            "outcome": "success",
        },
    )
    found = agent.run_tool("find_skill", {"query": "schema required fields", "limit": 3})
    read = agent.run_tool("read_skill", {"name": "json-audit", "include_memory": True})

    assert "appended .lcah/skills/json-audit/.memory.md" in note_result
    assert "/json-audit" in found
    assert "schema file" in found
    assert "SKILL.md:" in read
    assert ".memory.md:" in read
    assert "Works best" in read

    handled, should_exit, output = handle_repl_command(agent, "/auto-skills")

    assert handled is True
    assert should_exit is False
    assert "/json-audit" in output
    assert "memory_notes=" in output


def test_auto_skill_failed_evaluation_does_not_register(tmp_path):
    agent = build_agent(tmp_path, [])

    result = agent.run_tool(
        "skill_create",
        {
            "name": "broken-skill",
            "description": "A skill with failing validation",
            "body": "# Broken Skill\n\nThis should not enter the catalog.",
            "tests": "def test_fails():\n    assert False\n",
            "run_tests": True,
        },
    )

    assert "evaluation: failed" in result
    assert "broken-skill" not in agent.skills
    status = (tmp_path / ".lcah" / "skills" / "broken-skill" / ".autoskill.json").read_text(encoding="utf-8")
    assert '"status": "failed"' in status


def test_skill_allowed_tools_restricts_inline_execution(tmp_path):
    skill_dir = tmp_path / ".lcah" / "skills" / "readonly"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: readonly
description: Read-only workflow
allowed-tools: read_file
---
Use only read tools.
""",
        encoding="utf-8",
    )
    command = "printf bad > bad.txt"
    agent = build_agent(
        tmp_path,
        [
            f'<tool>{{"name":"run_shell","args":{{"command":{json.dumps(command)},"timeout":20}}}}</tool>',
            "<final>blocked</final>",
        ],
    )

    handled, _, output = handle_repl_command(agent, "/readonly")

    assert handled is True
    assert output == "blocked"
    assert not (tmp_path / "bad.txt").exists()
    events = agent.session_store.event_path(agent.session["id"]).read_text(encoding="utf-8")
    assert '"tool_name": "run_shell"' in events
    assert '"reason": "tool_not_allowed"' in events


def test_disable_model_invocation_skill_returns_expanded_prompt(tmp_path):
    skill_dir = tmp_path / ".lcah" / "skills" / "template"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: template
description: Render without model
disable-model-invocation: true
---
Template says $ARGUMENTS.
""",
        encoding="utf-8",
    )
    agent = build_agent(tmp_path, [])

    handled, _, output = handle_repl_command(agent, "/template hello")

    assert handled is True
    assert output == "Template says hello."
    assert agent.model_client.prompts == []
    events = agent.session_store.event_path(agent.session["id"]).read_text(encoding="utf-8")
    assert '"status": "prompt_only"' in events


def test_builtin_skills_use_dynamic_argument_sections(tmp_path):
    agent = build_agent(tmp_path, [])

    review_prompt = agent.skills["review"].render("focus auth")
    test_prompt = agent.skills["test"].render("only unit tests")

    assert "Additional Focus" in review_prompt
    assert "focus auth" in review_prompt
    assert "Specific Instructions" in test_prompt
    assert "only unit tests" in test_prompt


def test_prompt_metadata_exposes_skill_catalog(tmp_path):
    agent = build_agent(tmp_path, [])

    metadata = agent.prompt_metadata("inspect", "")

    assert metadata["skills"]["available_count"] >= 4
    review = next(item for item in metadata["skills"]["items"] if item["name"] == "review")
    assert review["source"] == "builtin"
    assert review["context"] == "inline"
    assert "description" in review


def test_cli_lists_skills_without_calling_model(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()
    result = subprocess.run(
        [sys.executable, "-m", "lcah", "--cwd", str(tmp_path)],
        input="/skills\n/exit\n",
        text=True,
        capture_output=True,
        env=env,
        timeout=20,
        check=True,
    )

    assert "/review" in result.stdout
    assert "/test" in result.stdout
    assert "/commit" in result.stdout
    assert "/simplify" in result.stdout


def test_auto_skill_examples_script_reports_reuse_and_safety():
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()
    result = subprocess.run(
        [sys.executable, "scripts/run_auto_skill_examples.py"],
        text=True,
        capture_output=True,
        env=env,
        timeout=20,
        check=True,
    )
    report = json.loads(result.stdout)

    assert report["created"]["csv_summary_passed"] is True
    assert report["created"]["json_audit_passed"] is True
    assert report["retrieval"]["csv_query_hits_csv_summary"] is True
    assert report["retrieval"]["json_memory_used_in_routing"] is True
    assert report["reuse"]["skill_prompt_loaded"] is True
    assert report["safety_gate"]["broken_skill_not_registered"] is True
    assert report["efficiency_proxy"]["user_instruction_chars_saved"] > 0
    assert report["efficiency_proxy"]["catalog_smaller_than_full_skills"] is True
    assert report["efficiency_proxy"]["reuse_did_not_create_new_skill"] is True


def test_auto_skill_engineering_benchmark_reports_reduced_exploration():
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()
    result = subprocess.run(
        [sys.executable, "scripts/run_auto_skill_engineering_benchmark.py"],
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
        check=True,
    )
    report = json.loads(result.stdout)
    summary = report["summary"]

    assert summary["scenario_count"] == 3
    assert summary["baseline_pass_rate"] == "3/3"
    assert summary["reuse_pass_rate"] == "3/3"
    assert summary["all_skills_created"] is True
    assert summary["total_tool_steps_reuse"] < summary["total_tool_steps_baseline"]
    assert summary["total_exploration_steps_reuse"] < summary["total_exploration_steps_baseline"]
    assert summary["total_tool_steps_saved"] == 20
    assert summary["total_exploration_steps_saved"] == 14
    table = summary["table_mode_comparison"]
    assert table["no_skill"]["pass"] is True
    assert table["curated_skill"]["pass"] is True
    assert table["auto_skill"]["pass"] is True
    assert table["no_skill"]["repair_rounds"] > table["curated_skill"]["repair_rounds"] > table["auto_skill"]["repair_rounds"]
    assert table["no_skill"]["format_errors"] > table["curated_skill"]["format_errors"] > table["auto_skill"]["format_errors"]
    assert table["no_skill"]["tool_steps"] > table["curated_skill"]["tool_steps"] > table["auto_skill"]["tool_steps"]
    assert all(row["improvement"]["skill_prompt_loaded"] for row in report["scenarios"])
