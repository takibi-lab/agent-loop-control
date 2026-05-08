"""Terminal views for ledger timeline and search."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from .ledger import read_events
from .verifier import verify_ledger


def timeline(path: str) -> List[str]:
    warning = _verification_warning(path)
    events = sorted(read_events(path), key=lambda event: (event.get("ts", ""), event.get("event_id", "")))
    lines = [warning] if warning else []
    lines.extend(_summary(event) for event in events)
    return lines or ["No events."]


def search(path: str, event_type: str | None = None, policy_decision: str | None = None, command: str | None = None, file_path: str | None = None) -> List[str]:
    warning = _verification_warning(path)
    lines = [warning] if warning else []
    matches = []
    for event in read_events(path):
        if event_type and event.get("event_type") != event_type:
            continue
        if policy_decision and (event.get("policy") or {}).get("decision") != policy_decision:
            continue
        if command and command not in (event.get("tool") or {}).get("command", ""):
            continue
        if file_path and not any(file_path in item.get("path", "") for item in event.get("files", [])):
            continue
        matches.append(event)
    lines.extend(_summary(event) for event in matches)
    if not matches:
        lines.append("No matching events.")
    return lines


def _verification_warning(path: str) -> str | None:
    result = verify_ledger(path)
    if result.valid:
        return None
    location = f"line {result.line}" if result.line else "ledger"
    return f"WARNING: ledger verification failed at {location}: {result.reason}"


def _summary(event: Dict[str, Any]) -> str:
    tool = event.get("tool") or {}
    policy = event.get("policy") or {}
    files = event.get("files") or []
    parts = [event.get("ts", "?"), event.get("event_type", "?")]
    if tool.get("name"):
        parts.append(f"tool={tool['name']}")
    if tool.get("command"):
        parts.append(f"cmd={tool['command']}")
    if policy.get("decision"):
        parts.append(f"decision={policy['decision']}")
    if files:
        parts.append("paths=" + ",".join(item.get("path", "?") for item in files))
    return " | ".join(parts)
