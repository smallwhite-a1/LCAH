"""Run deterministic auto-skill examples for CSV and JSON workflows.

The examples intentionally avoid live model calls. They exercise the same
auto-skill tools exposed to LCAH and report concrete benefits:
- evaluated skills are registered and discoverable;
- repeated tasks can route through a named skill instead of ad-hoc discovery;
- skill-level memory improves retrieval;
- failing skills are blocked from the catalog until repaired.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lcah import LCAH, SessionStore, WorkspaceContext
from lcah.cli import handle_repl_command
from lcah.testing import ScriptedModelClient


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lcah-autoskill-example-") as temp_dir:
        root = Path(temp_dir)
        _seed_workspace(root)
        agent = _agent(root)

        csv_result = agent.run_tool(
            "skill_create",
            {
                "name": "csv-summary",
                "description": "Summarize CSV headers, row counts, and missing values",
                "body": "\n".join(
                    [
                        "# CSV Summary",
                        "",
                        "Use this repeatable procedure for $ARGUMENTS:",
                        "1. Read the first lines to identify the dialect and header.",
                        "2. Count rows with Python's csv module.",
                        "3. Report headers, row count, and columns with missing values.",
                    ]
                ),
                "tests": _csv_skill_tests(),
                "notes": "Created from a successful CSV inspection workflow.",
                "run_tests": True,
            },
        )
        json_result = agent.run_tool(
            "skill_create",
            {
                "name": "json-audit",
                "description": "Audit JSON records for required fields and malformed values",
                "body": "\n".join(
                    [
                        "# JSON Audit",
                        "",
                        "Use this repeatable procedure for $ARGUMENTS:",
                        "1. Load the schema or infer required keys from examples.",
                        "2. Validate each record for missing required fields.",
                        "3. Report malformed rows with compact evidence.",
                    ]
                ),
                "tests": _json_skill_tests(),
                "notes": "Created from a successful JSON validation workflow.",
                "run_tests": True,
            },
        )
        agent.run_tool(
            "skill_note",
            {
                "name": "json-audit",
                "note": "Retrieval should prefer this skill for schema and required-field wording.",
                "outcome": "success",
            },
        )
        blocked_result = agent.run_tool(
            "skill_create",
            {
                "name": "broken-parser",
                "description": "Broken parser that should be blocked",
                "body": "# Broken Parser\n\nThis intentionally fails evaluation.",
                "tests": "def test_fails():\n    assert False\n",
                "run_tests": True,
            },
        )

        csv_route = agent.run_tool("find_skill", {"query": "csv headers row count missing values", "limit": 3})
        json_route = agent.run_tool("find_skill", {"query": "json schema required fields", "limit": 3})
        csv_read = agent.run_tool("read_skill", {"name": "csv-summary", "include_memory": True})

        skill_count_before_reuse = len(agent.skills)
        csv_manual_prompt = (
            "For data/users.csv, inspect the CSV dialect and header, count rows with Python's csv module, "
            "then report headers, row count, and columns with missing values."
        )
        csv_slash_command = "/csv-summary data/users.csv"
        auto_skills = [
            skill
            for skill in agent.skills.values()
            if ".lcah/skills" in str(skill.skill_root)
        ]
        catalog_chars = sum(len(skill.name) + len(skill.description) for skill in auto_skills)
        full_auto_skill_chars = 0
        for skill in auto_skills:
            skill_root = Path(skill.skill_root)
            full_auto_skill_chars += len((skill_root / "SKILL.md").read_text(encoding="utf-8"))
            memory_file = skill_root / ".memory.md"
            if memory_file.exists():
                full_auto_skill_chars += len(memory_file.read_text(encoding="utf-8"))


        agent.model_client.outputs.append("<final>CSV summary done with reusable skill.</final>")
        handled, _should_exit, invoked = handle_repl_command(agent, "/csv-summary data/users.csv")
        skill_count_after_reuse = len(agent.skills)

        report = {
            "workspace": str(root),
            "domains": ["csv-summary", "json-audit"],
            "created": {
                "csv_summary_passed": "evaluation: passed" in csv_result,
                "json_audit_passed": "evaluation: passed" in json_result,
            },
            "retrieval": {
                "csv_query_hits_csv_summary": "/csv-summary" in csv_route,
                "json_query_hits_json_audit": "/json-audit" in json_route,
                "json_memory_used_in_routing": "schema and required-field" in json_route,
            },
            "reuse": {
                "slash_invocation_handled": handled,
                "slash_invocation_output": invoked,
                "skill_prompt_loaded": "Skill: csv-summary" in agent.model_client.prompts[-1],
            },
            "safety_gate": {
                "broken_skill_failed": "evaluation: failed" in blocked_result,
                "broken_skill_not_registered": "broken-parser" not in agent.skills,
            },
            "compact_catalog": {
                "registered_auto_skill_count": len(
                    [
                        name
                        for name, skill in agent.skills.items()
                        if ".lcah/skills" in str(skill.skill_root)
                    ]
                ),
                "read_skill_contains_memory": ".memory.md:" in csv_read,
            },
            "efficiency_proxy": {
                "manual_csv_prompt_chars": len(csv_manual_prompt),
                "slash_command_chars": len(csv_slash_command),
                "user_instruction_chars_saved": len(csv_manual_prompt) - len(csv_slash_command),
                "user_instruction_reduction_ratio": round(
                    1 - (len(csv_slash_command) / len(csv_manual_prompt)),
                    3,
                ),
                "catalog_chars": catalog_chars,
                "full_auto_skill_chars": full_auto_skill_chars,
                "catalog_smaller_than_full_skills": catalog_chars < full_auto_skill_chars,
                "reuse_did_not_create_new_skill": skill_count_before_reuse == skill_count_after_reuse,
            },
        }
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _agent(root: Path) -> LCAH:
    workspace = WorkspaceContext.build(root)
    return LCAH(
        model_client=ScriptedModelClient([]),
        workspace=workspace,
        session_store=SessionStore(root / ".lcah" / "sessions"),
        approval_policy="auto",
    )


def _seed_workspace(root: Path) -> None:
    (root / "README.md").write_text("auto-skill example workspace\n", encoding="utf-8")
    data = root / "data"
    data.mkdir()
    (data / "users.csv").write_text("id,name,email\n1,Ada,ada@example.test\n2,Lin,\n", encoding="utf-8")
    (data / "events.json").write_text('[{"id": 1, "kind": "click"}, {"kind": "view"}]\n', encoding="utf-8")


def _csv_skill_tests() -> str:
    return """from pathlib import Path


def test_csv_skill_mentions_headers_rows_and_missing_values():
    text = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")
    assert "headers" in text
    assert "row count" in text
    assert "missing values" in text
"""


def _json_skill_tests() -> str:
    return """from pathlib import Path


def test_json_skill_mentions_required_fields():
    text = (Path(__file__).resolve().parents[1] / "SKILL.md").read_text(encoding="utf-8")
    assert "required fields" in text
    assert "malformed" in text
"""


if __name__ == "__main__":
    raise SystemExit(main())
