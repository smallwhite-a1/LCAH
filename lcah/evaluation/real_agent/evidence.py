"""Content-addressed, append-only evidence for real-agent attempts."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .contracts import AttemptIdentity


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def event_digest(event: dict) -> str:
    return "sha256:" + hashlib.sha256(_canonical(event)).hexdigest()


class EvidenceStore:
    def __init__(self, root: str | Path, secret_values: dict[str, str] | None = None):
        self.root = Path(root)
        self.secret_values = {k: v for k, v in (secret_values or {}).items() if v}

    def _redact(self, value):
        if isinstance(value, dict):
            return {k: self._redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact(v) for v in value]
        if isinstance(value, str):
            for kind, secret in self.secret_values.items():
                if secret in value:
                    return {"secret_detected": True, "secret_type": kind,
                            "redacted_sha256": "sha256:" + hashlib.sha256(secret.encode()).hexdigest()}
        return value

    def _atomic(self, path: Path, payload) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(_canonical(self._redact(payload)) + b"\n")
        os.replace(temporary, path)

    def put_blob(self, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        path = self.root / "blobs" / "sha256" / digest
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(content)
            os.replace(temporary, path)
        return f"sha256:{digest}"

    def attempt_path(self, identity: AttemptIdentity) -> Path:
        return self.root / "attempts" / identity.task_id / identity.condition / str(identity.repetition)

    def start_attempt(self, identity: AttemptIdentity, metadata: dict) -> Path:
        path = self.attempt_path(identity)
        path.mkdir(parents=True, exist_ok=True)
        metadata_path = path / "metadata.json"
        if not metadata_path.exists():
            self._atomic(metadata_path, {"identity": identity.to_dict(), **metadata})
        return path

    def append_event(self, attempt: Path, event_type: str, payload: dict) -> dict:
        trajectory = attempt / "trajectory.jsonl"
        rows = []
        if trajectory.exists():
            rows = [json.loads(line) for line in trajectory.read_text().splitlines() if line]
        event = {
            "sequence": len(rows) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": str(event_type),
            "previous_event_sha256": event_digest(rows[-1]) if rows else "",
            "payload": self._redact(payload),
        }
        with trajectory.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def finish_attempt(self, attempt: Path, outcome: dict) -> Path:
        path = attempt / "outcome.json"
        if path.exists():
            raise FileExistsError(f"attempt outcome already exists: {path}")
        self._atomic(path, outcome)
        return path

    def terminal(self, identity: AttemptIdentity) -> bool:
        path = self.attempt_path(identity) / "outcome.json"
        if not path.exists():
            return False
        outcome = json.loads(path.read_text())
        return outcome.get("status") in {"pass", "fail"} and outcome.get("grader_complete") is True
