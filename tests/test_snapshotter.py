"""Tests for Git diff snapshotter."""

import json
import subprocess
from pathlib import Path

import pytest

from agent_loop.snapshotter import capture_diff, get_repo_state, take_snapshot
from agent_loop.verifier import verify_ledger


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True)
    (path / "readme.txt").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True)


def test_get_repo_state_in_git_dir(tmp_path):
    _init_git_repo(tmp_path)
    state = get_repo_state(tmp_path)
    assert state is not None
    assert state["branch"] == "main"
    assert state["commit"]
    assert state["dirty"] is False


def test_get_repo_state_clean_vs_dirty(tmp_path):
    _init_git_repo(tmp_path)
    state = get_repo_state(tmp_path)
    assert state["dirty"] is False

    (tmp_path / "newfile.txt").write_text("change")
    state = get_repo_state(tmp_path)
    assert state["dirty"] is True


def test_get_repo_state_no_git(tmp_path):
    state = get_repo_state(tmp_path)
    assert state is None


def test_capture_diff_returns_patch_hash(tmp_path):
    _init_git_repo(tmp_path)
    summary, patch_sha256 = capture_diff(tmp_path)
    assert isinstance(patch_sha256, str)
    assert len(patch_sha256) == 64


def test_take_snapshot_emits_diff_snapshot_event(tmp_path):
    _init_git_repo(tmp_path)
    ledger = tmp_path / "l.jsonl"
    event_id = take_snapshot(ledger_path=ledger, repo_root=tmp_path)
    assert event_id

    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "git.diff_snapshot"
    assert events[0]["diff"]["patch_sha256"]


def test_take_snapshot_no_git_emits_blind_spot(tmp_path):
    no_git = tmp_path / "no_git"
    no_git.mkdir()
    ledger = tmp_path / "l.jsonl"
    take_snapshot(ledger_path=ledger, repo_root=no_git)

    events = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert events[0]["event_type"] == "blind_spot.declared"


def test_ledger_integrity_after_snapshot(tmp_path):
    _init_git_repo(tmp_path)
    ledger = tmp_path / "l.jsonl"
    take_snapshot(ledger_path=ledger, repo_root=tmp_path)
    result = verify_ledger(ledger)
    assert result["valid"] is True
