"""Tests for the approval fatigue analyzer."""

from agent_loop.analyzer import analyze_approvals
from agent_loop.ledger import append_event, build_event

REPO_APP = "github.com/acme/app"
REPO_LIB = "github.com/acme/lib"


def _append_tool_pre(
    ledger,
    *,
    command: str,
    decision: str = "ask",
    risk: str = "low",
    repo_remote: str | None = None,
) -> dict:
    """Append a tool.pre event with an embedded policy decision."""
    extra: dict = {
        "tool": {"name": "Bash", "command": command},
        "policy": {
            "decision": decision,
            "risk": risk,
            "rule_id": "test",
            "rationale": "test fixture",
        },
    }
    if repo_remote is not None:
        extra["repo"] = {
            "root": f"/work/{repo_remote.rsplit('/', 1)[-1]}",
            "remote": repo_remote,
            "branch": "main",
            "commit": "a" * 40,
            "dirty": False,
        }
    return append_event(ledger, build_event("tool.pre", "claude-code", extra=extra))


def _append_tool_error(ledger, *, command: str) -> dict:
    """Append a failed tool action as a tool.error event."""
    return append_event(
        ledger,
        build_event(
            "tool.error",
            "claude-code",
            extra={"tool": {"name": "Bash", "command": command, "success": False}},
        ),
    )


def _append_cc(ledger, event_type: str, *, tool: dict, session_id: str = "s1") -> dict:
    """Append a Claude Code tool event with a given tool dict and session id."""
    return append_event(
        ledger,
        build_event(event_type, "claude-code", session_id=session_id, extra={"tool": tool}),
    )


def _append_blind_spot(ledger, *, reason: str) -> dict:
    """Append a blind_spot.declared event as the importer would."""
    return append_event(
        ledger,
        build_event(
            "blind_spot.declared",
            "codex-cli",
            extra={"blind_spots": [reason, "Hidden model reasoning is not captured."]},
        ),
    )


def _append_recommendation(ledger, *, message: str) -> dict:
    """Append a recommendation.created event as the importer would."""
    return append_event(
        ledger,
        build_event("recommendation.created", "codex-cli", extra={"message": message}),
    )


def test_decision_counts_are_consistent_with_total(tmp_path):
    """allow/ask/deny counts must sum within the policy-decision total."""
    ledger = tmp_path / "ledger.jsonl"
    _append_tool_pre(ledger, command="git status --short", decision="allow")
    _append_tool_pre(ledger, command="uv run pytest", decision="ask")
    _append_tool_pre(ledger, command="rm -rf /tmp/x", decision="deny", risk="critical")

    report = analyze_approvals(ledger)

    assert "Actions with policy decision:    3" in report
    assert "ask decisions:             1" in report
    assert "deny decisions:            1" in report
    assert "allow decisions:           1" in report
    assert "Policy decisions recorded" not in report


def test_low_risk_repeated_asks_become_improvement_candidates(tmp_path):
    """Low-risk asks repeated twice or more surface as policy candidates."""
    ledger = tmp_path / "ledger.jsonl"
    _append_tool_pre(ledger, command="git status --short", decision="ask", risk="low")
    _append_tool_pre(ledger, command="git status --porcelain", decision="ask", risk="low")

    report = analyze_approvals(ledger)

    assert "POLICY IMPROVEMENT CANDIDATES" in report
    assert "cmd:git status  (asked 2 times)" in report


def test_repeated_failures_are_reported(tmp_path):
    """Actions failing twice or more appear in the repeated failure section."""
    ledger = tmp_path / "ledger.jsonl"
    _append_tool_error(ledger, command="uv run pytest tests/a")
    _append_tool_error(ledger, command="uv run pytest tests/b")
    _append_tool_pre(ledger, command="git status", decision="allow")

    report = analyze_approvals(ledger)

    assert "REPEATED FAILURE ANALYSIS:" in report
    assert "2x  cmd:uv run" in report


def test_no_repeated_failures_section_when_failures_are_unique(tmp_path):
    """A single failure should not be flagged as a repeated failure."""
    ledger = tmp_path / "ledger.jsonl"
    _append_tool_error(ledger, command="uv run pytest tests/a")
    _append_tool_pre(ledger, command="git status", decision="allow")

    report = analyze_approvals(ledger)

    assert "REPEATED FAILURE ANALYSIS:" in report
    assert "Total failed tool actions:   1" in report
    assert "No action failed two or more times." in report


