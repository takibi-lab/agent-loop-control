import json
import unittest

from agent_loop.policy import load_policy


class SchemaExamplesTests(unittest.TestCase):
    def test_policy_schema_mentions_required_fields_and_example_conforms_basically(self):
        with open("schemas/agent-policy.schema.json", encoding="utf-8") as fh:
            schema = json.load(fh)
        policy = load_policy("examples/agent-policy.yaml")
        self.assertIn("defaults", schema["properties"])
        self.assertIn("redaction", schema["properties"])
        self.assertIn("rules", schema["properties"])
        self.assertIn("decision", policy["defaults"])
        self.assertTrue(policy["redaction"]["patterns"])
        for rule in policy["rules"]:
            self.assertIn(rule["decision"], {"allow", "ask", "deny"})
            self.assertIn("id", rule)
            self.assertIn("match", rule)


if __name__ == "__main__":
    unittest.main()
