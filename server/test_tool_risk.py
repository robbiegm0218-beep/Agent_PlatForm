import unittest

from server.tool_risk import ToolRiskPolicy


class ToolRiskPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = ToolRiskPolicy()

    def test_read_only_is_the_only_automatic_risk(self):
        self.assertFalse(self.policy.assess("read_only").requires_confirmation)
        for risk in ("local_write", "external_write", "destructive"):
            with self.subTest(risk=risk):
                self.assertTrue(self.policy.assess(risk).requires_confirmation)

    def test_privileged_requires_explicit_request_and_confirmation(self):
        self.assertFalse(self.policy.assess("privileged").allowed)
        approved_surface = self.policy.assess("privileged", explicitly_requested=True)
        self.assertTrue(approved_surface.allowed)
        self.assertTrue(approved_surface.requires_confirmation)

    def test_unknown_and_non_idempotent_write_registration_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知"):
            self.policy.validate_registration("mystery", True)
        with self.assertRaisesRegex(ValueError, "幂等"):
            self.policy.validate_registration("local_write", False)


if __name__ == "__main__":
    unittest.main()
