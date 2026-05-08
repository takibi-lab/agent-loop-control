"""Tests for Claude Code hook collector."""

import json

from agent_loop.collector import collect_hook_event
from agent_loop.verifier import verify_ledger


def _make_hook(hook_type: str, **kwargs) -> str:
    return json.dumps({"hook_type": hook_type, **kwargs})


def test_pre_tool_use_normalizes_to_tool_pre(tmp_path):
    ledger = tmp_path / "l.jsonl"
    payload = _make_hook("PreToolUse", tool_name="Bash", tool_input={"command": "ls -la"})
    event = collect_hook_event(payload, ledger_path=ledger)
    assert event["event_type"] == "tool.pre"
    assert event["tool"]["name"] == "Bash"
    assert event["tool"]["command"] == "ls -la"
    assert event["tool"]["input_full"] == {"command": "ls -la"}


def test_post_tool_use_normalizes_to_tool_post(tmp_path):
    ledger = tmp_path / "l.jsonl"
    payload = _make_hook("PostToolUse", tool_name="Glob")
    event = collect_hook_event(payload, ledger_path=ledger)
    assert event["event_type"] == "tool.post"


def test_post_tool_failure_normalizes_to_tool_error(tmp_path):
    ledger = tmp_path / "l.jsonl"
    payload = _make_hook("PostToolUseFailure", tool_name="Bash")
    event = collect_hook_event(payload, ledger_path=ledger)
    assert event["event_type"] == "tool.error"


def test_permission_request_normalizes(tmp_path):
    ledger = tmp_path / "l.jsonl"
    payload = _make_hook("PermissionRequest", reason="needs network")
    event = collect_hook_event(payload, ledger_path=ledger)
    assert event["event_type"] == "approval.requested"


def test_permission_denied_normalizes(tmp_path):
    ledger = tmp_path / "l.jsonl"
    payload = _make_hook("PermissionDenied", reason="policy block")
    event = collect_hook_event(payload, ledger_path=ledger)
    assert event["event_type"] == "approval.resolved"
    assert event["approval"]["status"] == "denied"


def test_session_start_normalizes(tmp_path):
    ledger = tmp_path / "l.jsonl"
    event = collect_hook_event(_make_hook("SessionStart"), ledger_path=ledger)
    assert event["event_type"] == "session.start"


def test_session_end_normalizes(tmp_path):
    ledger = tmp_path / "l.jsonl"
    event = collect_hook_event(_make_hook("SessionEnd"), ledger_path=ledger)
    assert event["event_type"] == "session.end"


def test_unknown_hook_type_emits_blind_spot(tmp_path):
    ledger = tmp_path / "l.jsonl"
    event = collect_hook_event(_make_hook("UnknownEventXYZ"), ledger_path=ledger)
    assert event["event_type"] == "blind_spot.declared"
    assert any("UnknownEventXYZ" in bs for bs in event["blind_spots"])


def test_malformed_json_emits_blind_spot(tmp_path):
    ledger = tmp_path / "l.jsonl"
    event = collect_hook_event("not-json", ledger_path=ledger)
    assert event["event_type"] == "blind_spot.declared"


def test_edit_tool_input_full_is_redacted_before_persistence(tmp_path, sample_policy_yaml):
    ledger = tmp_path / "l.jsonl"
    payload = _make_hook(
        "PreToolUse",
        tool_name="Edit",
        tool_input={
            "file_path": "/tmp/x",
            "new_string": "api_key=hunter2",
            "edits": [{"replacement": "token=abc123"}],
        },
    )
    event = collect_hook_event(payload, ledger_path=ledger, policy_path=sample_policy_yaml)
    assert event["tool"]["input_full"]["new_string"] == "api_key=[REDACTED]"
    assert event["tool"]["input_full"]["edits"][0]["replacement"] == "token=[REDACTED]"
    assert event["redaction"]["applied"] is True
    assert "hunter2" not in ledger.read_text(encoding="utf-8")
    assert "abc123" not in ledger.read_text(encoding="utf-8")


def test_write_tool_path_is_classified(tmp_path, sample_policy_yaml):
    ledger = tmp_path / "l.jsonl"
    payload = _make_hook(
        "PreToolUse",
        tool_name="Write",
        tool_input={"file_path": ".env", "content": "safe=value"},
    )
    event = collect_hook_event(payload, ledger_path=ledger, policy_path=sample_policy_yaml)
    assert event["policy"]["decision"] == "deny"
    assert event["policy"]["rule_id"] == "deny-sensitive"


def test_ledger_integrity_after_multiple_events(tmp_path):
    ledger = tmp_path / "l.jsonl"
    for hook_type in ("SessionStart", "PreToolUse", "PostToolUse", "SessionEnd"):
        collect_hook_event(_make_hook(hook_type), ledger_path=ledger)
    result = verify_ledger(ledger)
    assert result["valid"] is True
    assert result["event_count"] == 4
