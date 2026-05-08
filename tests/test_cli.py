"""Tests for CLI validation and error reporting."""

from click.testing import CliRunner

from agent_loop.cli import main


def test_policy_check_success_reports_counts(sample_policy_yaml):
    result = CliRunner().invoke(main, ["policy", "check", str(sample_policy_yaml)])
    assert result.exit_code == 0
    assert "Rules: 4" in result.output
    assert "Redaction patterns: 1" in result.output


def test_policy_check_invalid_policy_exits_one(tmp_path):
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
    result = CliRunner().invoke(main, ["policy", "check", str(policy)])
    assert result.exit_code == 1
    assert "invalid" in result.output
    assert "maybe" in result.output


def test_verify_prints_collected_errors(tmp_path):
    ledger = tmp_path / "bad.jsonl"
    ledger.write_text('not-json\n{"event_id":"x"}\n', encoding="utf-8")
    result = CliRunner().invoke(main, ["verify", str(ledger)])
    assert result.exit_code == 1
    assert "ledger integrity check failed" in result.output
    assert "invalid JSON" in result.output
    assert "missing 'hash'" in result.output


def test_verify_success(tmp_path):
    ledger = tmp_path / "empty.jsonl"
    ledger.write_text("", encoding="utf-8")
    result = CliRunner().invoke(main, ["verify", str(ledger)])
    assert result.exit_code == 0
    assert "0 events verified" in result.output
