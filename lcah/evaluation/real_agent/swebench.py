"""Thin bridge to the official SWE-bench Docker harness."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class SWEbenchDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class OfficialSWEbenchResult:
    instance_id: str
    status: str
    passed: bool
    valid_run: bool
    raw_report: dict

    def to_dict(self):
        return {"instance_id": self.instance_id, "status": self.status,
                "passed": self.passed, "valid_run": self.valid_run,
                "raw_report": dict(self.raw_report)}


def check_swebench_installation() -> None:
    if importlib.util.find_spec("swebench") is None:
        raise SWEbenchDependencyError(
            "official swebench harness is not installed; install the pinned Phase-B integration dependency"
        )


def build_prediction(instance_id: str, patch: str, model_name: str) -> dict[str, str]:
    return {"instance_id": str(instance_id), "model_name_or_path": str(model_name),
            "model_patch": str(patch)}


def parse_official_report(path: str | Path, instance_id: str) -> OfficialSWEbenchResult:
    report = json.loads(Path(path).read_text())
    if instance_id in report.get("error_ids", []):
        return OfficialSWEbenchResult(instance_id, "grader_error", False, False, report)
    if instance_id in report.get("resolved_ids", []):
        return OfficialSWEbenchResult(instance_id, "pass", True, True, report)
    if instance_id in report.get("unresolved_ids", []):
        return OfficialSWEbenchResult(instance_id, "fail", False, True, report)
    item = report.get(instance_id)
    if isinstance(item, dict):
        if item.get("resolved") is True:
            return OfficialSWEbenchResult(instance_id, "pass", True, True, report)
        if item.get("resolved") is False:
            return OfficialSWEbenchResult(instance_id, "fail", False, True, report)
    return OfficialSWEbenchResult(instance_id, "grader_error", False, False, report)


class SWEbenchHarness:
    def run(self, *, dataset_name: str, predictions_path: str | Path, run_id: str,
            report_path: str | Path, max_workers: int = 1, timeout: int = 3600):
        check_swebench_installation()
        command = [sys.executable, "-m", "swebench.harness.run_evaluation",
                   "--dataset_name", dataset_name, "--predictions_path", str(predictions_path),
                   "--max_workers", str(max_workers), "--run_id", run_id]
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "official SWE-bench harness failed")
        if not Path(report_path).exists():
            raise RuntimeError("official SWE-bench report was not produced")
        return result
