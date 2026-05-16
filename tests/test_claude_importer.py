"""Tests for the Claude Code session transcript importer."""

import json
from pathlib import Path

from agent_loop.claude_importer import import_claude_session, is_claude_session
from agent_loop.importer import import_session
from agent_loop.verifier import verify_ledger

EXAMPLE = Path("examples/claude-code/claude-code-session-input.jsonl")


def _write(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _events(ledger: Path) -> list[dict]:
    return [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]


def _assistant(content: list[dict]) -> dict:
    return {"type": "assistant", "uuid": "a", "sessionId": "s1", "message": {"role": "assistant", "content": content}}


def _user(content, **extra) -> dict:
    return {"type": "user", "uuid": "u", "sessionId": "s1", "message": {"role": "user", "content": content}, **extra}


def test_detects_claude_format(tmp_path):
    claude = tmp_path / "claude.jsonl"
    _write(claude, [_user("hello", cwd="/work")])
    codex = tmp_path / "codex.jsonl"
    _write(codex, [{"type": "function_call", "name": "bash", "arguments": {"command": "ls"}}])

    assert is_claude_session(claude) is True
    assert is_claude_session(codex) is False


def test_tool_use_block_normalizes_to_tool_pre(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(session, [_assistant([{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls -la"}}])])
    ledger = tmp_path / "l.jsonl"

    count = import_claude_session(session, ledger_path=ledger)

    assert count == 1
    events = _events(ledger)
    assert events[0]["event_type"] == "tool.pre"
    assert events[0]["tool"]["name"] == "Bash"
    assert events[0]["tool"]["call_id"] == "t1"
    assert events[0]["tool"]["command"] == "ls -la"


def test_tool_result_block_normalizes_to_tool_post(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(session, [
        _assistant([{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]),
        _user([{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]),
    ])
    ledger = tmp_path / "l.jsonl"

    import_claude_session(session, ledger_path=ledger)

    events = _events(ledger)
    assert [e["event_type"] for e in events] == ["tool.pre", "tool.post"]
    assert events[1]["tool"] == {"name": "Bash", "call_id": "t1", "success": True}


def test_tool_result_error_normalizes_to_tool_error(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(session, [
        _user([{"type": "tool_result", "tool_use_id": "t9", "content": "boom", "is_error": True}]),
    ])
    ledger = tmp_path / "l.jsonl"

    import_claude_session(session, ledger_path=ledger)

    events = _events(ledger)
    assert events[0]["event_type"] == "tool.error"
    assert events[0]["tool"]["success"] is False
    assert events[0]["tool"]["error"] == "boom"


def test_genuine_text_user_record_is_prompt(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(session, [_user("please review the code")])
    ledger = tmp_path / "l.jsonl"

    import_claude_session(session, ledger_path=ledger)

    events = _events(ledger)
    assert events[0]["event_type"] == "prompt.submitted"
    assert events[0]["prompt"] == "please review the code"


def test_tool_result_user_record_is_not_counted_as_prompt(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(session, [_user([{"type": "tool_result", "tool_use_id": "t1", "content": "output"}])])
    ledger = tmp_path / "l.jsonl"

    import_claude_session(session, ledger_path=ledger)

    events = _events(ledger)
    assert [e["event_type"] for e in events] == ["tool.post"]
    assert not any(e["event_type"] == "prompt.submitted" for e in events)


def test_meta_user_record_is_skipped(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(session, [_user("<local-command-caveat>noise</local-command-caveat>", isMeta=True)])
    ledger = tmp_path / "l.jsonl"

    count = import_claude_session(session, ledger_path=ledger)

    assert count == 0
    assert not ledger.exists()


def test_assistant_text_normalizes_to_recommendation(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(session, [_assistant([{"type": "text", "text": "Use a safer command."}])])
    ledger = tmp_path / "l.jsonl"

    import_claude_session(session, ledger_path=ledger)

    events = _events(ledger)
    assert events[0]["event_type"] == "recommendation.created"
    assert events[0]["message"] == "Use a safer command."


def test_assistant_text_and_tool_use_emit_both_events(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(session, [_assistant([
        {"type": "text", "text": "Listing files."},
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
    ])])
    ledger = tmp_path / "l.jsonl"

    import_claude_session(session, ledger_path=ledger)

    events = _events(ledger)
    assert [e["event_type"] for e in events] == ["recommendation.created", "tool.pre"]


def test_unsupported_record_emits_blind_spot(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(session, [{"type": "future-mystery-record", "sessionId": "s1"}])
    ledger = tmp_path / "l.jsonl"

    import_claude_session(session, ledger_path=ledger)

    events = _events(ledger)
    assert events[0]["event_type"] == "blind_spot.declared"
    assert "future-mystery-record" in events[0]["blind_spots"][0]


def test_attachment_hook_permission_decision_normalizes_to_approval(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(
        session,
        [
            {
                "type": "attachment",
                "sessionId": "s1",
                "attachment": {
                    "type": "hook_permission_decision",
                    "decision": "allow",
                    "toolUseID": "tu1",
                    "hookEvent": "PermissionRequest",
                },
            }
        ],
    )
    ledger = tmp_path / "l.jsonl"

    import_claude_session(session, ledger_path=ledger)

    events = _events(ledger)
    assert events[0]["event_type"] == "approval.resolved"
    assert events[0]["approval"]["status"] == "approved"
    assert events[0]["approval"]["request_id"] == "tu1"


def test_attachment_metadata_subtype_and_system_record_are_skipped(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(
        session,
        [
            {"type": "attachment", "sessionId": "s1", "attachment": {"type": "skill_listing", "content": "x"}},
            {"type": "system", "subtype": "turn_duration", "sessionId": "s1"},
            {"type": "pr-link", "prNumber": 1, "sessionId": "s1"},
        ],
    )
    ledger = tmp_path / "l.jsonl"

    count = import_claude_session(session, ledger_path=ledger)

    assert count == 0
    assert not ledger.exists()


def test_unknown_attachment_subtype_emits_blind_spot(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(
        session,
        [{"type": "attachment", "sessionId": "s1", "attachment": {"type": "mystery_attachment"}}],
    )
    ledger = tmp_path / "l.jsonl"

    import_claude_session(session, ledger_path=ledger)

    events = _events(ledger)
    assert events[0]["event_type"] == "blind_spot.declared"
    assert "mystery_attachment" in events[0]["blind_spots"][0]


def test_permission_mode_change_emits_event_only_on_transition(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(
        session,
        [
            {"type": "permission-mode", "permissionMode": "default", "sessionId": "s1"},
            {"type": "permission-mode", "permissionMode": "default", "sessionId": "s1"},
            {"type": "permission-mode", "permissionMode": "acceptEdits", "sessionId": "s1"},
        ],
    )
    ledger = tmp_path / "l.jsonl"

    count = import_claude_session(session, ledger_path=ledger)

    assert count == 2
    events = _events(ledger)
    assert [e["event_type"] for e in events] == ["policy.mode_changed", "policy.mode_changed"]
    assert events[0]["policy"]["mode"] == "default"
    assert events[1]["policy"]["mode"] == "acceptEdits"
    assert events[1]["policy"]["previous_mode"] == "default"


def test_metadata_record_types_are_skipped(tmp_path):
    """Pure transcript bookkeeping records produce no events at all."""
    session = tmp_path / "s.jsonl"
    _write(
        session,
        [
            {"type": "file-history-snapshot", "messageId": "m1", "sessionId": "s1"},
            {"type": "last-prompt", "leafUuid": "x", "sessionId": "s1"},
            {"type": "ai-title", "aiTitle": "Some title", "sessionId": "s1"},
        ],
    )
    ledger = tmp_path / "l.jsonl"

    count = import_claude_session(session, ledger_path=ledger)

    assert count == 0
    assert not ledger.exists()


def test_import_with_policy_classifies_only_tool_pre(tmp_path, sample_policy_yaml):
    """A policy file tags imported tool.pre events; other events stay untagged."""
    session = tmp_path / "s.jsonl"
    _write(
        session,
        [
            _user("please run the build", cwd="/work"),
            _assistant(
                [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "git status --short"}}]
            ),
        ],
    )
    ledger = tmp_path / "l.jsonl"

    import_claude_session(session, ledger_path=ledger, policy_path=str(sample_policy_yaml))

    by_type = {e["event_type"]: e for e in _events(ledger)}
    assert by_type["tool.pre"]["policy"]["decision"] == "allow"
    assert by_type["tool.pre"]["policy"]["rule_id"] == "allow-readonly"
    assert "policy" not in by_type["prompt.submitted"]


def test_path_tool_records_files_array(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(session, [_assistant([
        {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/work/app.py"}},
    ])])
    ledger = tmp_path / "l.jsonl"

    import_claude_session(session, ledger_path=ledger)

    events = _events(ledger)
    assert events[0]["files"] == [{"path": "/work/app.py", "operation": "read"}]


def test_subagent_transcripts_are_imported_and_attributed(tmp_path):
    session = tmp_path / "sess-x.jsonl"
    _write(session, [_user("main prompt", sessionId="sess-x")])
    sub_dir = tmp_path / "sess-x" / "subagents"
    sub_dir.mkdir(parents=True)
    sub_file = sub_dir / "agent-abc123.jsonl"
    _write(sub_file, [
        {"type": "assistant", "uuid": "sa", "isSidechain": True, "agentId": "abc123", "sessionId": "sess-x",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "ts1", "name": "Grep", "input": {"pattern": "TODO"}}]}},
    ])
    (sub_dir / "agent-abc123.meta.json").write_text(
        json.dumps({"agentType": "Explore", "description": "Find TODOs"}), encoding="utf-8"
    )
    ledger = tmp_path / "l.jsonl"

    count = import_claude_session(session, ledger_path=ledger)

    assert count == 2
    events = _events(ledger)
    sub_events = [e for e in events if "sub_agent" in e]
    assert len(sub_events) == 1
    assert sub_events[0]["event_type"] == "tool.pre"
    assert sub_events[0]["sub_agent"] == {
        "agent_id": "abc123",
        "parent_session_id": "sess-x",
        "type": "Explore",
        "description": "Find TODOs",
    }
    assert sub_events[0]["session"]["agent_id"] == "abc123"


def test_import_session_dispatches_to_claude_importer(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(session, [_assistant([{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}])])
    ledger = tmp_path / "l.jsonl"

    import_session(session, ledger_path=ledger)

    events = _events(ledger)
    assert events[0]["source"]["agent"] == "claude-code"
    assert events[0]["event_type"] == "tool.pre"


def test_malformed_jsonl_emits_blind_spot(tmp_path):
    session = tmp_path / "s.jsonl"
    session.write_text('{"type": "user", "uuid": "u1", "message": {"role": "user", "content": "hi"}}\nnot-json\n')
    ledger = tmp_path / "l.jsonl"

    import_claude_session(session, ledger_path=ledger)

    events = _events(ledger)
    assert events[-1]["event_type"] == "blind_spot.declared"
    assert "malformed JSON" in events[-1]["blind_spots"][0]


def test_ledger_integrity_after_claude_import(tmp_path):
    session = tmp_path / "s.jsonl"
    _write(session, [
        _user("do a thing"),
        _assistant([{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "echo hi"}}]),
        _user([{"type": "tool_result", "tool_use_id": "t1", "content": "hi"}]),
    ])
    ledger = tmp_path / "l.jsonl"

    import_claude_session(session, ledger_path=ledger)

    assert verify_ledger(ledger)["valid"] is True


def test_example_claude_transcript_imports_meaningfully(tmp_path):
    ledger = tmp_path / "l.jsonl"

    count = import_session(EXAMPLE, ledger_path=ledger)

    events = _events(ledger)
    types = {e["event_type"] for e in events}
    assert {"prompt.submitted", "recommendation.created", "tool.pre", "tool.post"} <= types
    # The example's sub-agent transcript contributes a failed Read.
    assert any(e["event_type"] == "tool.error" for e in events)
    assert any("sub_agent" in e for e in events)
    assert count == len(events)
