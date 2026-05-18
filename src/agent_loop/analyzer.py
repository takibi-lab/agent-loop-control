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
        # Only a real shell command is grouped as `cmd:`. `input_summary` is the
        # raw tool input for non-shell tools (patch text, JSON), so using it as a
        # fallback would surface noise like `cmd:*** Begin` as a policy candidate.
        cmd = tool.get("command") or ""
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
    total_failures = sum(failure_counter.values())

    lines = []
    lines.append("REPEATED FAILURE ANALYSIS:")
    lines.append(f"  Total failed tool actions:   {total_failures}")
    if repeated:
        lines.append("  Actions that failed repeatedly (review or fix root cause):")
        for key, count in repeated[:10]:
            lines.append(f"  {count:4d}x  {key}")
    elif total_failures:
        lines.append("  No action failed two or more times.")
    else:
        lines.append("  No failures detected.")
    lines.append("")
    return lines


# Shell commands whose primary verb duplicates a dedicated Claude Code tool.
_NATIVE_TOOL_SHELL_VERBS = {"cat", "find", "grep", "head", "ls", "rg", "sed", "tail"}


def _bash_primary_verb(command: str) -> str:
    """Return the leading command word, skipping a leading `cd ... &&` prefix.

    `cd /repo && grep foo` reports `grep`; a bare `cd /repo` reports "".
    """
    for segment in command.split("&&"):
        tokens = segment.strip().split()
        if not tokens or tokens[0] == "cd":
            continue
        return tokens[0]
    return ""


def _tool_hygiene_section(events: list[dict]) -> list[str]:
    """Build the Claude Code tool-usage hygiene section as report lines.

    Surfaces habits visible in imported Claude Code transcripts: shell calls
    whose primary verb duplicates a dedicated tool, file-not-found errors,
    edit-before-read violations, and how widely subagents are used. The section
    is omitted when the ledger contains no Claude Code events.
    """
    cc = [e for e in events if (e.get("source") or {}).get("agent") == "claude-code"]
    if not cc:
        return []

    bash_total = 0
    bash_replaceable: Counter = Counter()
    sessions: set[str] = set()
    sessions_with_agent: set[str] = set()
    tool_errors = 0
    file_not_found = 0
    edit_before_read = 0

    for e in cc:
        tool = e.get("tool") if isinstance(e.get("tool"), dict) else {}
        name = tool.get("name", "")
        sid = (e.get("session") or {}).get("session_id")
        if sid:
            sessions.add(sid)
        if e.get("event_type") == "tool.pre":
            if name == "Bash":
                bash_total += 1
                verb = _bash_primary_verb(str(tool.get("command") or ""))
                if verb in _NATIVE_TOOL_SHELL_VERBS:
                    bash_replaceable[verb] += 1
            elif name == "Agent" and sid:
                sessions_with_agent.add(sid)
        if _is_failure(e):
            tool_errors += 1
            err = str(tool.get("error") or "").lower()
            if "has not been read" in err:
                edit_before_read += 1
            elif any(s in err for s in ("no such file", "does not exist", "enoent")):
                file_not_found += 1

    lines = ["CLAUDE CODE TOOL USAGE HYGIENE:"]
    lines.append(f"  Claude Code sessions:        {len(sessions)}")
    replaceable = sum(bash_replaceable.values())
    if bash_total:
        pct = 100 * replaceable / bash_total
        lines.append(
            f"  Bash calls replaceable by a dedicated tool: "
            f"{replaceable}/{bash_total} ({pct:.0f}%)"
        )
        if bash_replaceable:
            by_verb = ", ".join(f"{c} {v}" for v, c in bash_replaceable.most_common(5))
            lines.append(f"    by verb: {by_verb}  -> prefer Glob / Grep / Read")
    if tool_errors:
        fnf_pct = 100 * file_not_found / tool_errors
        lines.append(
            f"  File-not-found errors:       "
            f"{file_not_found}/{tool_errors} tool errors ({fnf_pct:.0f}%)"
        )
    if edit_before_read:
        lines.append(f"  Edit-before-Read violations: {edit_before_read}")
    if sessions:
        agent_pct = 100 * len(sessions_with_agent) / len(sessions)
        lines.append(
            f"  Sessions delegating to subagents: "
            f"{len(sessions_with_agent)}/{len(sessions)} ({agent_pct:.0f}%)"
        )
    lines.append("")
    return lines


def _import_visibility_section(events: list[dict]) -> list[str]:
    """Build the import-visibility report section as report lines.

    Imported transcripts (Codex / Claude Code) carry `blind_spot.declared` events
    for record types the importer cannot normalize, and `recommendation.created`
    events for assistant guidance. This section surfaces both so importer coverage
    gaps are visible instead of silently dropped. It is omitted when the ledger
    contains no imported transcript events.
    """
    blind_spots = [e for e in events if e.get("event_type") == "blind_spot.declared"]
    recommendations = [e for e in events if e.get("event_type") == "recommendation.created"]
    if not blind_spots and not recommendations:
        return []

    reason_counter: Counter = Counter()
    for e in blind_spots:
        spots = e.get("blind_spots")
        if isinstance(spots, list) and spots:
            reason_counter[str(spots[0])] += 1
    unsupported = [
        (reason, count)
        for reason, count in reason_counter.most_common()
        if reason.startswith("Unsupported")
    ]

    lines = ["IMPORT VISIBILITY (imported transcripts):"]
    lines.append(f"  Blind spot events:           {len(blind_spots)}")
    lines.append(f"  Recommendations captured:    {len(recommendations)}")
    if unsupported:
        lines.append("  Top unsupported record types (extend the importer to capture these):")
        for reason, count in unsupported[:5]:
            lines.append(f"  {count:4d}x  {reason}")
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
    lines.extend(_tool_hygiene_section(events))
    lines.extend(_import_visibility_section(events))

    lines.append("BLIND SPOTS AND ASSUMPTIONS:")
    lines.append("  - Only captured hook events are analyzed; bypassed actions are invisible.")
    lines.append("  - Risk levels depend on policy configuration; missing policies default to 'ask'.")
    lines.append("  - Recommendations are advisory; review policy changes before applying.")

    return "\n".join(lines)