def test_tool_hygiene_flags_bash_replaceable_by_native_tools(tmp_path):
    """Bash calls whose primary verb duplicates a dedicated tool are counted."""
    ledger = tmp_path / "ledger.jsonl"
    _append_cc(ledger, "tool.pre", tool={"name": "Bash", "command": "find . -name '*.py'"})
    _append_cc(ledger, "tool.pre", tool={"name": "Bash", "command": "cd /repo && grep foo src"})
    _append_cc(ledger, "tool.pre", tool={"name": "Bash", "command": "git status --short"})

    report = analyze_approvals(ledger)

    assert "CLAUDE CODE TOOL USAGE HYGIENE:" in report
    assert "Bash calls replaceable by a dedicated tool: 2/3 (67%)" in report
    assert "prefer Glob / Grep / Read" in report


def test_tool_hygiene_reports_errors_and_subagent_use(tmp_path):
    """File-not-found, edit-before-read, and subagent metrics are reported."""
    ledger = tmp_path / "ledger.jsonl"
    _append_cc(ledger, "tool.pre", tool={"name": "Agent"}, session_id="s1")
    _append_cc(
        ledger,
        "tool.error",
        tool={"name": "Read", "success": False, "error": "Error: no such file or directory"},
        session_id="s1",
    )
    _append_cc(
        ledger,
        "tool.error",
        tool={"name": "Edit", "success": False, "error": "File has not been read yet."},
        session_id="s2",
    )

    report = analyze_approvals(ledger)

    assert "Claude Code sessions:        2" in report
    assert "File-not-found errors:       1/2 tool errors (50%)" in report
    assert "Edit-before-Read violations: 1" in report
    assert "Sessions delegating to subagents: 1/2 (50%)" in report


def test_tool_hygiene_section_absent_without_claude_code_events(tmp_path):
    """A ledger with no Claude Code events has no tool-hygiene section."""
    ledger = tmp_path / "ledger.jsonl"
    _append_blind_spot(ledger, reason="Unsupported Codex record type: 'error'")

    report = analyze_approvals(ledger)

    assert "CLAUDE CODE TOOL USAGE HYGIENE" not in report


def test_import_visibility_reports_blind_spots_and_recommendations(tmp_path):
    """Imported blind spots and recommendations surface in their own section."""
    ledger = tmp_path / "ledger.jsonl"
    _append_blind_spot(ledger, reason="Unsupported Codex record type: 'exec_command_end'")
    _append_blind_spot(ledger, reason="Unsupported Codex record type: 'exec_command_end'")
    _append_blind_spot(ledger, reason="Unsupported Claude Code record type: 'attachment'")
    _append_recommendation(ledger, message="Consider adding a regression test.")

    report = analyze_approvals(ledger)

    assert "IMPORT VISIBILITY (imported transcripts):" in report
    assert "Blind spot events:           3" in report
    assert "Recommendations captured:    1" in report
    assert "2x  Unsupported Codex record type: 'exec_command_end'" in report


def test_import_visibility_section_absent_without_imported_events(tmp_path):
    """A ledger of only hook events has no import-visibility section."""
    ledger = tmp_path / "ledger.jsonl"
    _append_tool_pre(ledger, command="git status", decision="allow")

    report = analyze_approvals(ledger)

    assert "IMPORT VISIBILITY" not in report


def test_empty_ledger_returns_no_matching_events(tmp_path):
    """An empty ledger yields a clear no-events message."""
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("", encoding="utf-8")

    report = analyze_approvals(ledger)

    assert report == "No matching events in ledger. Nothing to analyze."


def test_group_by_repo_breaks_down_per_repository(tmp_path):
    """group_by='repo' routes through the per-repo breakdown view."""
    ledger = tmp_path / "ledger.jsonl"
    _append_tool_pre(ledger, command="git status", decision="ask", repo_remote=REPO_APP)
    _append_tool_pre(ledger, command="git diff", decision="deny", repo_remote=REPO_APP)
    _append_tool_pre(ledger, command="git log", decision="ask", repo_remote=REPO_LIB)

    report = analyze_approvals(ledger, group_by="repo")

    assert "APPROVAL ANALYSIS BY REPO" in report
    assert REPO_APP in report
    assert REPO_LIB in report
    assert "Total events analyzed:       3" in report


def test_group_by_repo_on_empty_ledger(tmp_path):
    """The repo breakdown handles an empty ledger gracefully."""
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("", encoding="utf-8")

    report = analyze_approvals(ledger, group_by="repo")

    assert report == "No events in ledger. Nothing to analyze."
