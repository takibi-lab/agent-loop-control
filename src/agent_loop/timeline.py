"""Timeline and search CLI views for the ledger."""

import json
from pathlib import Path

import click

from agent_loop.verifier import verify_ledger


def _load_events(ledger_path: str | Path) -> list[dict]:
    p = Path(ledger_path)
    if not p.exists():
        return []
    events = []
    with p.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                try:
                    events.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
    return events


def _summarize(event: dict) -> str:
    etype = event.get("event_type", "unknown")
    ts = event.get("ts", "")[:19].replace("T", " ")

    parts = [f"{ts}  {etype:<25}"]

    tool = event.get("tool", {})
    if isinstance(tool, dict):
        name = tool.get("name", "")
        cmd = tool.get("command") or tool.get("input_summary", "")
        if name:
            parts.append(f"tool={name}")
        if cmd:
            parts.append(f"cmd={cmd[:60]}")

    policy = event.get("policy", {})
    if isinstance(policy, dict) and policy.get("decision"):
        parts.append(f"[{policy['decision']}]")

    session = event.get("session", {})
    if isinstance(session, dict) and session.get("session_id"):
        parts.append(f"sess={session['session_id'][:8]}")

    return "  ".join(parts)


def print_timeline(ledger_path: str | Path, *, limit: int = 50) -> None:
    result = verify_ledger(ledger_path)
    if not result["valid"]:
        click.echo(f"WARNING: ledger integrity check failed: {result['reason']}", err=True)

    events = _load_events(ledger_path)
    if not events:
        click.echo("(no events)")
        return

    for event in events[-limit:]:
        click.echo(_summarize(event))

    total = len(events)
    if total > limit:
        click.echo(f"... ({total - limit} earlier events not shown; use --limit to show more)")


def print_search(
    ledger_path: str | Path,
    *,
    event_type: str | None = None,
    decision: str | None = None,
    command: str | None = None,
    file_path: str | None = None,
) -> None:
    result = verify_ledger(ledger_path)
    if not result["valid"]:
        click.echo(f"WARNING: ledger integrity check failed: {result['reason']}", err=True)

    events = _load_events(ledger_path)
    matched = []

    for event in events:
        if event_type and event.get("event_type") != event_type:
            continue
        if decision:
            policy = event.get("policy", {})
            if not isinstance(policy, dict) or policy.get("decision") != decision:
                continue
        if command:
            tool = event.get("tool", {})
            cmd_val = ""
            if isinstance(tool, dict):
                cmd_val = tool.get("command") or tool.get("input_summary") or ""
            if command.lower() not in cmd_val.lower():
                continue
        if file_path:
            files = event.get("files", [])
            if not any(file_path.lower() in (f.get("path") or "").lower() for f in files):
                continue
        matched.append(event)

    if not matched:
        click.echo("(no matching events)")
        return

    for event in matched:
        click.echo(_summarize(event))
    click.echo(f"\n{len(matched)} event(s) matched.")
