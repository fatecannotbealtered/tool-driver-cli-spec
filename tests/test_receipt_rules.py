"""The receipt -> ok/error-code table (COR-003) and the driver contract against its pinned base."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
sys.path.insert(0, str(ROOT / "scripts"))
import check_spec  # noqa: E402

RECEIPT = json.loads((ROOT / "examples" / "valid" / "receipt-applied-unsaved.json").read_text(encoding="utf-8"))
NOT_RUN = {"status": "not_run", "scope": "x", "snapshot_id": None, "coverage": "none", "checks": [], "not_checked": [], "evidence_refs": []}


def receipt(**outcome):
    value = copy.deepcopy(RECEIPT)
    verification = outcome.pop("verification", None)
    value["outcome"].update(outcome)
    if verification is not None:
        value["outcome"]["verification"] = verification
    return value


class ReceiptRuleTests(unittest.TestCase):
    def rule(self, value):
        return check_spec.receipt_rule(value)

    def test_success_and_no_op(self):
        self.assertTrue(self.rule(RECEIPT)["ok"])
        noop = receipt(change="not_applied", persistence="unchanged", verification=NOT_RUN)
        self.assertTrue(self.rule(noop)["ok"])

    def test_unknown_dimensions_come_first(self):
        for dimension in ["execution", "change", "persistence", "delivery"]:
            with self.subTest(dimension=dimension):
                value = receipt(**{dimension: "unknown"})
                self.assertEqual(self.rule(value)["codes"], ["E_OUTCOME_UNKNOWN"])
        self.assertEqual(self.rule(receipt(execution="running"))["codes"], ["E_OUTCOME_UNKNOWN"])

    def test_partial_and_stopped_after_lasting_effect(self):
        self.assertEqual(self.rule(receipt(change="partial"))["codes"], ["E_PARTIAL"])
        self.assertEqual(self.rule(receipt(execution="failed"))["codes"], ["E_PARTIAL"])
        saved_then_failed = receipt(execution="interrupted", change="not_applied", persistence="saved")
        self.assertEqual(self.rule(saved_then_failed)["codes"], ["E_PARTIAL"])

    def test_stopped_without_lasting_effect(self):
        value = receipt(execution="failed", change="not_applied", persistence="unchanged", verification=NOT_RUN)
        codes = self.rule(value)["codes"]
        self.assertIn("E_NATIVE_FAILURE", codes)
        self.assertIn("E_INTERRUPTED", codes)
        self.assertNotIn("E_PARTIAL", codes)

    def test_verification_outcomes(self):
        failed = dict(RECEIPT["outcome"]["verification"], status="failed")
        self.assertEqual(self.rule(receipt(verification=failed))["codes"], ["E_VERIFY_FAILED"])
        incomplete = dict(RECEIPT["outcome"]["verification"], status="incomplete", reason="checker crashed")
        self.assertEqual(self.rule(receipt(verification=incomplete))["codes"], ["E_VERIFY_INCOMPLETE"])
        self.assertEqual(self.rule(receipt(verification=NOT_RUN))["codes"], ["E_VERIFY_INCOMPLETE"])

    def test_every_rule_names_known_codes_and_ends_with_success(self):
        contract = check_spec.driver_contract()
        table = check_spec.code_table()
        rules = contract["receipt_codes"]["rules"]
        self.assertEqual(rules[-1], {"when": [], "ok": True, "codes": []})
        for rule in rules:
            self.assertTrue(all(code in table for code in rule["codes"]), rule)


class ContractTests(unittest.TestCase):
    def test_driver_codes_follow_the_base_extension_rules(self):
        self.assertEqual(check_spec.base_errors(), [])
        self.assertEqual(check_spec.contract_errors(), [])
        table = check_spec.code_table()
        self.assertEqual(table["E_OUTCOME_UNKNOWN"]["exit"], 6)
        self.assertFalse(table["E_OUTCOME_UNKNOWN"]["retryable"])
        self.assertEqual(table["E_HUMAN_REQUIRED"]["exit"], 9)
        self.assertTrue(table["E_BUSY"]["retryable"])
        self.assertTrue(table["E_TIMEOUT"]["retryable"], "the base keeps E_TIMEOUT retryable; the driver layer limits when it is used")

    def test_check_spec_passes_as_a_base_envelope(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "check_spec.py")], capture_output=True, timeout=120,
                                creationflags=HIDDEN)
        response = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(result.returncode, 0, response)
        self.assertEqual(set(response), {"ok", "schema_version", "data", "meta"})
        self.assertTrue(response["ok"])

    def test_check_spec_main_writes_to_text_streams(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()) as output:
            status = check_spec.main()
        self.assertEqual(status, 0)
        self.assertTrue(json.loads(output.getvalue())["ok"])

    def test_vendored_base_matches_its_lock(self):
        lock = json.loads((ROOT / "base" / "base-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["tag"], check_spec.driver_contract()["base"]["tag"])
        self.assertEqual(len(lock["files"]), 11)


if __name__ == "__main__":
    unittest.main()
