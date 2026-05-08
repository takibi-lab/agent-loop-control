"""Git diff snapshotter."""

from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Optional

from .ledger import append_event


def _git(args: list[str], cwd: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), text=True, capture_output=True)


def snapshot(repo_path: str | Path = ".", ledger_path: Optional[str | Path] = None) -> Dict[str, Any]:
    root_proc = _git(["rev-parse", "--show-toplevel"], repo_path)
    if root_proc.returncode != 0:
        raise RuntimeError("not a git repository")
    root = Path(root_proc.stdout.strip())
    branch = _git(["branch", "--show-current"], root).stdout.strip() or "HEAD"
    commit = _git(["rev-parse", "HEAD"], root).stdout.strip()
    status = _git(["status", "--short"], root).stdout
    diff_summary = _git(["diff", "--stat"], root).stdout.strip()
    patch = _git(["diff"], root).stdout
    patch_sha256 = sha256(patch.encode("utf-8")).hexdigest()
    event = {
        "source": {"agent": "agent-loop", "collector": "git-diff-snapshot"},
        "repo": {"root": str(root), "branch": branch, "commit": commit, "dirty": bool(status.strip())},
        "event_type": "git.diff_snapshot",
        "diff": {"patch_sha256": patch_sha256, "summary": diff_summary},
        "blind_spots": ["Ignored and untracked file content is not captured by default."],
    }
    if ledger_path:
        return append_event(ledger_path, event)
    return event
