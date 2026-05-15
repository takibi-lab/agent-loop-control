"""Approval fatigue analyzer.

Reads ledger events and summarizes approval patterns, repeated low-risk prompts,
and policy improvement candidates.
"""

from collections import Counter
from pathlib import Path

from agent_loop.ledger_reader import filter_events, load_events
from agent_loop.repo_context import repo_label


def _action_key(event: dict) -> str:
    """Group similar actions for reports.

    Commands are grouped by their first two words, so `git status --short`
    and `git status --porcelain` are treated as the same action category.
    """
    tool = event.get("tool", {})
    if isinstance(tool, dict):
        name = tool.get("name", "")
        cmd = tool.get("command") or tool.get("input_summary") or ""
        if cmd:
            words = cmd.split()
            return "cmd:" + " ".join(words[:2])
        if name:
            return f"tool:{name}"
    return "unknown"


def _is_failure(event: dict) -> bool:
    """Return True when an event represents a failed tool action."""
    if event.get("event_type") == "tool.error":
        return True
    tool = event.get("tool")
    return isinstance(tool, dict) and tool.get("success") is False


def _failure_section(events: list[dict]) -> list[str]:
    """Build the repeated-failure report section as report lines.

    Failures are grouped with `_action_key()` and only actions that failed
    two or more times are reported, ordered by frequency.
    """
    failure_counter: Counter = Counter()
    for e in events:
        if _is_failure(e):
            failure_counter[_action_key(e)] += 1

    repeated = [(key, count) for key, count in failure_counter.most_common() if count >= 2]

    lines = []
    lines.append("REPEATED FAILURE ANALYSIS:")
    if repeated:
        lines.append("  Actions that failed repeatedly (review or fix root cause):")
        for key, count in repeated[:10]:
            lines.append(f"  {count:4d}x  {key}")
    else:
        lines.append("  No repeated failures detected.")
    lines.append("")
    return lines


def _repo_breakdown(events: list[dict]) -> str:
    if not events:
        return "No events in ledger. Nothing to analyze."

    event_counter: Counter = Counter(repo_label(event) for event in events)
    ask_counter: Counter = Counter(
        repo_label(event)
        for event in events
        if isinstance(event.get("policy"), dict) and event["policy"].get("decision") == "ask"
    )
    deny_counter: Counter = Counter(
        repo_label(event)
        for event in events
        if isinstance(event.get("policy"), dict) and event["policy"].get("decision") == "deny"
    )

    lines = []
    lines.append("=" * 60)
    lines.append("APPROVAL ANALYSIS BY REPO")
    lines.append("=" * 60)
    lines.append(f"Total events analyzed:       {len(events)}")
    lines.append("")
    lines.append("REPOSITORIES (by event count):")
    for label, count in event_counter.most_common():
        lines.append(
            f"  {count:4d}x events  {ask_counter[label]:4d} ask  {deny_counter[label]:4d} deny  {label}"
        )
    lines.append("")
    lines.append("BLIND SPOTS AND ASSUMPTIONS:")
    lines.append("  - Events without Git context are grouped by session.cwd when available.")
    lines.append("  - Repository labels prefer repo.remote and fall back to repo.root.")
    return "\n".join(lines)


def analyze_approvals(
    ledger_path: str | Path,
    *,
    repo_filter: dict[str, str] | None = None,
    group_by: str | None = None,
) -> str:
    events = filter_events(load_events(ledger_path), repo_filter=repo_filter)
    if group_by == "repo":
        return _repo_breakdown(events)

    if not events:
        return "No matching events in ledger. Nothing to analyze."

    decision_events = [
        e for e in events
        if isinstance(e.get("policy"), dict) and e["policy"].get("decision")
    ]
    approval_requests = [e for e in events if e.get("event_type") == "approval.requested"]
    approval_resolved = [e for e in events if e.get("event_type") == "approval.resolved"]

    ask_events = [
        e for e in events
        if isinstance(e.get("policy"), dict) and e["policy"].get("decision") == "ask"
    ]
    deny_events = [
        e for e in events
        if isinstance(e.get("policy"), dict) and e["policy"].get("decision") == "deny"
    ]
    allow_events = [
        e for e in events
        if isinstance(e.get("policy"), dict) and e["policy"].get("decision") == "allow"
    ]

    ask_counter: Counter = Counter()
    ask_risk_map: dict[str, str] = {}
    for e in ask_events:
        key = _action_key(e)
        ask_counter[key] += 1
        risk = e.get("policy", {}).get("risk", "unknown")
        ask_risk_map[key] = risk

    deny_counter: Counter = Counter()
    for e in deny_events:
        deny_counter[_action_key(e)] += 1

    lines = []
    lines.append("=" * 60)
    lines.append("APPROVAL FATIGUE ANALYSIS REPORT")
    lines.append("=" * 60)
    lines.append(f"Total events analyzed:       {len(events)}")
    lines.append(f"Actions with policy decision:{len(decision_events):5d}")
    lines.append(f"  ask decisions:             {len(ask_events)}")
    lines.append(f"  deny decisions:            {len(deny_events)}")
    lines.append(f"  allow decisions:           {len(allow_events)}")
    lines.append(f"Approval requests:           {len(approval_requests)}")
    lines.append(f"Approval denials/resolved:   {len(approval_resolved)}")
    lines.append("")

    if ask_counter:
        lines.append("REPEATED ASK ACTIONS (by frequency):")
        for key, count in ask_counter.most_common(10):
            risk = ask_risk_map.get(key, "unknown")
            lines.append(f"  {count:4d}x  [{risk:<8}]  {key}")
        lines.append("")

        candidates = [
            (key, count)
            for key, count in ask_counter.most_common()
            if ask_risk_map.get(key) in ("low", "unknown") and count >= 2
        ]
        if candidates:
            lines.append("POLICY IMPROVEMENT CANDIDATES (low-risk repeated asks):")
            lines.append("  Consider adding allow rules for these actions:")
            for key, count in candidates[:5]:
                lines.append(f"  - {key}  (asked {count} times)")
            lines.append("")

    if deny_counter:
        lines.append("DENIED ACTIONS (high-risk, review before allowing):")
        for key, count in deny_counter.most_common(10):
            lines.append(f"  {count:4d}x  {key}")
        lines.append("")

    lines.extend(_failure_section(events))

    lines.append("BLIND SPOTS AND ASSUMPTIONS:")
    lines.append("  - Only captured hook events are analyzed; bypassed actions are invisible.")
    lines.append("  - Risk levels depend on policy configuration; missing policies default to 'ask'.")
    lines.append("  - Recommendations are advisory; review policy changes before applying.")

    return "\n".join(lines)
