"""Approval fatigue analyzer.

Reads ledger events and summarizes approval patterns, repeated low-risk prompts,
and policy improvement candidates.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any


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


def _action_key(event: dict) -> str:
    tool = event.get("tool", {})
    if isinstance(tool, dict):
        name = tool.get("name", "")
        cmd = tool.get("command") or tool.get("input_summary") or ""
        if name:
            return f"tool:{name}"
        if cmd:
            words = cmd.split()
            return "cmd:" + " ".join(words[:2])
    return "unknown"


def analyze_approvals(ledger_path: str | Path) -> str:
    events = _load_events(ledger_path)
    if not events:
        return "No events in ledger. Nothing to analyze."

    policy_events = [e for e in events if e.get("event_type") == "policy.decision"]
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
    lines.append(f"Policy decisions recorded:   {len(policy_events)}")
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

    lines.append("BLIND SPOTS AND ASSUMPTIONS:")
    lines.append("  - Only captured hook events are analyzed; bypassed actions are invisible.")
    lines.append("  - Risk levels depend on policy configuration; missing policies default to 'ask'.")
    lines.append("  - Recommendations are advisory; review policy changes before applying.")

    return "\n".join(lines)
