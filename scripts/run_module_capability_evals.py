"""Run phase-two compression, memory, and recovery capability evaluations."""

import argparse
import json

from lcah.evaluation.module_suite import run_module_capability_evals


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    artifact = run_module_capability_evals(args.output_dir, repetitions=args.repetitions)
    print(json.dumps(artifact, sort_keys=True))
    valid = True
    for module in artifact["modules"].values():
        analysis = module["analysis"]
        calibration = analysis["calibration"]
        valid = valid and analysis["sensitivity_check"]["detected"]
        valid = valid and 0.60 <= calibration["production_pass_rate"] <= 0.85
        valid = valid and calibration["difficulty"]["basic"]["pass_rate"] >= 0.75
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
