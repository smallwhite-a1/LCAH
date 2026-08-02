#!/usr/bin/env python3
"""Run the deterministic compression-on/off LCAH harness ablation."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lcah.evaluation.evaluator import (  # noqa: E402
    DEFAULT_COMPRESSION_ABLATION_V2_ARTIFACT_PATH,
    run_compression_ablation_v2,
)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Compare LCAH with context compression enabled and disabled."
    )
    parser.add_argument("--benchmark-path", default="benchmarks/coding_tasks.json")
    parser.add_argument(
        "--artifact-path",
        default=str(DEFAULT_COMPRESSION_ABLATION_V2_ARTIFACT_PATH),
    )
    parser.add_argument("--workspace-root", default="artifacts/compression-workspaces")
    parser.add_argument("--max-new-tokens", type=int, default=64)
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    artifact = run_compression_ablation_v2(
        benchmark_path=args.benchmark_path,
        artifact_path=args.artifact_path,
        workspace_root=args.workspace_root,
        max_new_tokens=args.max_new_tokens,
    )
    print(json.dumps(artifact["variants"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
