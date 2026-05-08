import unittest

from agent_loop.policy import classify, load_policy
from agent_loop.redaction import redact_event


class PolicyRedactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_policy("examples/agent-policy.yaml")

    def test_policy_matches_allow_ask_deny_and_default(self):
        self.assertEqual(classify(self.policy, tool="Grep").decision, "allow")
        self.assertEqual(classify(self.policy, command="curl https://example.com").decision, "ask")
        self.assertEqual(classify(self.policy, paths=[".env"]).decision, "deny")
        default = classify(self.policy, command="unknown command")
        self.assertEqual(default.decision, "ask")
        self.assertIsNone(default.rule_id)

    def test_deny_precedence(self):
        decision = classify(self.policy, command="git status --short", paths=[".env"])
        self.assertEqual(decision.decision, "deny")

    def test_redaction_configured_no_match_multiple_and_bad_regex(self):
        policy = {
            "redaction": {
                "enabled": True,
                "patterns": [
                    {"name": "token", "regex": "token=([^\\s]+)", "replacement": "token=[REDACTED]"},
                    {"name": "password", "regex": "password=([^\\s]+)", "replacement": "password=[REDACTED]"},
                    {"name": "bad", "regex": "(", "replacement": "x"},
                ],
            }
        }
        event = {"event_type": "tool.pre", "tool": {"command": "token=abc password=def"}}
        redacted = redact_event(event, policy)
        self.assertEqual(redacted["tool"]["command"], "token=[REDACTED] password=[REDACTED]")
        self.assertTrue(redacted["redaction"]["applied"])
        self.assertEqual(redacted["redaction"]["patterns"], ["password", "token"])

        clean = redact_event({"event_type": "tool.pre", "tool": {"command": "echo ok"}}, policy)
        self.assertFalse(clean["redaction"]["applied"])
        self.assertNotIn("abc", str(redacted))


if __name__ == "__main__":
    unittest.main()
