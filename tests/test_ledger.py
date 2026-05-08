import json
import tempfile
import unittest
from pathlib import Path

from agent_loop.ledger import LedgerError, append_event, read_events
from agent_loop.verifier import verify_ledger


class LedgerTests(unittest.TestCase):
    def test_first_and_subsequent_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            first = append_event(path, {"event_type": "session.start"})
            second = append_event(path, {"event_type": "session.end"})
            self.assertIsNone(first["prev_hash"])
            self.assertEqual(second["prev_hash"], first["hash"])
            self.assertEqual(len(read_events(path)), 2)
            self.assertTrue(verify_ledger(path).valid)

    def test_malformed_existing_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            path.write_text("{bad json}\n", encoding="utf-8")
            with self.assertRaises(LedgerError):
                append_event(path, {"event_type": "session.start"})

    def test_verifier_detects_changed_content_and_broken_prev_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            first = append_event(path, {"event_type": "session.start"})
            append_event(path, {"event_type": "session.end"})
            lines = path.read_text(encoding="utf-8").splitlines()
            event = json.loads(lines[0])
            event["event_type"] = "session.end"
            path.write_text(json.dumps(event) + "\n" + lines[1] + "\n", encoding="utf-8")
            self.assertFalse(verify_ledger(path).valid)

            other = Path(tmp) / "broken.jsonl"
            event = dict(first)
            event["prev_hash"] = "wrong"
            other.write_text(json.dumps(event) + "\n", encoding="utf-8")
            self.assertFalse(verify_ledger(other).valid)

    def test_empty_ledger_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.jsonl"
            path.write_text("", encoding="utf-8")
            result = verify_ledger(path)
            self.assertTrue(result.valid)
            self.assertEqual(result.checked, 0)


if __name__ == "__main__":
    unittest.main()
