"""Synthetic design-contract tests. These fixtures are not application acceptance evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_product_design import check_design  # noqa: E402
from generate_product import GenerationError, build_artifacts, build_contract, generate_registry  # noqa: E402

REGISTRY = json.loads((ROOT / "examples/development/product-registry.json").read_text(encoding="utf-8"))
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ProductDesignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="design-contract-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def artifact(self, record, identity, kind, value, **extra):
        payload = (json.dumps(value, sort_keys=True) + "\n").encode() if not isinstance(value, bytes) else value
        path = identity + ".json"
        (self.root / path).write_bytes(payload)
        item = {"id": identity, "kind": kind, "path": path, "sha256": hashlib.sha256(payload).hexdigest(),
                "source": "Synthetic contract-test fixture; not actual application evidence.", "summary": "Synthetic bytes for contract consistency tests.", **extra}
        record["evidence"] = [e for e in record["evidence"] if e["id"] != identity] + [item]
        return item

    def supported_fixture(self):
        reg = copy.deepcopy(REGISTRY)
        reg["commands"] = reg["commands"][:1]
        d = reg["design"]
        d["commands"] = d["commands"][:1]
        d["capabilities"] = d["capabilities"][:1]
        d["tasks"] = d["tasks"][:1]
        cid = d["capabilities"][0]["id"]
        task = d["tasks"][0]
        d["scope"]["inventory_ids"] = [cid]
        d["coverage"]["denominator_ids"] = [cid]
        d["application"].update(name="SyntheticConsumer", version="1.0", license="synthetic",
                                environment={"platform": "synthetic", "arch": "synthetic", "mode": "file"}, evidence_refs=["survey"])
        d["scope"]["inventory_evidence_refs"] = ["survey"]
        cap = d["capabilities"][0]
        cap.update(application_support="supported", automation="reachable", adapter="implemented", testing="verified", evidence_refs=["survey", "run"])
        task.update(status="supported", adapter_entries=[{"command_path": "drawing inspect", "artifact_ref": "implementation", "entrypoint": "Adapter.run"}],
                    readback=[{"id": "readback", "method": "Synthetic fixture readback", "criterion": "Width within tolerance", "independence": "Declared synthetic distinct sources"}],
                    test_ids=["inspect-test"])
        d["tests"] = [{"id": "inspect-test", "task_id": task["id"], "command_path": "drawing inspect", "status": "passed",
                       "evidence_ref": "run", "check_ids": ["readback"], "reason": "Synthetic record only."}]
        cmd = reg["commands"][0]
        cmd["driver"].update(maturity="verified", evidence_refs=["run"], environments=[{
            "application": "SyntheticConsumer", "application_version": "1.0", "platform": "synthetic", "arch": "synthetic",
            "adapter_version": "0.1.0", "mode": "file", "limitations": ["Synthetic test fixture"]}])
        profile = json.loads((ROOT / "examples/valid/verification-result-file.json").read_text(encoding="utf-8"))
        profile["observations"][0]["source"]["evidence_ref"] = "observations"
        raw = json.loads((ROOT / "examples/valid/evidence-development.json").read_text(encoding="utf-8"))
        raw.update(evidence_id="synthetic-run", kind="artifact_consumer", target=profile["target"], snapshot_id=profile["snapshot"]["id"],
                   capabilities=[cid], commands=["sample-driver drawing inspect --file synthetic.svg"],
                   checks=[{"id": "readback", "status": "passed", "required": True, "evidence_ref": "observations"}],
                   environment={"platform": "synthetic", "arch": "synthetic", "components": [{
                       "name": "SyntheticConsumer", "role": "application", "version": "1.0", "build_id": "fixture",
                       "location": "disk", "identity_status": "observed"}]})
        self.artifact(d, "survey", "document", b"Synthetic survey, version 1.0. Not application evidence.\n")
        self.artifact(d, "implementation", "implementation", b"class Adapter:\n    def run(self, call): pass\n")
        self.artifact(d, "observations", "observation", {"width": profile["observations"][0]["observed"]}, measurements={"readback": "/width"})
        self.artifact(d, "readback", "readback", profile)
        self.artifact(d, "run", "real_run", raw, binding={"run_id": "synthetic-run", "source_commit": raw["source_commit"],
                      "application_version": "1.0", "platform": "synthetic", "arch": "synthetic"}, readback_ref="readback")
        return reg

    def errors(self, reg):
        return check_design(reg, registry_dir=self.root, require=True)["errors"]

    def test_draft_does_not_count_unknown_or_placeholder_as_verified(self):
        report = check_design(copy.deepcopy(REGISTRY), require=True)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["coverage"]["verified"], 0)
        self.assertEqual(report["coverage"]["supported_tasks"], 0)
        self.assertEqual(report["coverage"]["denominator"], 4)
        self.assertEqual(report["coverage"]["declared_command_fcc"], "not_evaluated_by_this_checker")

    def test_legacy_registry_and_public_runtime_shape_remain_compatible(self):
        reg = copy.deepcopy(REGISTRY)
        before = build_contract(reg)
        reg.pop("design")
        after = build_contract(reg)
        self.assertEqual(before["reference"], after["reference"])
        self.assertEqual(set(before), set(after))
        self.assertNotIn("design", before["reference"])
        self.assertEqual(after["reference"]["driver_profile"]["schema_version"], "2.0")
        self.assertFalse(check_design(reg)["recorded"])
        self.assertTrue(check_design(reg, require=True)["errors"])
        artifact = json.loads(build_artifacts(reg)["development-design.json"])
        self.assertIsNone(artifact["coverage"])

    def test_bound_synthetic_record_checks_files_and_measured_values(self):
        reg = self.supported_fixture()
        report = check_design(reg, registry_dir=self.root, require=True)
        self.assertEqual(report["errors"], [], report)
        self.assertEqual(len(report["checked_artifacts"]), 5)
        self.assertEqual((report["coverage"]["verified"], report["coverage"]["supported_tasks"]), (1, 1))
        self.assertFalse(report["origin_authenticated"])
        build_contract(reg, registry_dir=self.root)

    def test_dangling_references_scope_omission_duplicates_and_command_omission_fail(self):
        changes = [lambda d: d["commands"][0]["capability_ids"].append("missing"),
                   lambda d: d["coverage"]["denominator_ids"].pop(),
                   lambda d: d["scope"]["inventory_ids"].pop(),
                   lambda d: d["commands"].pop(),
                   lambda d: d["capabilities"].append(copy.deepcopy(d["capabilities"][0])),
                   lambda d: d["tasks"][0]["test_ids"].append("missing")]
        for change in changes:
            reg = copy.deepcopy(REGISTRY)
            change(reg["design"])
            with self.subTest(change=change):
                self.assertTrue(self.errors(reg))

    def test_supported_task_needs_parameters_entries_readback_and_actual_tests(self):
        for field in ("critical_parameters", "adapter_entries", "readback", "test_ids"):
            reg = self.supported_fixture()
            reg["design"]["tasks"][0][field] = []
            with self.subTest(field=field):
                self.assertTrue(self.errors(reg))

    def test_status_dimensions_do_not_infer_unsupported_from_unreachable(self):
        reg = self.supported_fixture()
        d = reg["design"]
        d["capabilities"][0].update(automation="unreachable", testing="blocked", adapter="unimplemented")
        d["tasks"][0]["status"] = "blocked"
        d["tests"][0].update(status="blocked", evidence_ref=None, check_ids=[])
        reg["commands"][0]["driver"]["maturity"] = "draft"
        self.assertEqual(self.errors(reg), [])
        self.assertEqual(d["capabilities"][0]["application_support"], "supported")
        self.assertEqual(check_design(reg, registry_dir=self.root)["coverage"]["verified"], 0)

    def test_missing_files_changed_hashes_and_unsafe_paths_fail_before_generation(self):
        for path in ("missing.json", "../outside.json", "C:/outside.json"):
            reg = self.supported_fixture()
            reg["design"]["evidence"][0]["path"] = path
            self.assertTrue(self.errors(reg))
        reg = self.supported_fixture()
        (self.root / "observations.json").write_text("{}", encoding="utf-8")
        output = self.root / "generated"
        with self.assertRaises(GenerationError):
            generate_registry(reg, output, registry_dir=self.root)
        self.assertFalse(output.exists())

    def test_fixture_or_incomplete_run_cannot_back_passed_tests(self):
        for kind in ("simulated_adapter", "contract", "manual_review"):
            reg = self.supported_fixture()
            d = reg["design"]
            raw = json.loads((self.root / "run.json").read_text())
            raw["kind"] = kind
            previous = next(e for e in d["evidence"] if e["id"] == "run")
            self.artifact(d, "run", "real_run", raw, binding=previous["binding"], readback_ref="readback")
            self.assertTrue(self.errors(reg))
        for status in ("blocked", "unknown", "not_run"):
            reg = self.supported_fixture()
            reg["design"]["tests"][0]["status"] = status
            self.assertTrue(self.errors(reg))

    def test_run_source_application_version_and_environment_are_bound(self):
        for field, value in (("run_id", "other-run"), ("source_commit", "f" * 40), ("application_version", "2.0"), ("platform", "other"), ("arch", "other")):
            reg = self.supported_fixture()
            next(e for e in reg["design"]["evidence"] if e["id"] == "run")["binding"][field] = value
            with self.subTest(field=field):
                self.assertTrue(self.errors(reg))

    def test_expected_observed_and_actual_artifact_must_agree(self):
        reg = self.supported_fixture()
        self.artifact(reg["design"], "observations", "observation", {"width": {"value": 10, "unit": "mm"}}, measurements={"readback": "/width"})
        self.assertTrue(any("actual observation" in e for e in self.errors(reg)))
        reg = self.supported_fixture()
        profile = json.loads((self.root / "readback.json").read_text())
        profile["observations"][0]["observed"]["value"] = 10
        self.artifact(reg["design"], "readback", "readback", profile)
        self.artifact(reg["design"], "observations", "observation", {"width": {"value": 10, "unit": "mm"}}, measurements={"readback": "/width"})
        self.assertTrue(any("does not pass" in e for e in self.errors(reg)))

    def test_domain_and_tool_management_accounting(self):
        reg = copy.deepcopy(REGISTRY)
        reg["design"]["commands"][0].update(role="tool_management", capability_ids=[], task_ids=[], rationale="A tool-only diagnostic.")
        reg["design"]["capabilities"][0].update(cli_exposure="not_exposed", disposition="excluded", reason="Tool management outside application scope.")
        reg["design"]["tasks"].pop(0)
        self.assertEqual(self.errors(reg), [])
        reg["design"]["commands"][0]["role"] = "domain"
        self.assertTrue(self.errors(reg))

    def test_command_line_requires_design_and_preserves_base_envelope(self):
        reg = copy.deepcopy(REGISTRY)
        reg.pop("design")
        path = self.root / "registry.json"
        path.write_text(json.dumps(reg), encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/check_product_design.py"),
                                 "--registry", str(path), "--require-design"], capture_output=True, timeout=30, creationflags=HIDDEN)
        self.assertEqual(result.returncode, 2)
        response = json.loads(result.stdout)
        self.assertEqual(set(response), {"ok", "schema_version", "error", "meta"})
        self.assertIn("next_action", response["error"]["details"])
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/check_product_design.py")],
                                capture_output=True, timeout=30, creationflags=HIDDEN)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "E_USAGE")
        for item in json.loads((ROOT / "examples/index.json").read_text(encoding="utf-8"))["examples"]:
            if item["schema"] != "product-registry.schema.json":
                continue
            result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/check_product_design.py"),
                                     "--registry", str(ROOT / item["path"]), "--require-design"],
                                    capture_output=True, timeout=30, creationflags=HIDDEN)
            with self.subTest(path=item["path"]):
                self.assertEqual(result.returncode, 0 if item["valid"] else 2, result.stdout)
                self.assertEqual(json.loads(result.stdout)["ok"], item["valid"])

    def test_generated_design_is_owned_and_drift_checked(self):
        reg = self.supported_fixture()
        output = self.root / "generated"
        generate_registry(reg, output, registry_dir=self.root)
        artifact = json.loads((output / "development-design.json").read_text())
        self.assertEqual(artifact["coverage"]["denominator"], 1)
        self.assertEqual(generate_registry(reg, output, registry_dir=self.root, check=True)["changed"], False)
        (output / "development-design.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(GenerationError):
            generate_registry(reg, output, registry_dir=self.root, update=True)


if __name__ == "__main__":
    unittest.main()
