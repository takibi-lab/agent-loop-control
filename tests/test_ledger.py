"""Tests for ledger writer and verifier."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_loop.ledger import (
    LedgerAppendError,
    _canonical_bytes,
    _sha256,
    append_event,
    build_event,
)
from agent_loop.verifier import verify_ledger


def test_first_append_has_null_prev_hash(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ev = build_event("session.start", "test-agent")
    result = append_event(ledger, ev)
    assert result["prev_hash"] is None
    assert result["hash"]


def test_subsequent_append_links_prev_hash(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ev1 = build_event("session.start", "test-agent")
    r1 = append_event(ledger, ev1)

    ev2 = build_event("session.end", "test-agent")
    r2 = append_event(ledger, ev2)

    assert r2["prev_hash"] == r1["hash"]


def test_append_does_not_rewrite_existing_lines(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ev1 = build_event("session.start", "test-agent")
    append_event(ledger, ev1)
    original_first_line = ledger.read_text().splitlines()[0]

    ev2 = build_event("session.end", "test-agent")
    append_event(ledger, ev2)

    lines = ledger.read_text().splitlines()
    assert lines[0] == original_first_line
    assert len(lines) == 2


def test_hash_excludes_hash_field():
    ev = {"event_type": "test", "hash": "should-be-excluded", "prev_hash": None}
    payload = json.loads(_canonical_bytes(ev))
    assert "hash" not in payload


def test_verify_valid_ledger(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    for etype in ("session.start", "tool.pre", "session.end"):
        append_event(ledger, build_event(etype, "test-agent"))

    result = verify_ledger(ledger)
    assert result["valid"] is True
    assert result["event_count"] == 3
    assert result["errors"] == []


def test_verify_empty_ledger(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("")
    result = verify_ledger(ledger)
    assert result["valid"] is True
    assert result["event_count"] == 0


def test_verify_missing_file(tmp_path):
    result = verify_ledger(tmp_path / "nonexistent.jsonl")
    assert result["valid"] is False


def test_verify_detects_changed_content(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    append_event(ledger, build_event("session.start", "test-agent"))
    append_event(ledger, build_event("session.end", "test-agent"))

    lines = ledger.read_text().splitlines()
    ev = json.loads(lines[0])
    ev["event_type"] = "tampered"
    lines[0] = json.dumps(ev)
    ledger.write_text("\n".join(lines) + "\n")

    result = verify_ledger(ledger)
    assert result["valid"] is False
    assert "hash mismatch" in result["reason"]
    assert result["errors"]


def test_verify_detects_broken_prev_hash(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    append_event(ledger, build_event("session.start", "test-agent"))
    append_event(ledger, build_event("session.end", "test-agent"))

    lines = ledger.read_text().splitlines()
    ev = json.loads(lines[1])
    ev["prev_hash"] = "bad-hash"
    ev["hash"] = _sha256(_canonical_bytes(ev))
    lines[1] = json.dumps(ev)
    ledger.write_text("\n".join(lines) + "\n")

    result = verify_ledger(ledger)
    assert result["valid"] is False
    assert "prev_hash mismatch" in result["reason"]


def test_verify_invalid_jsonl(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text('{"valid": true}\nnot-json\n')
    result = verify_ledger(ledger)
    assert result["valid"] is False
    assert "invalid JSON" in result["reason"]


def test_verify_collects_multiple_errors(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text('{"valid": true}\nnot-json\n{"event_id":"x"}\n', encoding="utf-8")
    result = verify_ledger(ledger, fail_fast=False)
    assert result["valid"] is False
    assert len(result["errors"]) >= 2
    assert "invalid JSON" in result["errors"][0]


def test_append_rejects_malformed_existing_ledger(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(LedgerAppendError):
        append_event(ledger, build_event("session.start", "test-agent"))


def test_concurrent_appends_preserve_chain(tmp_path):
    ledger = tmp_path / "ledger.jsonl"

    def append_one(index: int) -> dict:
        return append_event(
            ledger,
            build_event(
                "tool.pre",
                "test-agent",
                extra={"tool": {"name": "Bash", "command": f"echo {index}"}},
            ),
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(append_one, range(50)))

    assert len({event["hash"] for event in results}) == 50
    result = verify_ledger(ledger)
    assert result["valid"] is True
    assert result["event_count"] == 50
