import json

from lcah.evaluation.real_agent.contracts import AttemptIdentity
from lcah.evaluation.real_agent.evidence import EvidenceStore, event_digest


def identity():
    return AttemptIdentity("task-1", "production", 0, "task-1:0", 7)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_evidence_store_deduplicates_blobs_and_hash_chains_events(tmp_path):
    store = EvidenceStore(tmp_path)
    assert store.put_blob(b"same") == store.put_blob(b"same")
    attempt = store.start_attempt(identity(), {"model": "deepseek-v4-flash"})
    store.append_event(attempt, "model_request", {"prompt": "hello"})
    store.append_event(attempt, "model_response", {"text": "world"})
    rows = read_jsonl(attempt / "trajectory.jsonl")
    assert [row["sequence"] for row in rows] == [1, 2]
    assert rows[1]["previous_event_sha256"] == event_digest(rows[0])


def test_secret_redaction_never_persists_secret_value(tmp_path):
    store = EvidenceStore(tmp_path, secret_values={"provider_key": "sk-live-secret"})
    attempt = store.start_attempt(identity(), {"authorization": "sk-live-secret"})
    store.append_event(attempt, "tool_result", {"output": "key=sk-live-secret"})
    all_text = "".join(path.read_text(errors="ignore") for path in tmp_path.rglob("*") if path.is_file())
    assert "sk-live-secret" not in all_text
    assert "secret_detected" in all_text


def test_finish_attempt_is_immutable(tmp_path):
    store = EvidenceStore(tmp_path)
    attempt = store.start_attempt(identity(), {})
    store.finish_attempt(attempt, {"status": "pass", "grader_complete": True})
    try:
        store.finish_attempt(attempt, {"status": "fail", "grader_complete": True})
    except FileExistsError:
        pass
    else:
        raise AssertionError("terminal outcome was overwritten")
