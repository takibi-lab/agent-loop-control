import tempfile
import unittest
from pathlib import Path

from agent_loop.collectors.claude import normalize_hook
from agent_loop.importers.codex import import_jsonl, normalize_record
from agent_loop.ledger import read_events
from agent_loop.policy import load_policy


class CollectorImporterTests(unittest.TestCase):
    def test_claude_supported_and_unknown_events(self):
        policy = load_policy("examples/agent-policy.yaml")
        event = normalize_hook(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "s1",
                "tool_name": "Bash",
                "tool_input": {"command": "git status --short", "path": "README.md"},
            },
            policy,
        )
        self.assertEqual(event["event_type"], "tool.pre")
        self.assertEqual(event["policy"]["decision"], "allow")

        unknown = normalize_hook({"hook_event_name": "NewHook"}, policy)
        self.assertEqual(unknown["event_type"], "blind_spot.declared")
        self.assertIn("Unsupported", unknown["blind_spots"][0])

    def test_codex_supported_unsupported_and_malformed_jsonl(self):
        self.assertEqual(normalize_record({"type": "tool_call", "tool_name": "shell", "command": "ls"})["event_type"], "tool.pre")
        self.assertEqual(normalize_record({"type": "message"})["event_type"], "blind_spot.declared")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "session.jsonl"
            ledger = Path(tmp) / "ledger.jsonl"
            source.write_text('{"type":"tool_call","command":"ls"}\n{bad json}\n', encoding="utf-8")
            events = import_jsonl(source, ledger)
            self.assertEqual(len(events), 2)
            self.assertEqual(read_events(ledger)[1]["event_type"], "blind_spot.declared")


if __name__ == "__main__":
    unittest.main()
