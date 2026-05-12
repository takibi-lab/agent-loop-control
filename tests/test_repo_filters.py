"""Tests for repository-aware ledger views."""

import json

from click.testing import CliRunner

from agent_loop.cli import main
from agent_loop.ledger import _canonical_bytes, _sha256, append_event, build_event

REPO_APP = "github.com/acme/app"
REPO_LIB = "github.com/acme/lib"


def _append_policy_event(ledger, *, repo_remote: str, command: str, decision: str = "ask") -> dict:
    return append_event(
        ledger,
        build_event(
            "policy.decision",
            "claude-code",
            extra={
                "repo": {
                    "root": f"/work/{repo_remote.rsplit('/', 1)[-1]}",
                    "remote": repo_remote,
                    "branch": "main",
                    "commit": "a" * 40,
                    "dirty": False,
                },
                "tool": {"name": "Bash", "command": command},
                "policy": {
                    "decision": decision,
                    "risk": "low",
                    "rule_id": "test",
                    "rationale": "test fixture",
                },
            },
        ),
    )


def _rewrite_event(ledger, index: int, mutate) -> None:
    lines = ledger.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    mutate(events[index])

    prev_hash = None
    for event in events:
        event["prev_hash"] = prev_hash
        event["hash"] = _sha256(_canonical_bytes(event))
        prev_hash = event["hash"]

    ledger.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def _tamper_event_without_rehashing(ledger, index: int, mutate) -> None:
    lines = ledger.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    mutate(events[index])
    ledger.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def test_timeline_filters_by_repo_remote(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _append_policy_event(ledger, repo_remote=REPO_APP, command="uv run pytest tests/app")
    _append_policy_event(ledger, repo_remote=REPO_LIB, command="uv run pytest tests/lib")

    result = CliRunner().invoke(main, ["timeline", str(ledger), "--repo", REPO_APP])

    assert result.exit_code == 0
    assert "tests/app" in result.output
    assert "tests/lib" not in result.output


def test_search_filters_by_repo_remote_with_other_predicates(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _append_policy_event(ledger, repo_remote=REPO_APP, command="git status --short", decision="ask")
    _append_policy_event(ledger, repo_remote=REPO_APP, command="git push", decision="deny")
    _append_policy_event(ledger, repo_remote=REPO_LIB, command="git status --short", decision="ask")

    result = CliRunner().invoke(
        main,
        ["search", str(ledger), "--repo", REPO_APP, "--decision", "ask"],
    )

    assert result.exit_code == 0
    assert "git status --short" in result.output
    assert "git push" not in result.output
    assert "1 event(s) matched" in result.output


def test_analyze_can_filter_to_one_repo(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _append_policy_event(ledger, repo_remote=REPO_APP, command="git status --short")
    _append_policy_event(ledger, repo_remote=REPO_APP, command="git status --porcelain")
    _append_policy_event(ledger, repo_remote=REPO_LIB, command="uv run pytest")

    result = CliRunner().invoke(main, ["analyze", str(ledger), "--repo", REPO_APP])

    assert result.exit_code == 0
    assert "Total events analyzed:       2" in result.output
    assert "cmd:git status" in result.output
    assert "cmd:uv run" not in result.output


def test_analyze_group_by_repo_keeps_repeated_asks_separate(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _append_policy_event(ledger, repo_remote=REPO_APP, command="git status --short")
    _append_policy_event(ledger, repo_remote=REPO_APP, command="git status --porcelain")
    _append_policy_event(ledger, repo_remote=REPO_LIB, command="git status --short")

    result = CliRunner().invoke(main, ["analyze", str(ledger), "--group-by", "repo"])

    assert result.exit_code == 0
    assert REPO_APP in result.output
    assert REPO_LIB in result.output
    assert "2x" in result.output
    assert "1x" in result.output


def test_repo_filtered_timeline_still_verifies_full_hash_chain(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _append_policy_event(ledger, repo_remote=REPO_APP, command="uv run pytest tests/app")
    _append_policy_event(ledger, repo_remote=REPO_LIB, command="uv run pytest tests/lib")
    _tamper_event_without_rehashing(
        ledger,
        1,
        lambda event: event["tool"].update({"command": "tampered outside selected repo"}),
    )

    result = CliRunner().invoke(main, ["timeline", str(ledger), "--repo", REPO_APP])

    assert result.exit_code == 0
    assert "ledger integrity check failed" in result.output
    assert "tests/app" in result.output
    assert "tampered outside selected repo" not in result.output


def test_repo_filter_matches_root_when_remote_is_missing(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    event = _append_policy_event(ledger, repo_remote=REPO_APP, command="pwd")
    root = "/work/local-only"
    _rewrite_event(
        ledger,
        0,
        lambda updated: updated.update(
            {
                "repo": {
                    "root": root,
                    "branch": event["repo"]["branch"],
                    "commit": event["repo"]["commit"],
                    "dirty": event["repo"]["dirty"],
                }
            }
        ),
    )

    result = CliRunner().invoke(main, ["search", str(ledger), "--repo-root", root])

    assert result.exit_code == 0
    assert "pwd" in result.output
    assert "1 event(s) matched" in result.output
