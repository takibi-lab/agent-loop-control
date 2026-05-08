"""Shared test fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def sample_policy_yaml(tmp_path: Path) -> Path:
    policy = tmp_path / "agent-policy.yaml"
    policy.write_text(
        r"""
version: 1
name: test-policy
defaults:
  decision: ask
  rationale: default review
redaction:
  enabled: true
  patterns:
    - name: env-secret
      regex: "(?i)(api[_-]?key|secret|token|password)=(\\S+)"
      replacement: "\\1=[REDACTED]"
rules:
  - id: allow-readonly
    decision: allow
    risk: low
    rationale: readonly
    match:
      tools:
        - Glob
      commands:
        prefixes:
          - git status
  - id: ask-network
    decision: ask
    risk: medium
    rationale: network
    match:
      tools:
        - WebFetch
  - id: deny-sensitive
    decision: deny
    risk: critical
    rationale: secrets
    match:
      paths:
        globs:
          - .env
          - .env.*
  - id: deny-destructive
    decision: deny
    risk: critical
    rationale: destructive
    match:
      commands:
        prefixes:
          - rm -rf
""".lstrip(),
        encoding="utf-8",
    )
    return policy
