"""Policy parser and action classifier."""

import fnmatch
import re
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from yaml import YAMLError

_DEFAULT_RISK = "unknown"
_METADATA_KEYS = {"hash", "prev_hash", "event_id", "ts", "schema_version"}


class PolicyValidationError(ValueError):
    """Raised when a policy file is invalid."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def _schema_candidates() -> list[Path]:
    current = Path(__file__).resolve()
    return [
        current.parents[2] / "schemas" / "agent-policy.schema.json",
        current.parents[1] / "schemas" / "agent-policy.schema.json",
        Path.cwd() / "schemas" / "agent-policy.schema.json",
    ]


def _schema_path() -> Path:
    candidates = _schema_candidates()
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _load_policy_schema() -> dict:
    try:
        schema = resources.files("agent_loop").joinpath("schemas/agent-policy.schema.json")
        if schema.is_file():
            with schema.open(encoding="utf-8") as f:
                return yaml.safe_load(f)
    except (FileNotFoundError, ModuleNotFoundError):
        pass

    schema_path = _schema_path()
    with schema_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_policy(policy: dict) -> list[str]:
    """Return validation errors for a parsed policy dict."""
    errors: list[str] = []
    schema = _load_policy_schema()

    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(policy), key=lambda e: list(e.path)):
        path = ".".join(str(part) for part in error.path) or "<root>"
        errors.append(f"{path}: {error.message}")

    rules = policy.get("rules", []) if isinstance(policy, dict) else []
    if isinstance(rules, list):
        for rule_index, rule in enumerate(rules):
            match = rule.get("match", {}) if isinstance(rule, dict) else {}
            commands = match.get("commands", {}) if isinstance(match, dict) else {}
            prefixes = commands.get("prefixes", []) if isinstance(commands, dict) else []
            for prefix_index, prefix in enumerate(prefixes):
                if isinstance(prefix, str) and prefix.strip() == "":
                    errors.append(
                        f"rules[{rule_index}].match.commands.prefixes[{prefix_index}]: "
                        "empty command prefixes are not allowed"
                    )

    redaction = policy.get("redaction", {}) if isinstance(policy, dict) else {}
    if isinstance(redaction, dict):
        for index, pattern in enumerate(redaction.get("patterns", []) or []):
            name = pattern.get("name", f"pattern[{index}]") if isinstance(pattern, dict) else f"pattern[{index}]"
            regex = pattern.get("regex") if isinstance(pattern, dict) else None
            if isinstance(regex, str):
                try:
                    re.compile(regex)
                except re.error as exc:
                    errors.append(f"redaction.patterns[{index}] {name!r}: invalid regex: {exc}")

    return errors


def load_policy(path: str | Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            policy = yaml.safe_load(f)
    except YAMLError as exc:
        raise PolicyValidationError([f"<yaml>: {exc}"]) from exc
    if not isinstance(policy, dict):
        raise PolicyValidationError(["<root>: policy must be a mapping"])
    errors = validate_policy(policy)
    if errors:
        raise PolicyValidationError(errors)
    return policy


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
    """Return True if any matcher in the rule matches the action.

    Within one rule, tools, command prefixes, and path globs use OR semantics.
    """
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
    errors: list[str] = []
    for index, p in enumerate(redaction.get("patterns", [])):
        try:
            compiled = re.compile(p["regex"])
            result.append({"name": p["name"], "pattern": compiled, "replacement": p["replacement"]})
        except re.error as exc:
            errors.append(f"redaction.patterns[{index}] {p.get('name', index)!r}: invalid regex: {exc}")
    if errors:
        raise PolicyValidationError(errors)
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


def _redact_value(value: Any, patterns: list[dict], matched: list[str], *, key: str | None = None) -> Any:
    if key in _METADATA_KEYS:
        return value
    if isinstance(value, str):
        redacted, names = redact_string(value, patterns)
        matched.extend(names)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item, patterns, matched) for item in value]
    if isinstance(value, dict):
        return {k: _redact_value(v, patterns, matched, key=str(k)) for k, v in value.items()}
    return value


def redact_event(event: dict, patterns: list[dict]) -> dict:
    """Apply redaction recursively to string values in an event dict.

    Event identity and hash-chain metadata keys are preserved.
    """
    if not patterns:
        return event

    all_matched: list[str] = []
    redacted = _redact_value(event, patterns, all_matched)
    unique_matched = list(dict.fromkeys(all_matched))
    redacted["redaction"] = {"applied": bool(unique_matched), "patterns": unique_matched}
    return redacted
