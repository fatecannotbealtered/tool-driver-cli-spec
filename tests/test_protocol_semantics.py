"""Adversarial phase, authorization and diagnostic cases at the actual CLI boundary."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/validate_contract.py"


class ProtocolSemanticsTests(unittest.TestCase):
    def invoke(self, schema, value):
        result = subprocess.run([sys.executable, str(CLI), "--schema", schema, "--input", "-"], input=json.dumps(value, ensure_ascii=False).encode("utf-8"), capture_output=True, timeout=15)
        parsed = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        return result, parsed

    def test_modify_cannot_be_hidden_by_verification_or_observation_phase(self):
        baseline = json.loads((ROOT / "examples/valid/workflow-read-plan-completed.json").read_text(encoding="utf-8"))
        for phase in ["verify", "observe", "apply", "result"]:
            with self.subTest(phase=phase):
                value = copy.deepcopy(baseline)
                value["steps"][0]["phase"] = phase
                value["steps"][0]["effects"] = ["change"]
                result, report = self.invoke("workflow", value)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(report["ok"])

    def test_nested_workflow_obeys_the_same_modify_rule(self):
        workflow = json.loads((ROOT / "examples/invalid/workflow-modification-hidden-as-verify.json").read_text(encoding="utf-8"))
        value = {"ok": True, "schema_version": "1.0", "request_id": "request-1", "phase": "result", "meta": {"duration_ms": 0}, "data": {"workflow": workflow}}
        result, report = self.invoke("response", value)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(report["ok"])

    def test_known_changes_need_an_authorization_reference(self):
        value = json.loads((ROOT / "examples/valid/receipt-applied-unsaved.json").read_text(encoding="utf-8"))
        value["authorization_scope_id"] = None
        result, report = self.invoke("receipt", value)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(report["ok"])

    def test_schema_errors_do_not_echo_sensitive_input_values(self):
        value = json.loads((ROOT / "examples/valid/response-applied-unsaved.json").read_text(encoding="utf-8"))
        sensitive = "private-token-value-DO-NOT-REPEAT"
        value["meta"]["duration_ms"] = sensitive
        result, report = self.invoke("response", value)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(sensitive.encode(), result.stdout + result.stderr)
        self.assertFalse(report["ok"])

    def test_malformed_schema_diagnostics_do_not_dump_its_data(self):
        value = json.loads((ROOT / "examples/valid/reference-experimental.json").read_text(encoding="utf-8"))
        private = "private-secret-value-NOT-IN-DIAGNOSTICS"
        request = value["capabilities"][0]["request_schema"]
        value["schemas"][request]["type"] = private
        result, report = self.invoke("reference", value)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(private.encode(), result.stdout + result.stderr)
        self.assertFalse(report["ok"])

    def test_numeric_overflow_is_rejected_without_infinity_output(self):
        payload = b'{"ok":true,"schema_version":"1.0","request_id":"r","phase":"observe","meta":{"duration_ms":1e999},"data":{}}'
        result = subprocess.run([sys.executable, str(CLI), "--schema", "response", "--input", "-"], input=payload, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)["ok"])
        self.assertNotIn(b"Infinity", result.stdout)

    def test_shared_definitions_are_not_an_empty_instance_contract(self):
        result, report = self.invoke("common", {"arbitrary": "input"})
        self.assertEqual(result.returncode, 2)
        self.assertFalse(report["ok"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "named pipes are tested on POSIX CI")
    def test_file_input_named_pipe_never_waits_for_a_writer(self):
        with tempfile.TemporaryDirectory(prefix="contract-fifo-") as temporary:
            path = Path(temporary) / "input.json"
            os.mkfifo(path)
            result = subprocess.run([sys.executable, str(CLI), "--schema", "response", "--input", str(path)], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
