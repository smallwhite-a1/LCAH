"""Run the deterministic sensitivity check for the evaluation foundation."""

import argparse
import json

from lcah.evaluation.sanity import run_sanity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    artifact = run_sanity(args.output)
    print(json.dumps(artifact["analysis"], sort_keys=True))
    return 0 if artifact["analysis"]["sensitivity_check"]["detected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
