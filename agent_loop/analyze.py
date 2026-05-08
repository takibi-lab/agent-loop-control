"""Analyzers for approval fatigue and related policy improvements."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from .ledger import read_events


def approval_report(path: str) -> List[str]:
    events = read_events(path)
    approvals = [event for event in events if _is_approval_related(event)]
    if not approvals:
        return ["No approval or policy decision events found.", "Assumptions: an empty ledger cannot prove no approvals occurred."]

    low_risk = Counter()
    denied_or_high = []
    rules = Counter()
    missing_policy = 0
    for event in approvals:
        policy = event.get("policy") or {}
        approval = event.get("approval") or {}
        key = _group_key(event)
        if policy.get("rule_id"):
            rules[policy["rule_id"]] += 1
        else:
            missing_policy += 1
        if approval.get("status") == "denied" or policy.get("decision") == "deny" or policy.get("risk") in {"high", "critical"}:
            denied_or_high.append(key)
        elif policy.get("decision") in {"allow", "ask"} and policy.get("risk") in {"low", "unknown"}:
            low_risk[key] += 1

    lines = ["Approval fatigue report"]
    lines.append(f"Total approval/policy events: {len(approvals)}")
    lines.append("Repeated low-risk candidates:")
    for key, count in low_risk.most_common():
        if count > 1:
            lines.append(f"- {key}: {count} occurrences; review for a narrow allow rule.")
    if not any(count > 1 for count in low_risk.values()):
        lines.append("- None found.")
    lines.append("Denied or high-risk actions:")
    lines.extend(f"- {key}" for key in denied_or_high) if denied_or_high else lines.append("- None found.")
    lines.append("Frequent matched rules:")
    lines.extend(f"- {rule}: {count}" for rule, count in rules.most_common()) if rules else lines.append("- None recorded.")
    lines.append(f"Missing policy metadata: {missing_policy}")
    lines.append("Assumptions and blind spots: repeated approvals are grouped by available command prefix, tool, file path, or rule metadata; uncaptured actions cannot be inferred.")
    return lines


def _is_approval_related(event: Dict[str, Any]) -> bool:
    return event.get("event_type") in {"policy.decision", "approval.requested", "approval.resolved"} or "policy" in event or "approval" in event


def _group_key(event: Dict[str, Any]) -> str:
    policy = event.get("policy") or {}
    tool = event.get("tool") or {}
    if policy.get("rule_id"):
        return f"rule:{policy['rule_id']}"
    if tool.get("command"):
        return f"command:{_prefix(tool['command'])}"
    if tool.get("name"):
        return f"tool:{tool['name']}"
    files = event.get("files") or []
    if files:
        return f"path:{files[0].get('path', 'unknown')}"
    return f"event:{event.get('event_type', 'unknown')}"


def _prefix(command: str) -> str:
    return " ".join(command.split()[:3])
