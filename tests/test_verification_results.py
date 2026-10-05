"""Real file writes/independent process readback; checker-state fixtures are explicitly simulated.

These tests do not connect to a CAD application or device and are not native acceptance evidence.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from test_sdk import CHANGELOG, REGISTRY, ROOT, VALIDATOR, TextAdapter, build_contract, path_of
from tool_driver_sdk import ContractValidationError, DriverCLI, build_verification
from tool_driver_sdk.verification import EXTENSION, PROFILE, UNTRUSTED_PATH

HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def record(target, snapshot, expected=12, observed=12):
    """Fixture values are not application evidence; CLI cases replace observed with a real disk read."""
    return {"profile": PROFILE, "target": deepcopy(target), "snapshot": deepcopy(snapshot),
            "requirements": [{"id": "readback", "kind": "field", "field_path": "",
                              "expected": {"value": expected, "unit": None}, "comparison": {"operator": "equals"},
                              "allowed_sources": ["file_consumer"],
                              "independence": {"required": True, "writer_sources": ["fixture-text-writer"],
                                               "expectation_sources": ["task-integer-literal"]}}],
            "observations": [{"requirement_id": "readback", "observed": {"value": observed, "unit": None},
                              "source": {"kind": "file_consumer", "completion": "completed", "target": deepcopy(target),
                                         "snapshot": deepcopy(snapshot), "method": "separate process parses the saved JSON number",
                                         "evidence_ref": "fixture-disk-readback", "defect_sources": ["stdlib-json-consumer"],
                                         "independence_basis": "writer saves text; task uses an integer literal; a fresh process parses disk JSON",
                                         "coverage": {"checked_paths": [""], "not_checked": []}}}],
            "not_checked": []}


class ObservedFileAdapter(TextAdapter):
    def __init__(self, scenario):
        super().__init__()
        self.scenario = scenario

    def apply(self, call, plan):
        path = path_of(plan["target"]["locator"])
        before = path.read_bytes()
        # A controlled backend actually ignores/clamps input. No requested value is used as observed.
        value = path.read_text(encoding="utf-8") if self.scenario in {"ignored", "echo"} else (
            "10" if self.scenario == "adjusted" else call.params["text"])
        receipt = super().apply(replace(call, params=dict(call.params, text=value)), plan)
        changed = path.read_bytes() != before
        receipt["outcome"].update(change="applied" if changed else "not_applied", persistence="saved" if changed else "unchanged")
        expected = int(call.params["text"])
        observed = None
        if self.scenario != "missing":
            reader = subprocess.run([sys.executable, "-I", "-c",
                                     "import json,sys; from pathlib import Path; print(json.dumps(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))))",
                                     str(path)], capture_output=True, check=True, timeout=10, creationflags=HIDDEN)
            observed = json.loads(reader.stdout)
        profile = record(plan["target"], receipt["snapshot_after"], expected, observed)
        requirement = profile["requirements"][0]
        observation = profile["observations"][0]
        source = observation["source"]
        if self.scenario == "missing":
            profile["observations"] = []
        elif self.scenario in {"screenshot", "echo"}:
            source["kind"] = "screenshot" if self.scenario == "screenshot" else "input_echo"
            source["method"] = "deliberately false source claim in a fixture; no actual screenshot"
            observation["observed"]["value"] = expected
            requirement["allowed_sources"] = [source["kind"]]  # even explicitly allowing it cannot prove a field
        elif self.scenario in {"same-writer", "same-expectation", "unknown-independence"}:
            source["defect_sources"] = {"same-writer": ["fixture-text-writer"],
                                        "same-expectation": ["task-integer-literal"], "unknown-independence": []}[self.scenario]
        elif self.scenario in {"running", "timeout", "new-finding", "custom-checker"}:
            # Simulated checker output exercises status/identity gates, not an official/native checker.
            source.update(kind="custom_checker" if self.scenario == "custom-checker" else "native_checker",
                          completion=self.scenario if self.scenario in {"running", "timeout"} else "completed",
                          method="explicitly simulated checker fixture", evidence_ref="simulated-checker-record",
                          defect_sources=["simulated-checker"])
            requirement.update(kind="structure", field_path="/findings", allowed_sources=["native_checker"],
                               comparison={"operator": "no_new_findings", "identity_fields": ["/rule", "/object"]})
            source["coverage"]["checked_paths"] = ["/findings"]
            requirement["expected"]["value"] = [{"rule": "clearance", "object": "old"}] if self.scenario == "new-finding" else []
            observation["observed"]["value"] = [{"rule": "clearance", "object": "new"}] if self.scenario == "new-finding" else []
        elif self.scenario == "stale-source":
            source["snapshot"]["revision"] = "old-revision"
        elif self.scenario == "stale-profile":
            profile["snapshot"]["revision"] = "old-revision"
            source["snapshot"]["revision"] = "old-revision"
        elif self.scenario in {"prior-failed", "prior-incomplete"}:
            legacy = receipt["outcome"]["verification"]
            legacy.update(status="failed" if self.scenario == "prior-failed" else "incomplete", coverage="partial")
            legacy["checks"].append({"id": "another-invariant", "required": True, "status": legacy["status"],
                                      "evidence_ref": "another-check", "reason": "separate invariant not established"})
            if self.scenario == "prior-incomplete":
                legacy["reason"] = "separate required invariant is still incomplete"
        # Intentionally overclaim legacy status. The runtime must derive the result itself.
        receipt["outcome"]["verification"]["extensions"] = {EXTENSION: profile}
        return receipt


class VerificationResultTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="verification-results-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        (self.base / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
        self.path = self.base / "number.json"
        self.path.write_text("5", encoding="utf-8")
        scope = {"scope_id": "verification-fixture", "tool": "text-driver", "granted_by": "test fixture",
                 "granted_at": "2026-01-01T00:00:00Z", "expires_at": None, "effects": ["observe", "change", "persist"],
                 "dangerous": False, "roots": [str(self.base)], "outputs": [str(self.base)]}
        (self.base / "scope.json").write_text(json.dumps(scope), encoding="utf-8")

    def cli(self, scenario, *argv):
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", TEXT_DRIVER_SCOPE_FILE=str(self.base / "scope.json"),
                           TEXT_DRIVER_STATE_DIR=str(self.base / ("state-" + scenario)))
        process = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--fixture-cli", scenario, *argv],
                                 cwd=self.base, env=environment, capture_output=True, timeout=30, creationflags=HIDDEN)
        self.assertTrue(process.stdout, process.stderr.decode("utf-8", errors="replace"))
        value = json.loads(process.stdout)
        VALIDATOR.validate("response", value)
        return process.returncode, value

    def write(self, scenario):
        self.path.write_text("5", encoding="utf-8")
        args = ["doc", "edit", "--path", str(self.path), "--text", "12"]
        code, preview = self.cli(scenario, *args, "--dry-run")
        self.assertEqual(code, 0, preview)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "5", "preview must not write")
        code, result = self.cli(scenario, *args, "--confirm", preview["data"]["confirm_token"])
        receipt = result["data"]["receipt"] if result["ok"] else result["error"]["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["execution"], "completed")
        self.assertIn(UNTRUSTED_PATH, receipt["_untrusted"])
        # Operation lookup in another process must preserve the guarded result, without redispatch.
        before = self.path.read_bytes()
        _, lookup = self.cli(scenario, "operation", "show", "--id", receipt["operation_id"])
        stored = lookup["data"]["operation_status"]["receipt"]
        self.assertEqual(stored["outcome"]["verification"], receipt["outcome"]["verification"])
        self.assertEqual(self.path.read_bytes(), before)
        return code, result, receipt

    def test_cli_retains_real_ignored_and_adjusted_readback(self):
        for scenario, actual, error in [("normal", 12, None), ("ignored", 5, "E_VERIFY_FAILED"), ("adjusted", 10, "E_VERIFY_FAILED")]:
            with self.subTest(scenario=scenario):
                code, result, receipt = self.write(scenario)
                self.assertEqual(json.loads(self.path.read_text()), actual)
                profile = receipt["outcome"]["verification"]["extensions"][EXTENSION]
                self.assertEqual(profile["requirements"][0]["expected"]["value"], 12)
                self.assertEqual(profile["observations"][0]["observed"]["value"], actual)
                self.assertEqual(result["ok"], error is None)
                if error:
                    self.assertNotEqual(code, 0)
                    self.assertEqual(result["error"]["code"], error)
                    self.assertEqual(receipt["outcome"]["verification"]["status"], "failed")

    def test_cli_refuses_false_or_incomplete_structural_success(self):
        for scenario in ("screenshot", "missing", "echo", "same-writer", "same-expectation", "unknown-independence",
                         "running", "timeout", "stale-source", "stale-profile", "custom-checker"):
            with self.subTest(scenario=scenario):
                code, result, receipt = self.write(scenario)
                self.assertNotEqual(code, 0)
                self.assertEqual(result["error"]["code"], "E_VERIFY_INCOMPLETE")
                verification = receipt["outcome"]["verification"]
                self.assertEqual(verification["status"], "incomplete")
                self.assertTrue(verification["not_checked"])
                self.assertEqual(json.loads(self.path.read_text()), 5 if scenario == "echo" else 12)

    def test_cli_equal_counts_do_not_hide_a_new_finding(self):
        _, result, receipt = self.write("new-finding")
        self.assertEqual(result["error"]["code"], "E_VERIFY_FAILED")
        profile = receipt["outcome"]["verification"]["extensions"][EXTENSION]
        expected = profile["requirements"][0]["expected"]["value"]
        actual = profile["observations"][0]["observed"]["value"]
        self.assertEqual(len(expected), len(actual))
        self.assertNotEqual(expected[0]["object"], actual[0]["object"])

    def test_cli_keeps_other_failures_and_incomplete_coverage(self):
        for scenario, error in [("prior-failed", "E_VERIFY_FAILED"), ("prior-incomplete", "E_VERIFY_INCOMPLETE")]:
            with self.subTest(scenario=scenario):
                _, result, receipt = self.write(scenario)
                self.assertEqual(result["error"]["code"], error)
                verification = receipt["outcome"]["verification"]
                self.assertEqual(verification["coverage"], "partial")
                profile_check = next(item for item in verification["checks"] if item["id"] == "readback")
                self.assertEqual(profile_check["status"], "passed")
                other = next(item for item in verification["checks"] if item["id"] == "another-invariant")
                self.assertNotEqual(other["status"], "passed")
                self.assertEqual(json.loads(self.path.read_text()), 12)

    def sample(self):
        example = json.loads((ROOT / "examples/valid/receipt-file-saved.json").read_text(encoding="utf-8"))
        return record(example["target"], example["snapshot_after"])

    def test_units_tolerance_json_types_and_coverage(self):
        for expected, actual, unit, actual_unit, tolerance, status in [
            (12, 12.01, "mm", "mm", 0.02, "passed"), (12, 12.03, "mm", "mm", 0.02, "failed"),
            (12, 12, "mm", "m", 0.02, "incomplete"), (True, 1, None, None, None, "failed")]:
            with self.subTest(expected=expected, actual=actual, unit=actual_unit):
                profile = self.sample()
                requirement = profile["requirements"][0]
                requirement["expected"] = {"value": expected, "unit": unit}
                if tolerance is not None:
                    requirement["comparison"] = {"operator": "within_tolerance", "absolute": tolerance}
                profile["observations"][0]["observed"] = {"value": actual, "unit": actual_unit}
                result = build_verification(profile, scope="selected field only", validator=VALIDATOR)
                self.assertEqual(result["status"], status)
        profile = self.sample()
        profile["not_checked"] = [{"field_path": "/connections", "required": True, "reason": "reader unavailable"}]
        self.assertEqual(build_verification(profile, scope="required connections", validator=VALIDATOR)["status"], "incomplete")
        profile["not_checked"][0]["required"] = False
        result = build_verification(profile, scope="scalar only; connections explicitly excluded", validator=VALIDATOR)
        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["not_checked"][0]["required"])

    def test_static_validator_rejects_a_forged_pass_and_keeps_legacy_compatibility(self):
        receipt = json.loads((ROOT / "examples/valid/receipt-file-saved.json").read_text(encoding="utf-8"))
        VALIDATOR.validate("receipt", receipt)
        # Previously legal opaque extensions are not retroactively assigned the new profile's shape.
        receipt["outcome"]["verification"]["extensions"] = {EXTENSION: {"profile": "a-private-profile:1", "note": "legacy format"}}
        VALIDATOR.validate("receipt", receipt)
        profile = record(receipt["target"], receipt["snapshot_after"], 12, 5)
        future = deepcopy(receipt)
        future_profile = deepcopy(profile)
        future_profile["profile"] = PROFILE.replace(":2.0", ":99.0")
        future["outcome"]["verification"]["extensions"] = {EXTENSION: future_profile}
        with self.assertRaises(ContractValidationError):
            VALIDATOR.validate("receipt", future)
        receipt["outcome"]["verification"] = build_verification(profile, scope="selected field", validator=VALIDATOR)
        receipt["_untrusted"] = [UNTRUSTED_PATH]
        VALIDATOR.validate("receipt", receipt)
        receipt["outcome"]["verification"].update(status="passed", checks=[{"id": "readback", "required": True,
                                                                           "status": "passed", "evidence_ref": "fake-pass"}])
        with self.assertRaises(ContractValidationError):
            VALIDATOR.validate("receipt", receipt)

    def test_finding_counts_or_ambiguous_identity_are_incomplete(self):
        for expected, actual in [(0, 0), ([{"rule": "x"}], [{"rule": "x"}]),
                                 ([{"rule": "x", "object": "a"}] * 2, [{"rule": "x", "object": "a"}] * 2)]:
            profile = self.sample()
            profile["requirements"][0].update(comparison={"operator": "no_new_findings", "identity_fields": ["/rule", "/object"]},
                                               expected={"value": expected, "unit": None})
            profile["observations"][0]["observed"]["value"] = actual
            self.assertEqual(build_verification(profile, scope="stable finding identity", validator=VALIDATOR)["status"], "incomplete")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--fixture-cli"]:
        scenario = sys.argv[2]
        base = Path(os.environ["TEXT_DRIVER_STATE_DIR"]).parent
        contract = build_contract(REGISTRY, registry_dir=base)
        with DriverCLI(contract, ObservedFileAdapter(scenario), validator=VALIDATOR, environ=os.environ, home=base / "home") as cli:
            output = cli.run(sys.argv[3:])
        raise SystemExit(output.write())
    unittest.main()
