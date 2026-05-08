"""Tests for policy parser, validation, classifier, and redaction."""

import re
from pathlib import Path

import pytest

from agent_loop.policy import (
    PolicyValidationError,
    classify_action,
    load_policy,
    load_redaction_patterns,
    redact_event,
    redact_string,
    validate_policy,
)

SAMPLE_POLICY_PATH = Path(__file__).parent.parent / "examples" / "agent-policy.yaml"


def test_load_sample_policy_documentation_contract():
    pol = load_policy(SAMPLE_POLICY_PATH)
    assert pol["version"] == 1
    assert pol["name"]
    assert len(pol["rules"]) > 0


def test_sample_policy_actually_redacts():
    pol = load_policy(SAMPLE_POLICY_PATH)
    patterns = load_redaction_patterns(pol)
    redacted, matched = redact_string("api_key=hunter2", patterns)
    assert redacted == "api_key=[REDACTED]"
    assert matched == ["env-secret"]


def test_tool_match_allow(sample_policy_yaml):
    policy = load_policy(sample_policy_yaml)
    result = classify_action(policy, tool="Glob")
    assert result["decision"] == "allow"
    assert result["rule_id"] == "allow-readonly"


def test_command_prefix_match(sample_policy_yaml):
    policy = load_policy(sample_policy_yaml)
    result = classify_action(policy, command="git status --short")
    assert result["decision"] == "allow"


def test_path_glob_match_deny(sample_policy_yaml):
    policy = load_policy(sample_policy_yaml)
    result = classify_action(policy, path=".env")
    assert result["decision"] == "deny"
    assert result["risk"] == "critical"


def test_default_when_no_match(sample_policy_yaml):
    policy = load_policy(sample_policy_yaml)
    result = classify_action(policy, tool="UnknownTool")
    assert result["decision"] == "ask"
    assert result["rule_id"] is None


def test_deny_takes_precedence_over_allow(sample_policy_yaml):
    policy = load_policy(sample_policy_yaml)
    result = classify_action(policy, tool="Glob", command="rm -rf /")
    assert result["decision"] == "deny"
    assert result["rule_id"] == "deny-destructive"


def test_rule_match_uses_or_semantics(sample_policy_yaml):
    policy = load_policy(sample_policy_yaml)
    result = classify_action(policy, command="git status --porcelain")
    assert result["decision"] == "allow"
    assert result["rule_id"] == "allow-readonly"


def test_load_policy_rejects_missing_version(tmp_path):
    policy = tmp_path / "bad.yaml"
    policy.write_text(
        """
name: bad
defaults:
  decision: ask
rules: []
""".lstrip(),
        encoding="utf-8",
    )
    with pytest.raises(PolicyValidationError) as exc:
        load_policy(policy)
    assert "version" in str(exc.value)


def test_load_policy_rejects_invalid_decision(tmp_path):
    policy = tmp_path / "bad.yaml"
    policy.write_text(
        """
version: 1
name: bad
defaults:
  decision: maybe
rules: []
""".lstrip(),
        encoding="utf-8",
    )
    with pytest.raises(PolicyValidationError) as exc:
        load_policy(policy)
    assert "maybe" in str(exc.value)


def test_load_policy_rejects_invalid_yaml(tmp_path):
    policy = tmp_path / "bad.yaml"
    policy.write_text('version: "unterminated\n', encoding="utf-8")
    with pytest.raises(PolicyValidationError) as exc:
        load_policy(policy)
    assert "<yaml>" in str(exc.value)


def test_validate_policy_returns_errors_list():
    errors = validate_policy({"name": "bad", "defaults": {"decision": "ask"}, "rules": []})
    assert errors
    assert any("version" in error for error in errors)


def test_load_policy_rejects_malformed_redaction_regex(tmp_path):
    policy = tmp_path / "bad.yaml"
    policy.write_text(
        """
version: 1
name: bad
defaults:
  decision: ask
redaction:
  enabled: true
  patterns:
    - name: broken
      regex: "["
      replacement: "[REDACTED]"
rules: []
""".lstrip(),
        encoding="utf-8",
    )
    with pytest.raises(PolicyValidationError) as exc:
        load_policy(policy)
    assert "invalid regex" in str(exc.value)


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


def test_load_redaction_patterns_from_policy(sample_policy_yaml):
    pol = load_policy(sample_policy_yaml)
    patterns = load_redaction_patterns(pol)
    assert len(patterns) > 0
    assert all("name" in p and "pattern" in p for p in patterns)


def test_redact_event_applies_to_tool_command():
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


def test_redact_event_walks_nested_tool_input():
    patterns = [
        {
            "name": "env-secret",
            "pattern": re.compile(r"(?i)(api[_-]?key|secret|token|password)=(\S+)"),
            "replacement": r"\1=[REDACTED]",
        }
    ]
    event = {
        "event_id": "api_key=keep-metadata",
        "hash": "api_key=keep-hash",
        "prev_hash": "api_key=keep-prev",
        "ts": "api_key=keep-ts",
        "schema_version": 1,
        "event_type": "tool.pre",
        "tool": {
            "name": "Edit",
            "input_full": {
                "file_path": "/tmp/x",
                "new_string": "api_key=supersecret",
                "edits": [{"replacement": "token=secret-token"}],
            },
        },
    }
    redacted = redact_event(event, patterns)
    assert redacted["tool"]["input_full"]["new_string"] == "api_key=[REDACTED]"
    assert redacted["tool"]["input_full"]["edits"][0]["replacement"] == "token=[REDACTED]"
    assert redacted["event_id"] == "api_key=keep-metadata"
    assert redacted["hash"] == "api_key=keep-hash"
    assert redacted["prev_hash"] == "api_key=keep-prev"
    assert redacted["ts"] == "api_key=keep-ts"


def test_redact_event_no_match():
    patterns = [{"name": "token", "pattern": re.compile(r"token=\S+"), "replacement": "token=[REDACTED]"}]
    event = {"event_type": "session.start", "tool": {"name": "Glob", "command": "*.py"}}
    redacted = redact_event(event, patterns)
    assert redacted["redaction"]["applied"] is False
