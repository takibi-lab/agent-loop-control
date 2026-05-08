"""Tests for Codex CLI session JSONL importer."""

import json
from pathlib import Path

from agent_loop.importer import import_codex_session
from agent_loop.verifier import verify_ledger


def _write_session(path: Path, records: list[dict]) -> None:
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_function_call_normalizes_to_tool_pre(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(session, [
        {"type": "function_call", "name": "bash", "arguments": {"command": "ls -la"}}
    ])
    ledger = tmp_path / "l.jsonl"
    count = import_codex_session(session, ledger_path=ledger)
    assert count == 1

    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "tool.pre"
    assert events[0]["tool"]["command"] == "ls -la"


def test_function_call_output_normalizes_to_tool_post(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(session, [
        {"type": "function_call_output", "name": "bash", "exit_code": 0}
    ])
    ledger = tmp_path / "l.jsonl"
    import_codex_session(session, ledger_path=ledger)
    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "tool.post"
    assert events[0]["tool"]["success"] is True


def test_function_call_output_error_normalizes_to_tool_error(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(session, [
        {"type": "function_call_output", "name": "bash", "error": "command not found"}
    ])
    ledger = tmp_path / "l.jsonl"
    import_codex_session(session, ledger_path=ledger)
    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "tool.error"


def test_unsupported_record_emits_blind_spot(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(session, [{"type": "unknown_mystery_type", "data": "stuff"}])
    ledger = tmp_path / "l.jsonl"
    import_codex_session(session, ledger_path=ledger)
    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "blind_spot.declared"


def test_malformed_jsonl_emits_blind_spot(tmp_path):
    session = tmp_path / "session.jsonl"
    session.write_text("not-json\n")
    ledger = tmp_path / "l.jsonl"
    count = import_codex_session(session, ledger_path=ledger)
    assert count == 1
    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "blind_spot.declared"


def test_ledger_integrity_after_import(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(session, [
        {"type": "function_call", "name": "bash", "arguments": {"command": "echo hi"}},
        {"type": "function_call_output", "name": "bash", "exit_code": 0},
    ])
    ledger = tmp_path / "l.jsonl"
    import_codex_session(session, ledger_path=ledger)
    result = verify_ledger(ledger)
    assert result["valid"] is True
