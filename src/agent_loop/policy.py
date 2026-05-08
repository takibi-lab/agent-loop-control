"""Policy parser and action classifier."""

import fnmatch
import re
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_RISK = "unknown"


def load_policy(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def classify_action(
    policy: dict,
    *,
    tool: str | None = None,
    command: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """Return decision/risk/rule_id/rationale for the given action.

    Deny rules take precedence when multiple rules match.
    """
    matches: list[dict] = []

    for rule in policy.get("rules", []):
        if _rule_matches(rule, tool=tool, command=command, path=path):
            matches.append(rule)

    if not matches:
        defaults = policy.get("defaults", {})
        return {
            "decision": defaults.get("decision", "ask"),
            "risk": _DEFAULT_RISK,
            "rule_id": None,
            "rationale": defaults.get("rationale", "No matching rule; default applied."),
        }

    # Deny takes highest precedence, then ask, then allow.
    _precedence = {"deny": 0, "ask": 1, "allow": 2}
    winner = min(matches, key=lambda r: _precedence.get(r.get("decision", "ask"), 1))
    return {
        "decision": winner.get("decision", "ask"),
        "risk": winner.get("risk", _DEFAULT_RISK),
        "rule_id": winner.get("id"),
        "rationale": winner.get("rationale", ""),
    }


def _rule_matches(
    rule: dict,
    *,
    tool: str | None,
    command: str | None,
    path: str | None,
) -> bool:
    match = rule.get("match", {})

    if tool and "tools" in match:
        if tool in match["tools"]:
            return True

    if command and "commands" in match:
        for prefix in match["commands"].get("prefixes", []):
            if command == prefix or command.startswith(prefix + " ") or command.startswith(prefix + "\t"):
                return True

    if path and "paths" in match:
        for glob in match["paths"].get("globs", []):
            if fnmatch.fnmatch(path, glob):
                return True

    return False


def load_redaction_patterns(policy: dict) -> list[dict]:
    """Return compiled redaction patterns from policy config."""
    redaction = policy.get("redaction", {})
    if not redaction.get("enabled", False):
        return []
    result = []
    for p in redaction.get("patterns", []):
        try:
            compiled = re.compile(p["regex"])
            result.append({"name": p["name"], "pattern": compiled, "replacement": p["replacement"]})
        except re.error:
            pass
    return result


def redact_string(value: str, patterns: list[dict]) -> tuple[str, list[str]]:
    """Apply redaction patterns to a string value.

    Returns (redacted_value, list_of_matched_pattern_names).
    """
    matched: list[str] = []
    for p in patterns:
        new_value, count = p["pattern"].subn(p["replacement"], value)
        if count > 0:
            value = new_value
            matched.append(p["name"])
    return value, matched


def redact_event(event: dict, patterns: list[dict]) -> dict:
    """Apply redaction to string fields in an event dict (shallow, selected fields).

    Adds a 'redaction' metadata object to the event.
    """
    if not patterns:
        return event

    _REDACT_FIELDS = ["command", "input_summary"]
    all_matched: list[str] = []

    event = dict(event)

    tool = event.get("tool")
    if isinstance(tool, dict):
        tool = dict(tool)
        for field in _REDACT_FIELDS:
            if isinstance(tool.get(field), str):
                tool[field], matched = redact_string(tool[field], patterns)
                all_matched.extend(matched)
        event["tool"] = tool

    if isinstance(event.get("prompt"), str):
        event["prompt"], matched = redact_string(event["prompt"], patterns)
        all_matched.extend(matched)

    unique_matched = list(dict.fromkeys(all_matched))
    event["redaction"] = {"applied": bool(unique_matched), "patterns": unique_matched}
    return event
