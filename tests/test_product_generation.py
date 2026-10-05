"""The product generator: one registry, owned outputs, drift checks and refusals."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
sys.path.insert(0, str(ROOT / "scripts"))
import check_spec  # noqa: E402
from generate_product import GenerationError, build_contract, generate_registry  # noqa: E402

REGISTRY = json.loads((ROOT / "examples" / "development" / "product-registry.json").read_text(encoding="utf-8"))


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="generation-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.output = self.base / "generated"

    def registry(self):
        return copy.deepcopy(REGISTRY)

    def test_reference_has_builtins_driver_profile_and_base_codes(self):
        contract = build_contract(self.registry())
        reference = contract["reference"]
        self.assertEqual(check_spec.reference_errors(reference), [])
        paths = {command["path"] for command in reference["commands"]}
        for builtin in ["reference", "context", "doctor", "changelog", "operation show", "operation list", "operation resolve"]:
            self.assertIn(builtin, paths)
        self.assertEqual(reference["driver_profile"]["base"], {"spec": "ai-native-cli-spec", "version": "v1.6.3"})
        self.assertEqual(reference["error_codes"]["E_OUTCOME_UNKNOWN"]["exit"], 6)
        self.assertEqual(reference["error_codes"]["E_DRAWING_LOCKED"]["exit"], 6)
        self.assertEqual(reference["release_readiness"]["level"], "unpublishable")
        self.assertTrue(contract["build_id"].startswith("registry-sha256:"))

    def test_generate_check_and_update(self):
        result = generate_registry(self.registry(), self.output)
        self.assertTrue(result["changed"])
        self.assertEqual(sorted(path.name for path in self.output.iterdir()),
                         ["contract-ext.json", "development-design.json", "product-generation.manifest.json", "product_contract.json", "reference.json", "skill-capabilities.md"])
        extension = json.loads((self.output / "contract-ext.json").read_text(encoding="utf-8"))
        self.assertIn("E_DRAWING_LOCKED", extension["error_codes"])
        self.assertNotIn("E_CONFLICT", extension["error_codes"], "core codes stay in the base contract")
        self.assertFalse(generate_registry(self.registry(), self.output, check=True)["changed"])
        changed = self.registry()
        changed["commands"][0]["description"] = "Changed description."
        with self.assertRaises(GenerationError) as caught:
            generate_registry(changed, self.output, check=True)
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        with self.assertRaises(GenerationError):
            generate_registry(changed, self.output)
        self.assertTrue(generate_registry(changed, self.output, update=True)["changed"])

    def test_outputs_edited_by_hand_are_never_overwritten(self):
        generate_registry(self.registry(), self.output)
        (self.output / "reference.json").write_text("{}", encoding="utf-8")
        changed = self.registry()
        changed["description"] = "Another description."
        with self.assertRaises(GenerationError) as caught:
            generate_registry(changed, self.output, update=True)
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        self.assertEqual((self.output / "reference.json").read_text(encoding="utf-8"), "{}")

    def test_unowned_files_block_generation(self):
        self.output.mkdir()
        (self.output / "reference.json").write_text("user file", encoding="utf-8")
        with self.assertRaises(GenerationError):
            generate_registry(self.registry(), self.output)
        self.assertEqual((self.output / "reference.json").read_text(encoding="utf-8"), "user file")

    def test_registry_errors_are_named(self):
        cases = []
        builtin = self.registry()
        builtin["commands"][0]["path"] = "operation purge"
        cases.append(builtin)
        label = self.registry()
        label["schemas"]["doctor"] = label["schemas"]["inspection"]
        cases.append(label)
        redefined = self.registry()
        redefined["error_codes"]["E_CONFLICT"] = {"exit": 1, "retryable": True, "description": "no"}
        cases.append(redefined)
        undeclared = self.registry()
        undeclared["commands"][1]["examples"] = ["sample-driver drawing set-title --file f --title t"]
        cases.append(undeclared)
        schema_error = self.registry()
        schema_error["commands"][0]["driver"]["effects"] = ["observe", "teleport"]
        cases.append(schema_error)
        for registry in cases:
            with self.subTest(registry=registry["commands"][0]["path"]):
                with self.assertRaises(GenerationError) as caught:
                    build_contract(registry)
                self.assertTrue(str(caught.exception))

    def test_changelog_is_embedded_and_must_match_the_version(self):
        registry = self.registry()
        registry["changelog"] = "CHANGELOG.md"
        (self.base / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-10-04\n\n### Added\n\n- first\n",
                                                encoding="utf-8")
        contract = build_contract(registry, registry_dir=self.base)
        self.assertEqual(contract["changelog"][0]["changes"]["added"], ["first"])
        (self.base / "CHANGELOG.md").write_text("# Changelog\n\n## [0.0.9] - 2026-10-01\n", encoding="utf-8")
        with self.assertRaises(GenerationError):
            build_contract(registry, registry_dir=self.base)

    def test_command_line_reports_base_envelopes(self):
        script = ROOT / "scripts" / "generate_product.py"
        registry = ROOT / "examples" / "development" / "product-registry.json"
        result = subprocess.run([sys.executable, "-B", str(script), "--registry", str(registry), "--output", str(self.output)],
                                capture_output=True, timeout=60, creationflags=HIDDEN)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(set(json.loads(result.stdout)), {"ok", "schema_version", "data", "meta"})
        result = subprocess.run([sys.executable, "-B", str(script), "--registry", str(registry)], capture_output=True, timeout=60,
                                creationflags=HIDDEN)
        response = json.loads(result.stdout)
        self.assertEqual((result.returncode, response["error"]["code"]), (2, "E_USAGE"))
        self.assertIn("next_action", response["error"]["details"])


if __name__ == "__main__":
    unittest.main()
