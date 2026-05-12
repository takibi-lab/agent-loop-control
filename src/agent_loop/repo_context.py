"""Repository context resolution and filtering helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _run_git(args: list[str], cwd: str | Path) -> tuple[str, int]:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            check=False,
        )
    except (FileNotFoundError, OSError):
        return "", 1
    return result.stdout.strip(), result.returncode


def normalize_path(path: str | Path) -> str:
    """Return a stable absolute path string without requiring the path to exist."""
    return str(Path(path).expanduser().resolve(strict=False))


def normalize_remote_url(remote: str | None) -> str | None:
    """Normalize common Git remote URL spellings for grouping and filtering."""
    if not remote:
        return None

    value = remote.strip()
    if not value:
        return None

    parsed = urlparse(value)
    if parsed.scheme in {"http", "https", "ssh", "git"} and parsed.netloc:
        host = parsed.netloc
        if "@" in host:
            host = host.split("@", 1)[1]
        path = parsed.path.lstrip("/")
        normalized = f"{host}/{path}"
    elif "@" in value and ":" in value.split("@", 1)[1]:
        _, rest = value.split("@", 1)
        host, path = rest.split(":", 1)
        normalized = f"{host}/{path}"
    else:
        normalized = value

    normalized = normalized.rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized or None


def resolve_repo_context(cwd: str | Path | None = ".") -> dict[str, Any] | None:
    """Resolve Git repository metadata from a working directory.

    Returns None when cwd is missing, invalid, or outside a Git work tree.
    """
    if cwd is None:
        return None

    root_out, rc = _run_git(["rev-parse", "--show-toplevel"], cwd)
    if rc != 0 or not root_out:
        return None

    root = normalize_path(root_out)
    branch, branch_rc = _run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], root)
    commit, commit_rc = _run_git(["rev-parse", "HEAD"], root)
    status_out, _ = _run_git(["status", "--porcelain"], root)
    remote, _ = _run_git(["config", "--get", "remote.origin.url"], root)

    repo: dict[str, Any] = {
        "root": root,
        "dirty": bool(status_out),
    }
    normalized_remote = normalize_remote_url(remote)
    if normalized_remote:
        repo["remote"] = normalized_remote
    if branch_rc == 0 and branch:
        repo["branch"] = branch
    if commit_rc == 0 and commit:
        repo["commit"] = commit
    return repo


def build_repo_filter(
    *,
    repo: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, str] | None:
    """Build a repo filter from CLI options.

    --repo-root always filters by normalized root path. --repo first tries to
    resolve a Git checkout path and falls back to normalized remote text.
    """
    if repo and repo_root:
        raise ValueError("Use only one of --repo or --repo-root.")

    if repo_root:
        return {"root": normalize_path(repo_root)}

    if repo:
        context = resolve_repo_context(repo)
        if context and context.get("root"):
            return {"root": str(context["root"])}
        normalized_remote = normalize_remote_url(str(repo))
        if normalized_remote:
            return {"remote": normalized_remote}

    return None


def repo_matches(event: dict[str, Any], repo_filter: dict[str, str] | None) -> bool:
    """Return whether an event matches a repo filter."""
    if not repo_filter:
        return True

    repo = event.get("repo")
    if not isinstance(repo, dict):
        return False

    expected_root = repo_filter.get("root")
    if expected_root:
        root = repo.get("root")
        return isinstance(root, str) and normalize_path(root) == expected_root

    expected_remote = repo_filter.get("remote")
    if expected_remote:
        remote = repo.get("remote")
        return normalize_remote_url(remote if isinstance(remote, str) else None) == expected_remote

    return True


def repo_label(event: dict[str, Any]) -> str:
    """Return a readable stable label for grouping an event by repository."""
    repo = event.get("repo")
    if isinstance(repo, dict):
        remote = repo.get("remote")
        if isinstance(remote, str) and remote:
            return remote
        root = repo.get("root")
        if isinstance(root, str) and root:
            return root

    session = event.get("session")
    if isinstance(session, dict):
        cwd = session.get("cwd")
        if isinstance(cwd, str) and cwd:
            return f"cwd:{normalize_path(cwd)}"

    return "(no repo)"
