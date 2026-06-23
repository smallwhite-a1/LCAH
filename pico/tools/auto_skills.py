"""Auto-skill tools inspired by lifecycle-managed skill systems."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..features import skills as skillslib

SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
AUTOSKILL_TOOL_NAMES = {
    "find_skill",
    "read_skill",
    "skill_create",
    "update_skill",
    "skill_note",
    "skill_eval",
}

AUTOSKILL_TOOL_SPECS = {
    "find_skill": {
        "schema": {"query": "str", "limit": "int=5"},
        "risky": False,
        "description": "Find relevant skills by catalog metadata and skill memory.",
    },
    "read_skill": {
        "schema": {"name": "str", "include_memory": "bool=true"},
        "risky": False,
        "description": "Read a skill package interface and optional per-skill memory.",
    },
    "skill_create": {
        "schema": {
            "name": "str",
            "description": "str",
            "body": "str",
            "tests": "str=''",
            "notes": "str=''",
            "overwrite": "bool=false",
            "run_tests": "bool=true",
        },
        "risky": True,
        "description": "Create a project auto-skill package with optional pytest evaluation.",
    },
    "update_skill": {
        "schema": {
            "name": "str",
            "body": "str=''",
            "description": "str=''",
            "tests": "str=''",
            "notes": "str=''",
            "run_tests": "bool=true",
        },
        "risky": True,
        "description": "Patch an existing auto-skill and re-run its tests.",
    },
    "skill_note": {
        "schema": {"name": "str", "note": "str", "outcome": "str='observation'"},
        "risky": True,
        "description": "Append skill-level memory such as lessons, caveats, or outcomes.",
    },
    "skill_eval": {
        "schema": {"name": "str"},
        "risky": True,
        "description": "Run a skill package's pytest tests and record the result.",
    },
}

AUTOSKILL_TOOL_EXAMPLES = {
    "find_skill": '<tool>{"name":"find_skill","args":{"query":"summarize CSV files","limit":3}}</tool>',
    "read_skill": '<tool>{"name":"read_skill","args":{"name":"csv-summary","include_memory":true}}</tool>',
    "skill_create": '<tool>{"name":"skill_create","args":{"name":"csv-summary","description":"Summarize CSV columns and row counts","body":"# CSV Summary\\n\\nUse Python csv module to inspect $ARGUMENTS.","tests":"def test_skill_doc_exists():\\n    assert True\\n","notes":"Created after a successful CSV analysis.","run_tests":true}}</tool>',
    "update_skill": '<tool>{"name":"update_skill","args":{"name":"csv-summary","body":"# CSV Summary\\n\\nUpdated procedure.","notes":"Refined after test feedback."}}</tool>',
    "skill_note": '<tool>{"name":"skill_note","args":{"name":"csv-summary","note":"Works best when file encoding is UTF-8.","outcome":"success"}}</tool>',
    "skill_eval": '<tool>{"name":"skill_eval","args":{"name":"csv-summary"}}</tool>',
}


@dataclass(frozen=True)
class SkillPackage:
    name: str
    root: Path
    skill_file: Path
    memory_file: Path
    tests_dir: Path
    status_file: Path


def validate_auto_skill_tool(agent, name, args):
    args = args or {}
    if name == "find_skill":
        if not str(args.get("query", "")).strip():
            raise ValueError("query must not be empty")
        limit = int(args.get("limit", 5))
        if limit < 1 or limit > 20:
            raise ValueError("limit must be in [1, 20]")
        return
    if name in {"read_skill", "skill_eval"}:
        _validate_skill_name(args.get("name", ""))
        return
    if name == "skill_note":
        _validate_skill_name(args.get("name", ""))
        if not str(args.get("note", "")).strip():
            raise ValueError("note must not be empty")
        return
    if name == "skill_create":
        _validate_skill_name(args.get("name", ""))
        if not str(args.get("description", "")).strip():
            raise ValueError("description must not be empty")
        if not str(args.get("body", "")).strip():
            raise ValueError("body must not be empty")
        _package(agent, args["name"])
        return
    if name == "update_skill":
        _validate_skill_name(args.get("name", ""))
        package = _package(agent, args["name"])
        if not package.skill_file.exists():
            raise ValueError("skill does not exist")
        if not any(str(args.get(key, "")).strip() for key in ("body", "description", "tests", "notes")):
            raise ValueError("update_skill needs body, description, tests, or notes")
        return


def tool_find_skill(agent, args):
    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit", 5))
    tokens = _tokens(query)
    rows = []
    for skill in skillslib.list_skills(agent.skills, user_invocable_only=False):
        memory = _read_memory(Path(skill.skill_root) / ".memory.md") if skill.skill_root else ""
        haystack = " ".join(
            [
                skill.name,
                skill.description,
                skill.when_to_use,
                skill.argument_hint,
                skill.source,
                memory,
            ]
        )
        score = _score(tokens, haystack)
        if score <= 0 and query.lower() not in haystack.lower():
            continue
        rows.append((score, skill, memory))
    rows.sort(key=lambda item: (-item[0], item[1].name))
    if not rows:
        return "(no matching skills)"
    lines = []
    for score, skill, memory in rows[:limit]:
        description = skill.description or skill.when_to_use or "No description"
        memory_tail = _last_memory_line(memory)
        suffix = f" | memory: {memory_tail}" if memory_tail else ""
        lines.append(f"/{skill.name} score={score} source={skill.source}: {description}{suffix}")
    return "\n".join(lines)


def tool_read_skill(agent, args):
    name = _validate_skill_name(args.get("name", ""))
    skill = agent.skills.get(name)
    if not skill:
        return f"error: skill {name!r} not found"
    root = Path(skill.skill_root) if skill.skill_root else None
    body = skill.render("$ARGUMENTS")
    lines = [
        f"name: {skill.name}",
        f"description: {skill.description or '-'}",
        f"source: {skill.source}",
        f"context: {skill.context}",
        f"root: {root or '-'}",
        "",
        "SKILL.md:",
        body,
    ]
    if _bool(args.get("include_memory", True)) and root:
        memory = _read_memory(root / ".memory.md")
        lines.extend(["", ".memory.md:", memory or "(empty)"])
    return "\n".join(lines)


def tool_skill_create(agent, args):
    name = _validate_skill_name(args.get("name", ""))
    package = _package(agent, name)
    if package.root.exists() and not _bool(args.get("overwrite", False)):
        return f"error: skill {name!r} already exists; pass overwrite=true to replace"
    package.root.mkdir(parents=True, exist_ok=True)
    package.skill_file.write_text(
        _skill_markdown(name, args.get("description", ""), args.get("body", "")),
        encoding="utf-8",
    )
    tests = str(args.get("tests", "") or "")
    if tests.strip():
        package.tests_dir.mkdir(parents=True, exist_ok=True)
        (package.tests_dir / "test_skill.py").write_text(tests, encoding="utf-8")
    if str(args.get("notes", "")).strip():
        _append_memory(package, args.get("notes", ""), outcome="created")
    eval_result = _run_eval(agent, package) if _bool(args.get("run_tests", True)) else "evaluation: skipped"
    _write_status(package, "registered" if _evaluation_passed(eval_result) else "failed", eval_result)
    _refresh_skills(agent)
    return f"created .pico/skills/{name}\n{eval_result}"


def tool_update_skill(agent, args):
    name = _validate_skill_name(args.get("name", ""))
    package = _package(agent, name)
    if not package.skill_file.exists():
        return f"error: skill {name!r} not found"
    metadata, old_body = skillslib.parse_frontmatter(package.skill_file.read_text(encoding="utf-8"))
    description = str(args.get("description") or metadata.get("description") or "").strip()
    body = str(args.get("body") or old_body).strip()
    package.skill_file.write_text(_skill_markdown(name, description, body), encoding="utf-8")
    tests = str(args.get("tests", "") or "")
    if tests.strip():
        package.tests_dir.mkdir(parents=True, exist_ok=True)
        (package.tests_dir / "test_skill.py").write_text(tests, encoding="utf-8")
    if str(args.get("notes", "")).strip():
        _append_memory(package, args.get("notes", ""), outcome="updated")
    eval_result = _run_eval(agent, package) if _bool(args.get("run_tests", True)) else "evaluation: skipped"
    _write_status(package, "registered" if _evaluation_passed(eval_result) else "failed", eval_result)
    _refresh_skills(agent)
    return f"updated .pico/skills/{name}\n{eval_result}"


def tool_skill_note(agent, args):
    name = _validate_skill_name(args.get("name", ""))
    package = _package(agent, name)
    if not package.skill_file.exists():
        return f"error: skill {name!r} not found"
    _append_memory(package, args.get("note", ""), outcome=str(args.get("outcome", "observation") or "observation"))
    return f"appended .pico/skills/{name}/.memory.md"


def tool_skill_eval(agent, args):
    name = _validate_skill_name(args.get("name", ""))
    package = _package(agent, name)
    if not package.skill_file.exists():
        return f"error: skill {name!r} not found"
    result = _run_eval(agent, package)
    _write_status(package, "registered" if _evaluation_passed(result) else "failed", result)
    _refresh_skills(agent)
    return result


def autoskill_status(agent):
    project_root = _autoskill_root(agent)
    rows = []
    for skill in skillslib.list_skills(agent.skills, user_invocable_only=False):
        root = Path(skill.skill_root) if skill.skill_root else None
        if root and _is_relative_to(root, project_root):
            memory = _read_memory(root / ".memory.md")
            tests = root / "tests"
            rows.append(
                {
                    "name": skill.name,
                    "description": skill.description or skill.when_to_use or "",
                    "memory_notes": sum(1 for line in memory.splitlines() if line.startswith("- ")),
                    "tests": tests.exists(),
                }
            )
    if not rows:
        return "No auto-skills in .pico/skills yet."
    lines = ["Auto-skills:"]
    for row in sorted(rows, key=lambda item: item["name"]):
        tests = "tests=yes" if row["tests"] else "tests=no"
        lines.append(f"- /{row['name']}: {row['description']} ({tests}, memory_notes={row['memory_notes']})")
    return "\n".join(lines)


def _refresh_skills(agent):
    agent.skills = skillslib.discover_skills(agent.root)
    refresh = getattr(agent, "refresh_prefix", None)
    if callable(refresh):
        refresh(force=True)


def _run_eval(agent, package: SkillPackage):
    if not package.tests_dir.exists():
        _append_memory(package, "No tests directory; skill registered without executable evaluation.", outcome="eval_skipped")
        return "evaluation: skipped (no tests/ directory)"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(package.tests_dir), "-q"],
        cwd=agent.root,
        capture_output=True,
        text=True,
        timeout=60,
        env=agent.shell_env(),
    )
    summary = _clip((result.stdout + "\n" + result.stderr).strip(), 1000)
    outcome = "eval_passed" if result.returncode == 0 else "eval_failed"
    _append_memory(package, f"pytest exit_code={result.returncode}\n{summary}", outcome=outcome)
    status = "passed" if result.returncode == 0 else "failed"
    return f"evaluation: {status}\nexit_code: {result.returncode}\n{summary or '(empty)'}"


def _skill_markdown(name, description, body):
    description = str(description).strip()
    body = str(body).strip()
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "source: auto\n"
        "user-invocable: true\n"
        "---\n"
        f"{body}\n"
    )


def _append_memory(package: SkillPackage, note, outcome="observation"):
    package.memory_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    content = package.memory_file.read_text(encoding="utf-8") if package.memory_file.exists() else f"# Skill Memory: {package.name}\n\n"
    entry = f"- {timestamp} [{outcome}] {_clip(str(note).strip(), 1600)}\n"
    package.memory_file.write_text(content.rstrip() + "\n" + entry, encoding="utf-8")


def _package(agent, name):
    name = _validate_skill_name(name)
    root = _autoskill_root(agent) / name
    return SkillPackage(
        name=name,
        root=root,
        skill_file=root / "SKILL.md",
        memory_file=root / ".memory.md",
        tests_dir=root / "tests",
        status_file=root / ".autoskill.json",
    )


def _autoskill_root(agent):
    root = (Path(agent.root) / ".pico" / "skills").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _validate_skill_name(name):
    value = str(name or "").strip().lower().replace("_", "-")
    if not SKILL_NAME_RE.match(value):
        raise ValueError("skill name must be kebab-case, start with a letter, and contain 2-63 chars")
    return value


def _tokens(text):
    return {token for token in re.findall(r"[a-z0-9]+", str(text).lower()) if len(token) > 1}


def _score(tokens, text):
    hay_tokens = _tokens(text)
    return len(tokens & hay_tokens)


def _read_memory(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _last_memory_line(memory):
    for line in reversed(str(memory).splitlines()):
        line = line.strip()
        if line.startswith("- "):
            return _clip(line[2:], 140)
    return ""


def _bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _clip(text, limit):
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _evaluation_passed(result):
    return str(result).startswith("evaluation: passed") or str(result).startswith("evaluation: skipped")


def _write_status(package, status, eval_result):
    payload = {
        "name": package.name,
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_evaluation": _clip(eval_result, 2000),
    }
    package.status_file.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _is_relative_to(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False
