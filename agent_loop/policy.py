"""Policy parser and deterministic classifier."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .yaml_loader import load_yaml_file


RANK = {"allow": 1, "ask": 2, "deny": 3}


@dataclass
class PolicyDecision:
    decision: str
    risk: str
    rule_id: Optional[str]
    rationale: str

    def as_event_policy(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "decision": self.decision,
            "risk": self.risk,
            "rationale": self.rationale,
        }
        if self.rule_id:
            data["rule_id"] = self.rule_id
        return data


def load_policy(path: str | Path) -> Dict[str, Any]:
    return load_yaml_file(str(path))


def classify(policy: Dict[str, Any], tool: str | None = None, command: str | None = None, paths: Iterable[str] = ()) -> PolicyDecision:
    matches: List[Dict[str, Any]] = []
    for rule in policy.get("rules", []):
        if _rule_matches(rule, tool, command, paths):
            matches.append(rule)

    if not matches:
        defaults = policy.get("defaults", {})
        return PolicyDecision(defaults.get("decision", "ask"), "unknown", None, defaults.get("rationale", "No rule matched."))

    matches.sort(key=lambda rule: RANK.get(rule.get("decision", "ask"), 2), reverse=True)
    rule = matches[0]
    return PolicyDecision(rule.get("decision", "ask"), rule.get("risk", "unknown"), rule.get("id"), rule.get("rationale", "Matched policy rule."))


def _rule_matches(rule: Dict[str, Any], tool: str | None, command: str | None, paths: Iterable[str]) -> bool:
    match = rule.get("match", {})
    checks = []
    tools = match.get("tools") or []
    if tools:
        checks.append(tool in tools)
    prefixes = (match.get("commands") or {}).get("prefixes") or []
    if prefixes:
        checks.append(any((command or "").startswith(prefix) for prefix in prefixes))
    globs = (match.get("paths") or {}).get("globs") or []
    path_list = list(paths)
    if globs:
        checks.append(any(fnmatch(path, glob) for path in path_list for glob in globs))
    return any(checks)
