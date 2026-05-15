"""Tests for repository context attached to ledger events."""

import json
import subprocess
from pathlib import Path

from agent_loop.collector import collect_hook_event
from agent_loop.repo_context import resolve_repo_context


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def _init_git_repo(path: Path, *, remote: str | None = None) -> str:
    _run_git(path, "init", "-b", "main")
    _run_git(path, "config", "user.email", "test@test.com")
    _run_git(path, "config", "user.name", "Test")
    (path / "readme.md").write_text("hello\n", encoding="utf-8")
    _run_git(path, "add", "readme.md")
    _run_git(path, "commit", "-m", "init")
    if remote:
        _run_git(path, "remote", "add", "origin", remote)
    return _run_git(path, "rev-parse", "HEAD")


def test_resolve_repo_context_from_nested_git_dir_normalizes_remote(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    head = _init_git_repo(repo, remote="git@github.com:Acme/Widget.git")
    nested = repo / "src" / "package"
    nested.mkdir(parents=True)

    context = resolve_repo_context(nested)

    assert context == {
        "root": str(repo),
        "remote": "github.com/Acme/Widget",
        "branch": "main",
        "commit": head,
        "dirty": False,
    }


def test_resolve_repo_context_marks_dirty_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    (repo / "readme.md").write_text("changed\n", encoding="utf-8")

    context = resolve_repo_context(repo)

    assert context is not None
    assert context["dirty"] is True


def test_resolve_repo_context_outside_git_returns_none(tmp_path):
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()

    assert resolve_repo_context(not_a_repo) is None


def test_collect_hook_event_attaches_optional_repo_context_from_cwd(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    head = _init_git_repo(repo, remote="https://github.com/acme/widget.git")
    ledger = tmp_path / "ledger.jsonl"

    collect_hook_event(
        json.dumps(
            {
                "hook_type": "PreToolUse",
                "session_id": "s1",
                "cwd": str(repo),
                "tool_name": "Bash",
                "tool_input": {"command": "git status --short"},
            }
        ),
        ledger_path=ledger,
    )

    event = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert event["repo"] == {
        "root": str(repo),
        "remote": "github.com/acme/widget",
        "branch": "main",
        "commit": head,
        "dirty": False,
    }


def test_collect_hook_event_omits_repo_context_when_cwd_is_outside_git(tmp_path):
    cwd = tmp_path / "plain"
    cwd.mkdir()
    ledger = tmp_path / "ledger.jsonl"

    collect_hook_event(
        json.dumps(
            {
                "hook_type": "SessionStart",
                "session_id": "s1",
                "cwd": str(cwd),
            }
        ),
        ledger_path=ledger,
    )

    event = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert "repo" not in event
