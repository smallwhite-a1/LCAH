#!/usr/bin/env python3
"""Prepare a 10/50/100-task SWE-bench Lite run for LCAH.

Without ``--run-command`` this only writes a deterministic manifest. With a
command, the command is invoked once per task and receives the public task JSON
through ``LCAH_SWEBENCH_TASK_JSON``. Workspace provisioning and model setup
remain explicit responsibilities of that command in this first phase.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lcah.evaluation.swebench_lite import (  # noqa: E402
    build_manifest,
    run_batch,
    write_manifest,
)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Prepare or run a deterministic 10/50/100-task SWE-bench Lite batch for LCAH."
    )
    parser.add_argument("--tasks-file", required=True, help="SWE-bench JSON or JSONL task source.")
    parser.add_argument("--count", type=int, choices=(10, 50, 100), default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--manifest-out",
        default="artifacts/swebench-lite-{count}.manifest.json",
        help="Output manifest path; {count} is replaced with 10 or 50.",
    )
    parser.add_argument(
        "--results-out",
        default=None,
        help="Optional resumable batch result path. Requires --run-command.",
    )
    parser.add_argument(
        "--run-command",
        default=None,
        help="Optional command invoked once per task; receives LCAH_SWEBENCH_TASK_JSON.",
    )
    return parser


def _command_runner(command):
    def run(task):
        env = os.environ.copy()
        env["LCAH_SWEBENCH_TASK_JSON"] = json.dumps(task, ensure_ascii=False)
        env["LCAH_SWEBENCH_INSTANCE_ID"] = task["instance_id"]
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        passed = result.returncode == 0
        return {
            "status": "pass" if passed else "fail",
            "passed": passed,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    return run


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    manifest_path = Path(args.manifest_out.format(count=args.count))
    manifest = build_manifest(
        args.tasks_file,
        count=args.count,
        seed=args.seed,
    )
    write_manifest(manifest_path, manifest)
    print(f"wrote {args.count} tasks to {manifest_path}")

    if args.run_command and not args.results_out:
        raise SystemExit("--results-out is required when --run-command is provided")
    if args.results_out and not args.run_command:
        raise SystemExit("--run-command is required when --results-out is provided")
    if args.run_command:
        artifact = run_batch(
            manifest_path,
            args.results_out,
            _command_runner(args.run_command),
        )
        print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
