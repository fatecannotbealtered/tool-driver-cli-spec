"""Review regressions at the SDK boundary, using controlled text-file adapters only."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import test_sdk as fixtures
from tool_driver_sdk.scope import well_formed_prefix, within


class DriverReviewRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.SDKTests.setUpClass()

    @classmethod
    def tearDownClass(cls):
        fixtures.SDKTests.tearDownClass()

    def setUp(self):
        self.case = fixtures.SDKTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_duplicate_scope_members_are_invalid_and_cannot_grant_write(self):
        self.case.grant(effects=["observe"])
        path = self.case.base / "home" / ".text-driver" / "scope.json"
        original = path.read_text(encoding="utf-8")
        path.write_text(original.replace('"effects": ["observe"]',
            '"effects": ["observe"], "effects": ["observe", "change", "persist"]'), encoding="utf-8")
        status = self.case.call("context")["data"]["authorization"]["status"]
        self.assertEqual(status, "invalid")
        self.case.edit("not allowed", "--dry-run", code=4)
        self.assertEqual(self.case.doc.read_text(encoding="utf-8"), "hello world")

    def test_encoded_separators_cannot_hide_destination_traversal(self):
        prefix = "share://host/release"
        for value in [prefix + "/%2e%2e%2foutside", prefix + "/..%5coutside", prefix + "/%2F.."]:
            with self.subTest(value=value):
                self.assertFalse(well_formed_prefix(value))
                self.assertFalse(within(value, prefix))
        self.assertTrue(within(prefix + "/design%20files/result", prefix))

    def _terminal_without_receipt(self, update):
        self.case.grant()
        data = self.case.call("doc", "render", "--path", str(self.case.doc), "--dry-run")["data"]
        initial = self.case.call("doc", "render", "--path", str(self.case.doc), "--confirm", data["confirm_token"])["data"]["operation_status"]
        with patch.object(self.case.adapter, "status", return_value=update):
            current = self.case.show(initial["operation_id"])
        self.assertEqual(current["status"], "unknown")
        self.assertIsNone(current["receipt"])
        refused = self.case.edit("blocked", "--dry-run", code=6)["error"]
        self.assertEqual(refused["details"]["conflict"], "unresolved_operation")

    def test_failed_async_job_without_effect_readback_keeps_target_unresolved(self):
        self._terminal_without_receipt({"status": "failed", "stage": "native-failure"})

    def test_observed_cancel_without_effect_readback_keeps_target_unresolved(self):
        self._terminal_without_receipt({"status": "cancelled", "stop_observed": True,
                                       "stop_evidence_ref": "test://controlled-stop"})

    def _wrong_receipt_identity(self, key, replacement):
        self.case.grant()
        data = self.case.plan()
        original = self.case.adapter.apply

        def wrong(call, plan):
            fields = original(call, plan)
            fields[key] = replacement
            return fields

        with patch.object(self.case.adapter, "apply", side_effect=wrong):
            error = self.case.edit("new text", "--confirm", data["confirm_token"], code=6)["error"]
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        self.assertEqual(self.case.show(data["preview"]["operation_id"])["status"], "unknown")
        self.assertEqual(self.case.doc.read_text(encoding="utf-8"), "new text")

    def test_receipt_of_another_plan_cannot_complete_this_operation(self):
        self._wrong_receipt_identity("plan_id", "unrelated-plan")

    def test_receipt_of_another_scope_cannot_complete_this_operation(self):
        self._wrong_receipt_identity("authorization_scope_id", "unrelated-scope")

    def test_receipt_of_another_target_cannot_complete_this_operation(self):
        other = self.case.root / "other.txt"
        other.write_text("other document", encoding="utf-8")
        self._wrong_receipt_identity("target", fixtures.target(other))

    def test_malformed_receipt_effects_still_leave_an_unknown_blocked_target(self):
        self._wrong_receipt_identity("effects", [{"change": True}])


if __name__ == "__main__":
    unittest.main()
