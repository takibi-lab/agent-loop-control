import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_loop.analyze import approval_report
from agent_loop.diff_snapshot import snapshot
from agent_loop.ledger import append_event
from agent_loop.views import search, timeline


class ViewsAnalyzeDiffCliTests(unittest.TestCase):
    def test_timeline_search_and_analyzer(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            append_event(
                ledger,
                {
                    "event_type": "approval.requested",
                    "tool": {"name": "shell", "command": "git status --short"},
                    "policy": {"decision": "ask", "risk": "low", "rule_id": "allow-readonly-discovery"},
                    "approval": {"status": "approved"},
                    "files": [{"path": "README.md"}],
                },
            )
            append_event(
                ledger,
                {
                    "event_type": "approval.requested",
                    "tool": {"name": "shell", "command": "git status --short"},
                    "policy": {"decision": "ask", "risk": "low", "rule_id": "allow-readonly-discovery"},
                    "approval": {"status": "approved"},
                },
            )
            append_event(
                ledger,
                {
                    "event_type": "approval.resolved",
                    "tool": {"name": "shell", "command": "rm -rf tmp"},
                    "policy": {"decision": "deny", "risk": "critical", "rule_id": "deny-destructive-commands"},
                    "approval": {"status": "denied"},
                },
            )
            self.assertIn("approval.requested", "\n".join(timeline(str(ledger))))
            self.assertIn("README.md", "\n".join(search(str(ledger), file_path="README")))
            self.assertIn("No matching events.", "\n".join(search(str(ledger), command="nope")))
            report = "\n".join(approval_report(str(ledger)))
            self.assertIn("allow-readonly-discovery: 2", report)
            self.assertIn("deny-destructive-commands", report)

    def test_analyzer_empty_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            ledger.write_text("", encoding="utf-8")
            self.assertIn("No approval", approval_report(str(ledger))[0])

    def test_diff_snapshot_clean_dirty_and_no_git(self):
        clean = snapshot(".")
        self.assertEqual(clean["event_type"], "git.diff_snapshot")
        self.assertIn("patch_sha256", clean["diff"])
        with tempfile.TemporaryDirectory() as tmp:
            no_git = Path(tmp)
            with self.assertRaises(RuntimeError):
                snapshot(no_git)

    def test_cli_help_and_policy_check(self):
        help_result = subprocess.run(["python3", "-m", "agent_loop.cli", "--help"], text=True, capture_output=True)
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("verify", help_result.stdout)
        verify_help = subprocess.run(["python3", "-m", "agent_loop.cli", "verify", "--help"], text=True, capture_output=True)
        self.assertEqual(verify_help.returncode, 0)
        policy_help = subprocess.run(["python3", "-m", "agent_loop.cli", "policy", "check", "--help"], text=True, capture_output=True)
        self.assertEqual(policy_help.returncode, 0)


if __name__ == "__main__":
    unittest.main()
