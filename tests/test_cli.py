"""Tests for CLI validation and error reporting."""

import json

from click.testing import CliRunner

from agent_loop.cli import main
from agent_loop.ledger import append_event, build_event


def test_policy_check_success_reports_counts(sample_policy_yaml):
    result = CliRunner().invoke(main, ["policy", "check", str(sample_policy_yaml)])
    assert result.exit_code == 0
    assert "Rules: 4" in result.output
    assert "Redaction patterns: 1" in result.output


def test_policy_check_invalid_policy_exits_one(tmp_path):
    policy = tmp_path / "bad.yaml"
    policy.write_text(
        """
version: 1
name: bad
defaults:
  decision: maybe
rules: []
""".lstrip(),
        encoding="utf-8",
    )
    result = CliRunner().invoke(main, ["policy", "check", str(policy)])
    assert result.exit_code == 1
    assert "invalid" in result.output
    assert "maybe" in result.output


def test_verify_prints_collected_errors(tmp_path):
    ledger = tmp_path / "bad.jsonl"
    ledger.write_text('not-json\n{"event_id":"x"}\n', encoding="utf-8")
    result = CliRunner().invoke(main, ["verify", str(ledger)])
    assert result.exit_code == 1
    assert "ledger integrity check failed" in result.output
    assert "invalid JSON" in result.output
    assert "missing 'hash'" in result.output


def test_verify_success(tmp_path):
    ledger = tmp_path / "empty.jsonl"
    ledger.write_text("", encoding="utf-8")
    result = CliRunner().invoke(main, ["verify", str(ledger)])
    assert result.exit_code == 0
    assert "0 events verified" in result.output


def test_import_with_policy_file_classifies_tool_pre(tmp_path, sample_policy_yaml):
    session = tmp_path / "session.jsonl"
    session.write_text(
        json.dumps(
            {
                "type": "function_call",
                "name": "exec_command",
                "arguments": json.dumps({"cmd": "rm -rf /tmp/x"}),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"

    result = CliRunner().invoke(
        main,
        ["import", str(session), "--ledger", str(ledger), "--policy-file", str(sample_policy_yaml)],
    )

    assert result.exit_code == 0
    assert "Imported 1 events" in result.output
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert events[0]["policy"]["decision"] == "deny"


def test_search_file_path_matches_tool_input(tmp_path):
    ledger = tmp_path / "l.jsonl"
    append_event(
        ledger,
        build_event(
            "tool.pre",
            "claude-code",
            extra={"tool": {"name": "Read", "input_full": {"file_path": ".env"}}},
        ),
    )

    result = CliRunner().invoke(main, ["search", str(ledger), "--file-path", ".env"])

    assert result.exit_code == 0
    assert "tool.pre" in result.output
    assert "1 event(s) matched" in result.output


def _append_write_event(ledger, *, file_path: str = "pyproject.toml") -> None:
    """Append a non-shell tool event carrying raw tool-input JSON."""
    raw_input = {"file_path": file_path, "content": "[build-system]\nrequires = []"}
    append_event(
        ledger,
        build_event(
            "tool.pre",
            "claude-code",
            extra={
                "tool": {
                    "name": "Write",
                    "input_summary": json.dumps(raw_input),
                    "input_full": raw_input,
                }
            },
        ),
    )


def test_timeline_non_shell_tool_shows_path_not_input_json(tmp_path):
    ledger = tmp_path / "l.jsonl"
    _append_write_event(ledger, file_path="pyproject.toml")

    result = CliRunner().invoke(main, ["timeline", str(ledger)])

    assert result.exit_code == 0
    assert "tool=Write" in result.output
    assert "path=pyproject.toml" in result.output
    # The raw tool-input JSON must not be rendered as a shell command.
    assert "cmd={" not in result.output
    assert '"content"' not in result.output


def test_timeline_shell_tool_still_shows_cmd(tmp_path):
    ledger = tmp_path / "l.jsonl"
    append_event(
        ledger,
        build_event(
            "tool.pre",
            "claude-code",
            extra={"tool": {"name": "Bash", "command": "git status --short"}},
        ),
    )

    result = CliRunner().invoke(main, ["timeline", str(ledger)])

    assert result.exit_code == 0
    assert "cmd=git status --short" in result.output


def test_search_command_predicate_still_matches_input_json(tmp_path):
    ledger = tmp_path / "l.jsonl"
    _append_write_event(ledger, file_path="pyproject.toml")

    result = CliRunner().invoke(main, ["search", str(ledger), "--command", "build-system"])

    assert result.exit_code == 0
    assert "1 event(s) matched" in result.output
    # Matched on input JSON, but the display still hides that JSON.
    assert "cmd={" not in result.output


def test_timeline_respects_explicit_structured_kind(tmp_path):
    """``tool.kind == "structured"`` suppresses ``cmd=`` even if a command field leaks in."""
    ledger = tmp_path / "l.jsonl"
    append_event(
        ledger,
        build_event(
            "tool.pre",
            "claude-code",
            extra={
                "tool": {
                    "name": "Write",
                    "kind": "structured",
                    "input_full": {"file_path": "pyproject.toml"},
                    "input_summary": '{"file_path": "pyproject.toml"}',
                }
            },
        ),
    )

    result = CliRunner().invoke(main, ["timeline", str(ledger)])

    assert result.exit_code == 0
    assert "tool=Write" in result.output
    assert "path=pyproject.toml" in result.output
    assert "cmd=" not in result.output
