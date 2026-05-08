"""Tests for policy parser and classifier."""

import re
import tempfile
from pathlib import Path

import pytest
import yaml

from agent_loop.policy import (
    classify_action,
    load_policy,
    load_redaction_patterns,
    redact_event,
    redact_string,
)

SAMPLE_POLICY_PATH = Path(__file__).parent.parent / "examples" / "agent-policy.yaml"


def test_load_sample_policy():
    pol = load_policy(SAMPLE_POLICY_PATH)
    assert pol["version"] == 1
    assert pol["name"]
    assert len(pol["rules"]) > 0


def test_tool_match_allow(tmp_path):
    policy = {
        "defaults": {"decision": "ask"},
        "rules": [{"id": "r1", "decision": "allow", "risk": "low", "match": {"tools": ["Glob", "LS"]}}],
    }
    result = classify_action(policy, tool="Glob")
    assert result["decision"] == "allow"
    assert result["rule_id"] == "r1"


def test_command_prefix_match(tmp_path):
    policy = {
        "defaults": {"decision": "ask"},
        "rules": [{"id": "r2", "decision": "allow", "risk": "low", "match": {"commands": {"prefixes": ["git status"]}}}],
    }
    result = classify_action(policy, command="git status --short")
    assert result["decision"] == "allow"


def test_path_glob_match_deny(tmp_path):
    policy = {
        "defaults": {"decision": "ask"},
        "rules": [{"id": "r3", "decision": "deny", "risk": "critical", "match": {"paths": {"globs": [".env", ".env.*"]}}}],
    }
    result = classify_action(policy, path=".env")
    assert result["decision"] == "deny"
    assert result["risk"] == "critical"


def test_default_when_no_match():
    policy = {"defaults": {"decision": "ask", "rationale": "default"}, "rules": []}
    result = classify_action(policy, tool="UnknownTool")
    assert result["decision"] == "ask"
    assert result["rule_id"] is None


def test_deny_takes_precedence_over_allow():
    policy = {
        "defaults": {"decision": "ask"},
        "rules": [
            {"id": "allow-r", "decision": "allow", "risk": "low", "match": {"tools": ["Bash"]}},
            {"id": "deny-r", "decision": "deny", "risk": "critical", "match": {"commands": {"prefixes": ["rm -rf"]}}},
        ],
    }
    result = classify_action(policy, tool="Bash", command="rm -rf /")
    assert result["decision"] == "deny"
    assert result["rule_id"] == "deny-r"


def test_classify_sample_policy_allow_readonly():
    pol = load_policy(SAMPLE_POLICY_PATH)
    result = classify_action(pol, tool="Glob")
    assert result["decision"] == "allow"


def test_classify_sample_policy_deny_sensitive_path():
    pol = load_policy(SAMPLE_POLICY_PATH)
    result = classify_action(pol, path=".env")
    assert result["decision"] == "deny"


def test_redact_string_applies_pattern():
    patterns = [
        {"name": "api-key", "pattern": re.compile(r"(?i)(api_key)=(\S+)"), "replacement": r"\1=[REDACTED]"}
    ]
    redacted, matched = redact_string("api_key=supersecret123", patterns)
    assert "supersecret123" not in redacted
    assert "[REDACTED]" in redacted
    assert "api-key" in matched


def test_redact_string_no_match():
    patterns = [
        {"name": "api-key", "pattern": re.compile(r"api_key=(\S+)"), "replacement": "api_key=[REDACTED]"}
    ]
    redacted, matched = redact_string("nothing sensitive here", patterns)
    assert redacted == "nothing sensitive here"
    assert matched == []


def test_redact_string_multiple_patterns():
    patterns = [
        {"name": "p1", "pattern": re.compile(r"SECRET"), "replacement": "[S]"},
        {"name": "p2", "pattern": re.compile(r"TOKEN"), "replacement": "[T]"},
    ]
    redacted, matched = redact_string("SECRET TOKEN here", patterns)
    assert "SECRET" not in redacted
    assert "TOKEN" not in redacted
    assert set(matched) == {"p1", "p2"}


def test_load_redaction_patterns_from_policy():
    pol = load_policy(SAMPLE_POLICY_PATH)
    patterns = load_redaction_patterns(pol)
    assert len(patterns) > 0
    assert all("name" in p and "pattern" in p for p in patterns)


def test_redact_event_applies_to_tool_command():
    import re

    patterns = [
        {"name": "token", "pattern": re.compile(r"token=\S+"), "replacement": "token=[REDACTED]"}
    ]
    event = {
        "event_type": "tool.pre",
        "tool": {"name": "Bash", "command": "curl -H token=abc123 https://api.example.com"},
    }
    redacted = redact_event(event, patterns)
    assert "abc123" not in redacted["tool"]["command"]
    assert redacted["redaction"]["applied"] is True
    assert "token" in redacted["redaction"]["patterns"]


def test_redact_event_no_match():
    import re

    patterns = [{"name": "token", "pattern": re.compile(r"token=\S+"), "replacement": "token=[REDACTED]"}]
    event = {"event_type": "session.start", "tool": {"name": "Glob", "command": "*.py"}}
    redacted = redact_event(event, patterns)
    assert redacted["redaction"]["applied"] is False
