"""Compare baseline engineering workflows with auto-skill reuse.

This is a deterministic local proxy benchmark, not a SkillsBench run. Each
scenario is executed twice in a fresh workspace:
- baseline: the scripted agent explores the repo and solves the task directly;
- reuse: an auto-skill is registered first, then the scripted agent invokes it.

The report focuses on the coding-agent value of auto-skills: fewer repeated
exploration steps and a more standardized path for recurring engineering tasks.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pico import Pico, SessionStore, WorkspaceContext
from pico.cli import handle_repl_command
from pico.testing import ScriptedModelClient

EXPLORE_TOOLS = {"list_files", "read_file", "search"}
PYTHON = shlex.quote(sys.executable)
PYTEST_CMD = f"PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. {PYTHON} -m pytest tests/test_math_ops.py -q"
CONFIG_CHECK_CMD = f"{PYTHON} scripts/check_config.py"
ORDER_REPORT_CMD = f"{PYTHON} scripts/build_order_report.py"
ORDER_VERIFY_CMD = f"{PYTHON} scripts/verify_order_report.py"


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    domain: str
    task: str
    skill_name: str
    skill_description: str
    skill_body: str
    skill_tests: str
    seed: Callable[[Path], None]
    baseline_outputs: Callable[[], list[str]]
    reuse_outputs: Callable[[], list[str]]
    reuse_command: str
    verifier: Callable[[Path], bool]
    verifier_command: str = ""
    curated_body: str = ""
    curated_outputs: Callable[[], list[str]] | None = None
    curated_command: str = ""


def main() -> int:
    scenarios = [
        _test_failure_triage(),
        _local_env_bootstrap(),
        _order_report(),
    ]
    with tempfile.TemporaryDirectory(prefix="lcah-autoskill-engineering-") as temp_dir:
        root = Path(temp_dir)
        results = [_run_scenario(root, scenario) for scenario in scenarios]
        summary = _summary(results)
        print(json.dumps({"workspace": str(root), "summary": summary, "scenarios": results}, indent=2, sort_keys=True))
    return 0


def _run_scenario(root: Path, scenario: Scenario) -> dict:
    baseline_root = root / scenario.scenario_id / "baseline"
    reuse_root = root / scenario.scenario_id / "reuse"
    baseline_root.mkdir(parents=True)
    reuse_root.mkdir(parents=True)
    scenario.seed(baseline_root)
    scenario.seed(reuse_root)

    baseline_agent = _agent(baseline_root, scenario.baseline_outputs())
    baseline_answer = baseline_agent.ask(scenario.task)
    baseline_verified = scenario.verifier(baseline_root)

    setup_agent = _agent(reuse_root, [])
    creation_result = setup_agent.run_tool(
        "skill_create",
        {
            "name": scenario.skill_name,
            "description": scenario.skill_description,
            "body": scenario.skill_body,
            "tests": scenario.skill_tests,
            "notes": f"Created from a successful {scenario.domain} engineering workflow.",
            "run_tests": True,
        },
    )

    curated_result = None
    if scenario.curated_outputs is not None:
        curated_root = root / scenario.scenario_id / "curated"
        curated_root.mkdir(parents=True)
        scenario.seed(curated_root)
        _install_curated_skill(curated_root, scenario)
        curated_agent = _agent(curated_root, scenario.curated_outputs())
        curated_handled, curated_should_exit, curated_answer = handle_repl_command(
            curated_agent,
            scenario.curated_command or scenario.reuse_command,
        )
        curated_verified = scenario.verifier(curated_root)
        curated_result = {
            "answer": curated_answer,
            "verified": curated_verified,
            "reused_registered_skill": curated_handled and not curated_should_exit and scenario.skill_name in curated_agent.skills,
            **_metrics(curated_agent, scenario.verifier_command),
        }

    reuse_agent = _agent(reuse_root, scenario.reuse_outputs())
    handled, should_exit, reuse_answer = handle_repl_command(reuse_agent, scenario.reuse_command)
    reuse_verified = scenario.verifier(reuse_root)

    baseline_metrics = _metrics(baseline_agent, scenario.verifier_command)
    reuse_metrics = _metrics(reuse_agent, scenario.verifier_command)
    improvement = {
        "tool_steps_saved": baseline_metrics["tool_steps"] - reuse_metrics["tool_steps"],
        "exploration_steps_saved": baseline_metrics["exploration_steps"] - reuse_metrics["exploration_steps"],
        "model_calls_saved": baseline_metrics["model_calls"] - reuse_metrics["model_calls"],
        "tool_step_reduction_ratio": _ratio_saved(baseline_metrics["tool_steps"], reuse_metrics["tool_steps"]),
        "exploration_reduction_ratio": _ratio_saved(
            baseline_metrics["exploration_steps"],
            reuse_metrics["exploration_steps"],
        ),
        "reused_registered_skill": handled and not should_exit and scenario.skill_name in reuse_agent.skills,
        "skill_prompt_loaded": any(f"Skill: {scenario.skill_name}" in prompt for prompt in reuse_agent.model_client.prompts),
        "reuse_verified": reuse_verified,
        "baseline_verified": baseline_verified,
    }
    return {
        "id": scenario.scenario_id,
        "domain": scenario.domain,
        "task": scenario.task,
        "skill": scenario.skill_name,
        "creation_passed": "evaluation: passed" in creation_result,
        "baseline": {"answer": baseline_answer, "verified": baseline_verified, **baseline_metrics},
        "curated": curated_result,
        "reuse": {"answer": reuse_answer, "verified": reuse_verified, **reuse_metrics},
        "improvement": improvement,
    }


def _agent(root: Path, outputs: list[str]) -> Pico:
    return Pico(
        model_client=ScriptedModelClient(outputs),
        workspace=WorkspaceContext.build(root),
        session_store=SessionStore(root / ".pico" / "sessions"),
        approval_policy="auto",
        max_steps=20,
    )


def _metrics(agent: Pico, verifier_command: str = "") -> dict:
    tool_items = [item for item in agent.session["history"] if item.get("role") == "tool"]
    tools = [item["name"] for item in tool_items]
    verifier_failures = 0
    format_errors = 0
    if verifier_command:
        for item in tool_items:
            if item.get("name") != "run_shell":
                continue
            args = item.get("args") or {}
            if verifier_command not in str(args.get("command", "")).strip():
                continue
            content = str(item.get("content", ""))
            if "exit_code: 0" not in content:
                verifier_failures += 1
                if "format_error" in content:
                    format_errors += 1
    return {
        "tool_steps": len(tools),
        "exploration_steps": sum(1 for name in tools if name in EXPLORE_TOOLS),
        "model_calls": len(agent.model_client.prompts),
        "repair_rounds": verifier_failures,
        "format_errors": format_errors,
        "tools": tools,
    }


def _ratio_saved(before: int, after: int) -> float:
    if before <= 0:
        return 0.0
    return round((before - after) / before, 3)


def _summary(results: list[dict]) -> dict:
    count = len(results)
    return {
        "scenario_count": count,
        "baseline_pass_rate": f"{sum(1 for row in results if row['baseline']['verified'])}/{count}",
        "reuse_pass_rate": f"{sum(1 for row in results if row['reuse']['verified'])}/{count}",
        "total_tool_steps_baseline": sum(row["baseline"]["tool_steps"] for row in results),
        "total_tool_steps_reuse": sum(row["reuse"]["tool_steps"] for row in results),
        "total_exploration_steps_baseline": sum(row["baseline"]["exploration_steps"] for row in results),
        "total_exploration_steps_reuse": sum(row["reuse"]["exploration_steps"] for row in results),
        "total_tool_steps_saved": sum(row["improvement"]["tool_steps_saved"] for row in results),
        "total_exploration_steps_saved": sum(row["improvement"]["exploration_steps_saved"] for row in results),
        "all_reuse_verified": all(row["reuse"]["verified"] for row in results),
        "all_skills_created": all(row["creation_passed"] for row in results),
        "table_mode_comparison": _table_mode_comparison(results),
    }


def _table_mode_comparison(results: list[dict]) -> dict:
    rows = [row for row in results if row["id"] == "order-report"]
    if not rows:
        return {}
    row = rows[0]
    modes = {
        "no_skill": row["baseline"],
        "curated_skill": row.get("curated") or {},
        "auto_skill": row["reuse"],
    }
    return {
        name: {
            "pass": bool(value.get("verified")),
            "tool_steps": value.get("tool_steps", 0),
            "exploration_steps": value.get("exploration_steps", 0),
            "repair_rounds": value.get("repair_rounds", 0),
            "format_errors": value.get("format_errors", 0),
        }
        for name, value in modes.items()
    }


def _install_curated_skill(root: Path, scenario: Scenario) -> None:
    skill_dir = root / ".pico" / "skills" / scenario.skill_name
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {scenario.skill_name}",
                f"description: {scenario.skill_description}",
                "user-invocable: true",
                "---",
                scenario.curated_body or scenario.skill_body,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _tool(name: str, args: dict) -> str:
    return f"<tool>{json.dumps({'name': name, 'args': args})}</tool>"


def _write(path: str, content: str) -> str:
    return f'<tool name="write_file" path="{path}"><content>{content}</content></tool>'


def _patch(path: str, old_text: str, new_text: str) -> str:
    return f'<tool name="patch_file" path="{path}"><old_text>{old_text}</old_text><new_text>{new_text}</new_text></tool>'


def _tagged(command: str, tag: str) -> str:
    return f"BENCH_STEP={shlex.quote(tag)} {command}"


def _test_failure_triage() -> Scenario:
    def seed(root: Path) -> None:
        (root / "src").mkdir()
        (root / "tests").mkdir()
        (root / "src" / "__init__.py").write_text("", encoding="utf-8")
        (root / "src" / "math_ops.py").write_text(
            "def add(a, b):\n    return a - b\n",
            encoding="utf-8",
        )
        (root / "tests" / "test_math_ops.py").write_text(
            "from src.math_ops import add\n\n\ndef test_adds_numbers():\n    assert add(2, 3) == 5\n",
            encoding="utf-8",
        )
        (root / "pyproject.toml").write_text("[project]\nname = 'demo'\nversion = '0.1.0'\n", encoding="utf-8")

    return Scenario(
        scenario_id="test-failure-triage",
        domain="debugging-and-testing",
        task="Fix the failing math test and verify it.",
        skill_name="pytest-fix-loop",
        skill_description="Run the known pytest target, inspect the failing implementation, patch it, and re-run tests.",
        skill_body="\n".join(
            [
                "# Pytest Fix Loop",
                "",
                f"Use this repeatable debugging loop for $ARGUMENTS.",
                f"1. Run `{PYTEST_CMD}`.",
                "2. Read the failing implementation file before editing.",
                "3. Patch the smallest bug.",
                f"4. Re-run `{PYTEST_CMD}` and stop when it passes.",
            ]
        ),
        skill_tests="from pathlib import Path\n\n\ndef test_skill_mentions_pytest_and_patch():\n    text = (Path(__file__).resolve().parents[1] / 'SKILL.md').read_text(encoding='utf-8')\n    assert 'pytest' in text\n    assert 'Patch' in text or 'patch' in text\n",
        seed=seed,
        baseline_outputs=lambda: [
            _tool("list_files", {"path": "."}),
            _tool("read_file", {"path": "pyproject.toml", "start": 1, "end": 80}),
            _tool("run_shell", {"command": PYTEST_CMD, "timeout": 30}),
            _tool("search", {"pattern": "def add", "path": "src"}),
            _tool("read_file", {"path": "src/math_ops.py", "start": 1, "end": 40}),
            _tool("read_file", {"path": "tests/test_math_ops.py", "start": 1, "end": 80}),
            _patch("src/math_ops.py", "return a - b", "return a + b  # fixed"),
            _tool("run_shell", {"command": PYTEST_CMD, "timeout": 30}),
            "<final>Fixed the add implementation and pytest passes.</final>",
        ],
        reuse_outputs=lambda: [
            _tool("run_shell", {"command": PYTEST_CMD, "timeout": 30}),
            _tool("read_file", {"path": "src/math_ops.py", "start": 1, "end": 40}),
            _patch("src/math_ops.py", "return a - b", "return a + b  # fixed"),
            _tool("run_shell", {"command": PYTEST_CMD, "timeout": 30}),
            "<final>Fixed with the pytest-fix-loop skill.</final>",
        ],
        reuse_command="/pytest-fix-loop tests/test_math_ops.py",
        verifier=lambda root: _command_ok(root, PYTEST_CMD)
        and "return a + b" in (root / "src" / "math_ops.py").read_text(encoding="utf-8"),
        verifier_command=PYTEST_CMD,
    )


def _local_env_bootstrap() -> Scenario:
    def seed(root: Path) -> None:
        (root / "scripts").mkdir()
        (root / "README.md").write_text(
            "Local setup requires APP_ENV=dev and CACHE_BACKEND=memory in .env.\n",
            encoding="utf-8",
        )
        (root / "pyproject.toml").write_text("[tool.demo]\ncheck = 'scripts/check_config.py'\n", encoding="utf-8")
        (root / "scripts" / "check_config.py").write_text(
            "from pathlib import Path\n"
            "text = Path('.env').read_text(encoding='utf-8')\n"
            "required = {'APP_ENV=dev', 'CACHE_BACKEND=memory'}\n"
            "missing = [item for item in required if item not in text]\n"
            "if missing:\n"
            "    raise SystemExit('missing ' + ','.join(missing))\n"
            "print('config ok')\n",
            encoding="utf-8",
        )

    env_content = "APP_ENV=dev\nCACHE_BACKEND=memory\n"
    return Scenario(
        scenario_id="local-env-bootstrap",
        domain="configuration",
        task="Create the local .env file and verify the config checker.",
        skill_name="local-env-bootstrap",
        skill_description="Create the known local .env defaults and run the project config checker.",
        skill_body="\n".join(
            [
                "# Local Env Bootstrap",
                "",
                "Use this repeatable setup for $ARGUMENTS.",
                "1. Write `.env` with `APP_ENV=dev` and `CACHE_BACKEND=memory`.",
                f"2. Run `{CONFIG_CHECK_CMD}`.",
                "3. Report the checker result.",
            ]
        ),
        skill_tests="from pathlib import Path\n\n\ndef test_skill_mentions_env_and_checker():\n    text = (Path(__file__).resolve().parents[1] / 'SKILL.md').read_text(encoding='utf-8')\n    assert 'APP_ENV=dev' in text\n    assert 'check_config.py' in text\n",
        seed=seed,
        baseline_outputs=lambda: [
            _tool("list_files", {"path": "."}),
            _tool("read_file", {"path": "README.md", "start": 1, "end": 80}),
            _tool("read_file", {"path": "pyproject.toml", "start": 1, "end": 80}),
            _tool("search", {"pattern": "APP_ENV", "path": "."}),
            _write(".env", env_content),
            _tool("run_shell", {"command": CONFIG_CHECK_CMD, "timeout": 20}),
            "<final>Configured .env and checker passes.</final>",
        ],
        reuse_outputs=lambda: [
            _write(".env", env_content),
            _tool("run_shell", {"command": CONFIG_CHECK_CMD, "timeout": 20}),
            "<final>Configured using the local-env-bootstrap skill.</final>",
        ],
        reuse_command="/local-env-bootstrap .env",
        verifier=lambda root: (root / ".env").read_text(encoding="utf-8") == env_content
        and _command_ok(root, CONFIG_CHECK_CMD),
        verifier_command=CONFIG_CHECK_CMD,
    )


def _order_report() -> Scenario:
    def seed(root: Path) -> None:
        (root / "data").mkdir()
        (root / "scripts").mkdir()
        (root / "reports").mkdir()
        (root / "README.md").write_text(
            "Build an ecommerce order report from data/orders.csv.\n"
            "Rules: drop cancelled orders, drop rows missing gross_sales, fill missing discount/refund/ad_spend with 0.\n"
            "Outputs: reports/report.xlsx and reports/summary.json.\n",
            encoding="utf-8",
        )
        (root / "data" / "orders.csv").write_text(
            "\n".join(
                [
                    "order_id,date,channel,gross_sales,discount,refund,ad_spend,status",
                    "1001,2026-01-01,ads,120.00,10.00,0.00,20.00,paid",
                    "1002,2026-01-01,organic,80.00,0.00,0.00,0.00,paid",
                    "1003,2026-01-02,ads,50.00,5.00,45.00,10.00,refunded",
                    "1004,2026-01-02,ads,40.00,,0.00,8.00,paid",
                    "1005,2026-01-03,organic,70.00,0.00,0.00,,cancelled",
                    "1006,2026-01-03,ads,,0.00,0.00,5.00,paid",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (root / "scripts" / "verify_order_report.py").write_text(_order_verifier_script(), encoding="utf-8")

    return Scenario(
        scenario_id="order-report",
        domain="table-data-processing",
        task="Create reports/report.xlsx and reports/summary.json from data/orders.csv.",
        skill_name="ecommerce-order-report",
        skill_description="Clean ecommerce orders, calculate GMV/net sales/refund rate/ROI, and emit xlsx plus JSON reports.",
        skill_body="\n".join(
            [
                "# Ecommerce Order Report",
                "",
                "Use this repeatable table workflow for $ARGUMENTS.",
                "1. Read `data/orders.csv` with DictReader.",
                "2. Drop rows where `status == cancelled` or `gross_sales` is missing.",
                "3. Treat missing `discount`, `refund`, and `ad_spend` as 0.",
                "4. Calculate `gmv`, `net_sales`, `refund_rate`, `roi`, and `order_count`.",
                "5. Write `reports/summary.json` with those exact keys.",
                "6. Write `reports/report.xlsx` with a `Summary` sheet and columns `metric`, `value`.",
                f"7. Run `{ORDER_VERIFY_CMD}` and repair any format or numeric mismatch.",
            ]
        ),
        skill_tests="from pathlib import Path\n\n\ndef test_skill_mentions_required_outputs_and_metrics():\n    text = (Path(__file__).resolve().parents[1] / 'SKILL.md').read_text(encoding='utf-8')\n    for token in ['summary.json', 'report.xlsx', 'gmv', 'net_sales', 'refund_rate', 'roi']:\n        assert token in text\n",
        seed=seed,
        baseline_outputs=lambda: [
            _tool("list_files", {"path": "."}),
            _tool("read_file", {"path": "README.md", "start": 1, "end": 80}),
            _tool("read_file", {"path": "data/orders.csv", "start": 1, "end": 80}),
            _write("scripts/build_order_report.py", _order_builder_script(include_xlsx=False, include_roi=False)),
            _tool("run_shell", {"command": _tagged(ORDER_REPORT_CMD, "no-skill-build-1"), "timeout": 20}),
            _tool("run_shell", {"command": _tagged(ORDER_VERIFY_CMD, "no-skill-verify-1"), "timeout": 20}),
            _tool("read_file", {"path": "scripts/verify_order_report.py", "start": 1, "end": 220}),
            _tool("read_file", {"path": "scripts/build_order_report.py", "start": 1, "end": 260}),
            _write("scripts/build_order_report.py", _order_builder_script(include_xlsx=True, include_roi=False)),
            _tool("run_shell", {"command": _tagged(ORDER_REPORT_CMD, "no-skill-build-2"), "timeout": 20}),
            _tool("run_shell", {"command": _tagged(ORDER_VERIFY_CMD, "no-skill-verify-2"), "timeout": 20}),
            _tool("read_file", {"path": "scripts/build_order_report.py", "start": 1, "end": 260}),
            _write("scripts/build_order_report.py", _order_builder_script(include_xlsx=True, include_roi=True)),
            _tool("run_shell", {"command": _tagged(ORDER_REPORT_CMD, "no-skill-build-3"), "timeout": 20}),
            _tool("run_shell", {"command": _tagged(ORDER_VERIFY_CMD, "no-skill-verify-3"), "timeout": 20}),
            "<final>Order report generated after verifier-guided repairs.</final>",
        ],
        curated_body="\n".join(
            [
                "# Ecommerce Order Report",
                "",
                "Create an ecommerce order report from `data/orders.csv`.",
                "Clean cancelled rows and missing values, calculate GMV, net sales, and refund rate.",
                "Write both `reports/report.xlsx` and `reports/summary.json`.",
            ]
        ),
        curated_outputs=lambda: [
            _write("scripts/build_order_report.py", _order_builder_script(include_xlsx=True, include_roi=False)),
            _tool("run_shell", {"command": _tagged(ORDER_REPORT_CMD, "curated-build-1"), "timeout": 20}),
            _tool("run_shell", {"command": _tagged(ORDER_VERIFY_CMD, "curated-verify-1"), "timeout": 20}),
            _tool("read_file", {"path": "scripts/build_order_report.py", "start": 1, "end": 260}),
            _write("scripts/build_order_report.py", _order_builder_script(include_xlsx=True, include_roi=True)),
            _tool("run_shell", {"command": _tagged(ORDER_REPORT_CMD, "curated-build-2"), "timeout": 20}),
            _tool("run_shell", {"command": _tagged(ORDER_VERIFY_CMD, "curated-verify-2"), "timeout": 20}),
            "<final>Order report generated with the curated skill after one verifier repair.</final>",
        ],
        reuse_outputs=lambda: [
            _write("scripts/build_order_report.py", _order_builder_script(include_xlsx=True, include_roi=True)),
            _tool("run_shell", {"command": _tagged(ORDER_REPORT_CMD, "auto-build-1"), "timeout": 20}),
            _tool("run_shell", {"command": _tagged(ORDER_VERIFY_CMD, "auto-verify-1"), "timeout": 20}),
            "<final>Order report generated with the auto-skill verifier contract.</final>",
        ],
        curated_command="/ecommerce-order-report data/orders.csv",
        reuse_command="/ecommerce-order-report data/orders.csv",
        verifier=lambda root: _command_ok(root, ORDER_VERIFY_CMD),
        verifier_command=ORDER_VERIFY_CMD,
    )


def _order_builder_script(include_xlsx: bool, include_roi: bool) -> str:
    roi_lines = [
        "    summary['roi'] = float((net_sales / ad_spend).quantize(Decimal('0.000001'))) if ad_spend else 0.0",
    ] if include_roi else []
    xlsx_lines = ["    write_xlsx(summary)"] if include_xlsx else []
    return "\n".join(
        [
            "import csv",
            "import json",
            "import zipfile",
            "from decimal import Decimal",
            "from pathlib import Path",
            "from xml.sax.saxutils import escape",
            "",
            "ROOT = Path('.')",
            "OUT = ROOT / 'reports'",
            "OUT.mkdir(exist_ok=True)",
            "",
            "def dec(value):",
            "    value = (value or '').strip()",
            "    return Decimal(value) if value else Decimal('0')",
            "",
            "def cell(ref, value):",
            "    if isinstance(value, (int, float, Decimal)):",
            "        return f'<c r=\"{ref}\"><v>{value}</v></c>'",
            "    return f'<c r=\"{ref}\" t=\"inlineStr\"><is><t>{escape(str(value))}</t></is></c>'",
            "",
            "def write_xlsx(summary):",
            "    rows = [('metric', 'value')] + list(summary.items())",
            "    xml_rows = []",
            "    for row_index, row in enumerate(rows, start=1):",
            "        xml_rows.append(",
            "            f'<row r=\"{row_index}\">'",
            "            + cell(f'A{row_index}', row[0])",
            "            + cell(f'B{row_index}', row[1])",
            "            + '</row>'",
            "        )",
            "    sheet_xml = '<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>' + \\",
            "        '<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>' + \\",
            "        ''.join(xml_rows) + '</sheetData></worksheet>'",
            "    with zipfile.ZipFile(OUT / 'report.xlsx', 'w', zipfile.ZIP_DEFLATED) as zf:",
            "        zf.writestr('[Content_Types].xml', '<?xml version=\"1.0\" encoding=\"UTF-8\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/><Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/></Types>')",
            "        zf.writestr('_rels/.rels', '<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/></Relationships>')",
            "        zf.writestr('xl/workbook.xml', '<?xml version=\"1.0\" encoding=\"UTF-8\"?><workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><sheets><sheet name=\"Summary\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>')",
            "        zf.writestr('xl/_rels/workbook.xml.rels', '<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/></Relationships>')",
            "        zf.writestr('xl/worksheets/sheet1.xml', sheet_xml)",
            "",
            "def main():",
            "    gmv = Decimal('0')",
            "    net_sales = Decimal('0')",
            "    refund = Decimal('0')",
            "    ad_spend = Decimal('0')",
            "    order_count = 0",
            "    with (ROOT / 'data' / 'orders.csv').open(newline='', encoding='utf-8') as handle:",
            "        for row in csv.DictReader(handle):",
            "            if row['status'].strip().lower() == 'cancelled':",
            "                continue",
            "            if not row['gross_sales'].strip():",
            "                continue",
            "            gross = dec(row['gross_sales'])",
            "            discount = dec(row['discount'])",
            "            row_refund = dec(row['refund'])",
            "            row_ad_spend = dec(row['ad_spend'])",
            "            gmv += gross",
            "            net_sales += gross - discount - row_refund",
            "            refund += row_refund",
            "            ad_spend += row_ad_spend",
            "            order_count += 1",
            "    summary = {",
            "        'gmv': float(gmv.quantize(Decimal('0.01'))),",
            "        'net_sales': float(net_sales.quantize(Decimal('0.01'))),",
            "        'refund_rate': float((refund / gmv).quantize(Decimal('0.000001'))) if gmv else 0.0,",
            "        'order_count': order_count,",
            "    }",
            *roi_lines,
            "    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\\n', encoding='utf-8')",
            *xlsx_lines,
            "    print('order report written')",
            "",
            "if __name__ == '__main__':",
            "    main()",
            "",
        ]
    )


def _order_verifier_script() -> str:
    return r'''import csv
import json
import zipfile
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path('.')
EXPECTED_KEYS = ['gmv', 'net_sales', 'refund_rate', 'roi', 'order_count']


def dec(value):
    value = (value or '').strip()
    return Decimal(value) if value else Decimal('0')


def expected_summary():
    gmv = Decimal('0')
    net_sales = Decimal('0')
    refund = Decimal('0')
    ad_spend = Decimal('0')
    order_count = 0
    with (ROOT / 'data' / 'orders.csv').open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            if row['status'].strip().lower() == 'cancelled':
                continue
            if not row['gross_sales'].strip():
                continue
            gross = dec(row['gross_sales'])
            discount = dec(row['discount'])
            row_refund = dec(row['refund'])
            row_ad_spend = dec(row['ad_spend'])
            gmv += gross
            net_sales += gross - discount - row_refund
            refund += row_refund
            ad_spend += row_ad_spend
            order_count += 1
    return {
        'gmv': float(gmv.quantize(Decimal('0.01'))),
        'net_sales': float(net_sales.quantize(Decimal('0.01'))),
        'refund_rate': float((refund / gmv).quantize(Decimal('0.000001'))) if gmv else 0.0,
        'roi': float((net_sales / ad_spend).quantize(Decimal('0.000001'))) if ad_spend else 0.0,
        'order_count': order_count,
    }


def fail(kind, message):
    raise SystemExit(f'{kind}: {message}')


def assert_summary(actual, expected):
    if sorted(actual) != sorted(EXPECTED_KEYS):
        fail('format_error', f'summary keys {sorted(actual)} != {EXPECTED_KEYS}')
    for key, value in expected.items():
        actual_value = actual[key]
        if isinstance(value, float):
            if abs(float(actual_value) - value) > 0.000001:
                fail('value_error', f'{key} {actual_value} != {value}')
        elif actual_value != value:
            fail('value_error', f'{key} {actual_value} != {value}')


def cell_text(cell, ns):
    inline = cell.find('m:is/m:t', ns)
    if inline is not None:
        return inline.text or ''
    value = cell.find('m:v', ns)
    return value.text if value is not None else ''


def read_xlsx_summary(path):
    if not path.exists():
        fail('format_error', 'missing report.xlsx')
    with zipfile.ZipFile(path) as zf:
        workbook = zf.read('xl/workbook.xml').decode('utf-8')
        if 'name="Summary"' not in workbook:
            fail('format_error', 'missing Summary sheet')
        root = ET.fromstring(zf.read('xl/worksheets/sheet1.xml'))
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    rows = []
    for row in root.findall('.//m:row', ns):
        rows.append([cell_text(cell, ns) for cell in row.findall('m:c', ns)])
    if not rows or rows[0] != ['metric', 'value']:
        fail('format_error', 'xlsx header must be metric,value')
    data = {}
    for row in rows[1:]:
        if len(row) >= 2:
            data[row[0]] = row[1]
    if sorted(data) != sorted(EXPECTED_KEYS):
        fail('format_error', f'xlsx metric keys {sorted(data)} != {EXPECTED_KEYS}')
    return data


def main():
    expected = expected_summary()
    summary_path = ROOT / 'reports' / 'summary.json'
    if not summary_path.exists():
        fail('format_error', 'missing summary.json')
    actual = json.loads(summary_path.read_text(encoding='utf-8'))
    assert_summary(actual, expected)
    xlsx_data = read_xlsx_summary(ROOT / 'reports' / 'report.xlsx')
    for key, value in expected.items():
        actual_value = int(xlsx_data[key]) if key == 'order_count' else float(xlsx_data[key])
        if isinstance(value, float):
            if abs(actual_value - value) > 0.000001:
                fail('value_error', f'xlsx {key} {actual_value} != {value}')
        elif actual_value != value:
            fail('value_error', f'xlsx {key} {actual_value} != {value}')
    print('order report verified')


if __name__ == '__main__':
    main()
'''


def _command_ok(root: Path, command: str) -> bool:
    result = subprocess.run(command, cwd=root, shell=True, text=True, capture_output=True, timeout=30)
    return result.returncode == 0


if __name__ == "__main__":
    raise SystemExit(main())
