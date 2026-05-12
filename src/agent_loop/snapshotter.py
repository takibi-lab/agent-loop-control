"""Git diff snapshotter.

Captures repository state and HEAD-relative diff, computes patch_sha256,
and emits a git.diff_snapshot ledger event.
"""

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from agent_loop.ledger import append_event, build_event, new_event_id
from agent_loop.repo_context import resolve_repo_context


def _run(args: list[str], cwd: str) -> tuple[str, int]:
    result = subprocess.run(args, capture_output=True, text=True, cwd=cwd, check=False)
    return result.stdout.strip(), result.returncode


def get_repo_state(repo_root: str | Path = ".") -> dict[str, Any] | None:
    """Return repo metadata dict, or None if not a git repo."""
    return resolve_repo_context(repo_root)


def capture_diff(repo_root: str | Path = ".") -> tuple[str, str]:
    """Return (diff_summary, patch_sha256) for staged and unstaged tracked changes."""
    root = str(repo_root)
    diff_out, _ = _run(["git", "diff", "HEAD", "--stat"], root)
    patch_out, _ = _run(["git", "diff", "HEAD", "--binary"], root)

    patch_sha256 = hashlib.sha256(patch_out.encode()).hexdigest()
    return diff_out, patch_sha256


def take_snapshot(
    *,
    ledger_path: str | Path = "agent-ledger.jsonl",
    repo_root: str | Path = ".",
    session_id: str | None = None,
) -> str:
    """Capture git state and append a git.diff_snapshot event. Returns event_id."""
    snapshot_id = new_event_id()

    repo_state = get_repo_state(repo_root)
    if repo_state is None:
        event = build_event(
            "blind_spot.declared",
            "agent-loop",
            session_id=session_id,
            extra={
                "blind_spots": [
                    f"No git repository found at {repo_root}; diff snapshot skipped."
                ]
            },
        )
        appended = append_event(ledger_path, event)
        return appended["event_id"]

    diff_summary, patch_sha256 = capture_diff(repo_root)

    extra: dict[str, Any] = {
        "repo": repo_state,
        "diff": {
            "snapshot_id": snapshot_id,
            "patch_sha256": patch_sha256,
            "summary": diff_summary or "(no changes)",
        },
    }

    event = build_event(
        "git.diff_snapshot",
        "agent-loop",
        session_id=session_id,
        extra=extra,
    )
    appended = append_event(ledger_path, event)
    return appended["event_id"]
