"""Checks for the candidate package matrix and the intentionally failing smoke stub."""

import ast
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@unittest.skipUnless(NODE, "Node.js is needed for the package evidence checker")
class PlatformDeliveryTests(unittest.TestCase):
    def test_matrix_and_smoke_failure_reporting(self):
        result = subprocess.run([NODE, "--test", "starter/common/scripts/test-platform-delivery.js"],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=HIDDEN)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unimplemented_product_smoke_refuses_to_pass(self):
        result = subprocess.run([NODE, "starter/common/scripts/smoke-product.js", "nonexistent"],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=HIDDEN)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("before publishing", result.stderr)


class GeneratorRefusalTests(unittest.TestCase):
    def test_starter_python_sources_parse_before_and_after_name_substitution(self):
        for path in (ROOT / "starter/common").rglob("*.py"):
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                ast.parse(source)
                ast.parse(source.replace("{{PACKAGE}}", "sample_driver"))

    def test_denied_hard_link_leaves_no_partial_output_or_lock(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import generate_product
        finally:
            sys.path.pop(0)
        payload = b'{"fixture":true}\n'
        artifacts = {"reference.json": payload}
        manifest = {"owner": generate_product.OWNER, "format_version": "2.0",
                    "registry_sha256": "fixture", "files": {"reference.json": generate_product.fingerprint(payload)}}
        with tempfile.TemporaryDirectory(prefix="link-refusal-") as temp:
            output = Path(temp).resolve() / "generated"
            with patch.object(generate_product, "build_artifacts", return_value=artifacts), \
                 patch.object(generate_product, "_manifest", return_value=manifest), \
                 patch.object(generate_product.os, "link", side_effect=PermissionError("hard link denied")):
                with self.assertRaises(PermissionError):
                    generate_product.generate_registry({}, output)
            self.assertEqual(list(output.iterdir()), [], "denial must leave no destination, temporary files or lock")


class BundleCoverageTests(unittest.TestCase):
    def test_committed_starter_javascript_is_in_bundle_inputs(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import build_spec_bundle
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory(prefix="bundle-js-") as temp:
            repo = Path(temp)
            relative = "starter/common/scripts/check-platform-delivery.js"
            source = repo / relative
            source.parent.mkdir(parents=True)
            payload = b'console.log("fixture");\n'
            source.write_bytes(payload)
            for args in (["init", "-q"], ["add", relative],
                         ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                          "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"]):
                subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, creationflags=HIDDEN)
            with patch.object(build_spec_bundle, "ROOT", repo), \
                 patch.object(build_spec_bundle, "required_payload", return_value={relative}):
                inputs = build_spec_bundle.committed_inputs("HEAD")
            self.assertEqual(inputs[relative], payload)

    def test_acceptance_identity_includes_starter_javascript(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from check_graduation import identity
        finally:
            sys.path.pop(0)
        self.assertIn("starter/common/scripts/check-platform-delivery.js", identity()["files"])


class LegacyReadinessTests(unittest.TestCase):
    def test_generated_reference_keeps_legacy_unpublishable_and_is_valid(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from generate_product import build_contract
            from check_spec import reference_errors
        finally:
            sys.path.pop(0)
        raw = (ROOT / "starter/common/registry.json").read_text(encoding="utf-8")
        for old, new in {"{{DESCRIPTION_JSON}}": '"Example"', "{{NAME}}": "sample-driver",
                         "{{VERSION}}": "0.1.0", "{{PROFILE}}": "file",
                         "{{PACKAGE}}": "sample_driver", "{{ENV_PREFIX}}": "SAMPLE_DRIVER"}.items():
            raw = raw.replace(old, new)
        registry = json.loads(raw)
        registry.pop("changelog", None)
        reference = build_contract(registry)["reference"]
        self.assertEqual(reference["release_readiness"]["level"], "unpublishable")
        self.assertEqual(reference["release_readiness"]["fcc_status"], "missing")
        self.assertEqual(reference_errors(reference), [])

    def test_legacy_doctor_still_reports_unpublishable_as_fail(self):
        sys.path.insert(0, str(ROOT / "packages"))
        try:
            from tool_driver_sdk.runtime import DriverCLI
        finally:
            sys.path.pop(0)
        cli = DriverCLI.__new__(DriverCLI)
        cli.reference = {"release_readiness": {"level": "unpublishable", "fcc_status": "missing", "reason": "coverage missing"}}
        cli._scope = lambda: SimpleNamespace(summary={"status": "read_only"}, grant_file="scope.json")
        cli.state_dir, cli.retain_days = Path("scratch-state"), 1
        cli._hook = lambda *_: ([{"check": "native_backend", "status": "pass", "fix": None}], None)
        cli.validator = SimpleNamespace(validate_shape=lambda *_: None)
        with patch("tool_driver_sdk.runtime.StateStore") as store:
            store.return_value.available.return_value = (True, None)
            checks = cli._doctor()["checks"]
        readiness = next(item for item in checks if item["check"] == "release_readiness")
        self.assertEqual(readiness["status"], "fail")
        self.assertIn("unpublishable", readiness["message"])


if __name__ == "__main__":
    unittest.main()
