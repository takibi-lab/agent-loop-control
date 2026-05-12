"""Shared JSONL ledger reading helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_loop.repo_context import repo_matches


def load_events(ledger_path: str | Path) -> list[dict[str, Any]]:
    """Load valid JSON object events from a ledger JSONL file."""
    p = Path(ledger_path)
    if not p.exists():
        return []

    events: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def filter_events(
    events: list[dict[str, Any]],
    *,
    repo_filter: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Filter ledger events by optional repo metadata."""
    if not repo_filter:
        return list(events)
    return [event for event in events if repo_matches(event, repo_filter)]
