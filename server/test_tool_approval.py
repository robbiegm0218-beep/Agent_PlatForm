import json
import unittest

from server.tool_approval import approval_preview


class ToolApprovalTests(unittest.TestCase):
    def test_persists_only_explicitly_whitelisted_arguments(self):
        preview = approval_preview(
            tool_id="publish_report", tool_name="发布报告", risk_level="external_write",
            arguments={"title": "周报", "api_token": "secret", "recipients": ["a@example.com"]},
            visible_argument_keys={"title", "recipients"}, effect_summary="向已选收件人发布报告",
            rollback_summary="发布后需在外部系统撤回", idempotency_key="run_1:publish_report",
        )
        self.assertEqual(json.loads(preview["arguments_json"]), {"recipients": ["a@example.com"], "title": "周报"})
        self.assertNotIn("secret", json.dumps(preview, ensure_ascii=False))
        self.assertEqual(preview["risk_level"], "external_write")

    def test_rejects_read_only_or_unknown_risk(self):
        for risk in ("read_only", "unknown"):
            with self.subTest(risk=risk), self.assertRaises(ValueError):
                approval_preview(tool_id="read", tool_name="读取", risk_level=risk, arguments={}, idempotency_key="x", effect_summary="", rollback_summary="")


if __name__ == "__main__":
    unittest.main()
