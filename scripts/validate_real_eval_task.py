"""Validate one native real-agent task without calling a model."""

import argparse
import json
from pathlib import Path

from lcah.evaluation.real_agent.contracts import TaskSpec
from lcah.evaluation.real_agent.preflight import validate_native_task


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.task).read_text())
    result = validate_native_task(TaskSpec.from_dict(payload), Path(args.output))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
