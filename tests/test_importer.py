"""Tests for Codex CLI session JSONL importer."""

import json
import subprocess
from pathlib import Path

from agent_loop.importer import import_codex_session
from agent_loop.verifier import verify_ledger


def _write_session(path: Path, records: list[dict]) -> None:
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def _init_git_repo(path: Path) -> str:
    _run_git(path, "init", "-b", "main")
    _run_git(path, "config", "user.email", "test@test.com")
    _run_git(path, "config", "user.name", "Test")
    (path / "readme.md").write_text("hello\n", encoding="utf-8")
    _run_git(path, "add", "readme.md")
    _run_git(path, "commit", "-m", "init")
    _run_git(path, "remote", "add", "origin", "git@github.com:acme/imported.git")
    return _run_git(path, "rev-parse", "HEAD")


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


def test_function_call_with_json_string_arguments_normalizes_command(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(
        session,
        [
            {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps({"cmd": "git status", "yield_time_ms": 1000}),
            }
        ],
    )
    ledger = tmp_path / "l.jsonl"

    import_codex_session(session, ledger_path=ledger)

    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "tool.pre"
    assert events[0]["tool"]["name"] == "exec_command"
    assert events[0]["tool"]["command"] == "git status"


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


def test_assistant_record_is_imported(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(session, [{"type": "assistant", "content": "Use a safer command."}])
    ledger = tmp_path / "l.jsonl"
    count = import_codex_session(session, ledger_path=ledger)
    assert count == 1

    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "recommendation.created"
    assert events[0]["message"] == "Use a safer command."


def test_codex_desktop_payload_wrapper_imports_tool_events(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    head = _init_git_repo(repo)
    session = tmp_path / "session.jsonl"
    _write_session(
        session,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "sess-1",
                    "cwd": str(repo),
                    "base_instructions": "do not persist this",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-1",
                    "arguments": json.dumps({"cmd": "git status", "yield_time_ms": 1000}),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "On branch main",
                },
            },
        ],
    )
    ledger = tmp_path / "l.jsonl"

    count = import_codex_session(session, ledger_path=ledger, agent="codex-desktop")

    assert count == 2
    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert [e["event_type"] for e in events] == ["tool.pre", "tool.post"]
    assert events[0]["session"]["session_id"] == "sess-1"
    assert events[0]["session"]["cwd"] == str(repo)
    assert events[0]["tool"] == {
        "name": "exec_command",
        "call_id": "call-1",
        "command": "git status",
        "input_summary": "git status",
    }
    assert events[0]["repo"] == {
        "root": str(repo),
        "remote": "github.com/acme/imported",
        "branch": "main",
        "commit": head,
        "dirty": False,
    }
    assert events[1]["tool"] == {
        "name": "exec_command",
        "call_id": "call-1",
        "command": "git status",
        "success": True,
    }


def test_codex_desktop_payload_wrapper_imports_messages(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(
        session,
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Please inspect this."}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "I found one issue."}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "internal instructions"}],
                },
            },
        ],
    )
    ledger = tmp_path / "l.jsonl"

    count = import_codex_session(session, ledger_path=ledger)

    assert count == 2
    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "prompt.submitted"
    assert events[0]["prompt"] == "Please inspect this."
    assert events[1]["event_type"] == "recommendation.created"
    assert events[1]["message"] == "I found one issue."


def test_codex_desktop_custom_tool_output_uses_metadata(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(
        session,
        [
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "call_id": "patch-1",
                    "input": "*** Begin Patch\n*** End Patch",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "patch-1",
                    "output": json.dumps({"output": "Success", "metadata": {"exit_code": 0}}),
                },
            },
        ],
    )
    ledger = tmp_path / "l.jsonl"

    import_codex_session(session, ledger_path=ledger)

    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert [e["event_type"] for e in events] == ["tool.pre", "tool.post"]
    assert events[1]["tool"] == {
        "name": "apply_patch",
        "call_id": "patch-1",
        "exit_code": 0,
        "success": True,
    }


def test_codex_desktop_telemetry_records_are_skipped(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(
        session,
        [
            {"type": "event_msg", "payload": {"type": "token_count", "info": {}}},
            {"type": "response_item", "payload": {"type": "reasoning", "summary": []}},
            {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "t1"}},
            {"type": "event_msg", "payload": {"type": "context_compacted"}},
            {"type": "event_msg", "payload": {"type": "turn_aborted", "reason": "interrupted"}},
            {"type": "event_msg", "payload": {"type": "thread_name_updated", "thread_name": "x"}},
            {"type": "compacted", "message": "summary"},
        ],
    )
    ledger = tmp_path / "l.jsonl"

    count = import_codex_session(session, ledger_path=ledger)

    assert count == 0
    assert not ledger.exists()


def test_item_completed_plan_normalizes_to_recommendation(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(
        session,
        [
            {
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "item": {"type": "Plan", "id": "p1", "text": "# Plan\n- step one"},
                },
            }
        ],
    )
    ledger = tmp_path / "l.jsonl"

    count = import_codex_session(session, ledger_path=ledger)

    assert count == 1
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "recommendation.created"
    assert "step one" in events[0]["message"]


def test_item_completed_unknown_item_type_emits_blind_spot(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(
        session,
        [{"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "MysteryItem"}}}],
    )
    ledger = tmp_path / "l.jsonl"

    import_codex_session(session, ledger_path=ledger)

    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "blind_spot.declared"
    assert "MysteryItem" in events[0]["blind_spots"][0]


def test_view_image_tool_call_normalizes_to_tool_pre(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(
        session,
        [
            {
                "type": "event_msg",
                "payload": {"type": "view_image_tool_call", "call_id": "v1", "path": "/tmp/x.png"},
            }
        ],
    )
    ledger = tmp_path / "l.jsonl"

    count = import_codex_session(session, ledger_path=ledger)

    assert count == 1
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "tool.pre"
    assert events[0]["tool"]["name"] == "view_image"
    assert events[0]["tool"]["call_id"] == "v1"


def test_codex_desktop_mcp_tool_end_imports_post_event(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(
        session,
        [
            {
                "type": "event_msg",
                "payload": {
                    "type": "mcp_tool_call_end",
                    "call_id": "mcp-1",
                    "invocation": {"server": "github", "tool": "fetch_issue", "arguments": {}},
                    "result": {"Ok": {}},
                },
            }
        ],
    )
    ledger = tmp_path / "l.jsonl"

    count = import_codex_session(session, ledger_path=ledger)

    assert count == 1
    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "tool.post"
    assert events[0]["tool"] == {
        "name": "github.fetch_issue",
        "call_id": "mcp-1",
        "success": True,
    }


def test_exec_command_end_normalizes_to_tool_post(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(
        session,
        [
            {
                "type": "function_call",
                "name": "exec_command",
                "call_id": "c1",
                "arguments": json.dumps({"cmd": "ls -la"}),
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "exec_command_end",
                    "call_id": "c1",
                    "command": ["/bin/zsh", "-lc", "ls -la"],
                    "exit_code": 0,
                    "status": "completed",
                    "stdout": "readme.md\n",
                    "stderr": "",
                },
            },
        ],
    )
    ledger = tmp_path / "l.jsonl"

    count = import_codex_session(session, ledger_path=ledger)

    assert count == 2
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [e["event_type"] for e in events] == ["tool.pre", "tool.post"]
    assert events[1]["tool"]["name"] == "exec_command"
    assert events[1]["tool"]["call_id"] == "c1"
    assert events[1]["tool"]["command"] == "ls -la"
    assert events[1]["tool"]["exit_code"] == 0
    assert events[1]["tool"]["success"] is True


def test_exec_command_end_with_nonzero_exit_normalizes_to_tool_error(tmp_path):
    session = tmp_path / "session.jsonl"
    _write_session(
        session,
        [
            {
                "type": "event_msg",
                "payload": {
                    "type": "exec_command_end",
                    "call_id": "c2",
                    "command": ["/bin/zsh", "-lc", "sed -n '1,5p' missing.md"],
                    "exit_code": 1,
                    "status": "failed",
                    "stdout": "",
                    "stderr": "sed: missing.md: No such file or directory",
                },
            }
        ],
    )
    ledger = tmp_path / "l.jsonl"

    count = import_codex_session(session, ledger_path=ledger)

    assert count == 1
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "tool.error"
    assert events[0]["tool"]["name"] == "exec_command"
    assert events[0]["tool"]["exit_code"] == 1
    assert events[0]["tool"]["success"] is False


def _exec_dup_records(*, end_before_output: bool) -> list[dict]:
    """Records for one shell call that emits both exec_command_end and
    function_call_output, ordered either way."""
    call = {
        "type": "function_call",
        "name": "exec_command",
        "call_id": "dup",
        "arguments": json.dumps({"cmd": "git status"}),
    }
    exec_end = {
        "type": "event_msg",
        "payload": {
            "type": "exec_command_end",
            "call_id": "dup",
            "command": ["/bin/zsh", "-lc", "git status"],
            "exit_code": 0,
            "status": "completed",
        },
    }
    output = {"type": "function_call_output", "call_id": "dup", "output": "On branch main"}
    tail = [exec_end, output] if end_before_output else [output, exec_end]
    return [call, *tail]


def test_exec_command_end_and_function_call_output_are_not_double_counted(tmp_path):
    """A shell call emits both exec_command_end and function_call_output for one
    call_id; only the richer exec_command_end becomes a tool.post event."""
    session = tmp_path / "session.jsonl"
    _write_session(session, _exec_dup_records(end_before_output=True))
    ledger = tmp_path / "l.jsonl"

    count = import_codex_session(session, ledger_path=ledger)

    assert count == 2
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [e["event_type"] for e in events] == ["tool.pre", "tool.post"]
    assert events[1]["tool"]["exit_code"] == 0
    assert verify_ledger(ledger)["valid"] is True


def test_exec_command_end_wins_even_when_function_call_output_comes_first(tmp_path):
    """exec_command_end is preferred regardless of transcript order: the leaner
    function_call_output is dropped even when it appears first."""
    session = tmp_path / "session.jsonl"
    _write_session(session, _exec_dup_records(end_before_output=False))
    ledger = tmp_path / "l.jsonl"

    count = import_codex_session(session, ledger_path=ledger)

    assert count == 2
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [e["event_type"] for e in events] == ["tool.pre", "tool.post"]
    # The kept output record is exec_command_end, which carries the exit code.
    assert events[1]["tool"]["exit_code"] == 0
    assert verify_ledger(ledger)["valid"] is True


def test_import_with_policy_classifies_only_tool_pre(tmp_path, sample_policy_yaml):
    """A policy file tags imported tool.pre events; tool.post stays untagged."""
    session = tmp_path / "session.jsonl"
    _write_session(
        session,
        [
            {
                "type": "function_call",
                "name": "exec_command",
                "call_id": "c1",
                "arguments": json.dumps({"cmd": "rm -rf /tmp/x"}),
            },
            {"type": "function_call_output", "call_id": "c1", "output": "done"},
        ],
    )
    ledger = tmp_path / "l.jsonl"

    import_codex_session(session, ledger_path=ledger, policy_path=str(sample_policy_yaml))

    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [e["event_type"] for e in events] == ["tool.pre", "tool.post"]
    assert events[0]["policy"]["decision"] == "deny"
    assert events[0]["policy"]["risk"] == "critical"
    assert "policy" not in events[1]


def test_import_without_policy_leaves_events_untagged(tmp_path):
    """Without a policy file imported events carry no policy decision."""
    session = tmp_path / "session.jsonl"
    _write_session(
        session,
        [{"type": "function_call", "name": "bash", "arguments": {"command": "ls"}}],
    )
    ledger = tmp_path / "l.jsonl"

    import_codex_session(session, ledger_path=ledger)

    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert "policy" not in events[0]


def test_malformed_jsonl_emits_blind_spot(tmp_path):
    session = tmp_path / "session.jsonl"
    session.write_text("not-json\n")
    ledger = tmp_path / "l.jsonl"
    count = import_codex_session(session, ledger_path=ledger)
    assert count == 1
    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "blind_spot.declared"


def test_import_uses_fallback_cwd_for_repo_context(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    head = _init_git_repo(repo)
    session = tmp_path / "session.jsonl"
    _write_session(session, [
        {"type": "function_call", "name": "bash", "arguments": {"command": "git status"}}
    ])
    ledger = tmp_path / "l.jsonl"

    import_codex_session(session, ledger_path=ledger, cwd=repo)

    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert events[0]["session"]["cwd"] == str(repo)
    assert events[0]["repo"] == {
        "root": str(repo),
        "remote": "github.com/acme/imported",
        "branch": "main",
        "commit": head,
        "dirty": False,
    }


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
