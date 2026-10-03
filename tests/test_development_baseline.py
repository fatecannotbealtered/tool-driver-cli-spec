"""Ensure development support does not silently replace the published wire contract."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DevelopmentBaselineTests(unittest.TestCase):
    def test_public_schema_bytes_and_version_match_the_recorded_release(self):
        baseline = json.loads((ROOT / "development/published-baseline.json").read_text(encoding="utf-8"))
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "1.0.0")
        self.assertEqual(baseline["spec_version"], "1.0.0")
        self.assertEqual(len(baseline["public_schemas"]), 11)
        for relative, expected in baseline["public_schemas"].items():
            with self.subTest(schema=relative):
                self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest(), expected)

    def test_development_registry_is_not_a_public_instance_contract(self):
        path = ROOT / "schemas/product-registry.schema.json"
        declaration = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(declaration["x-development-only"])
        result = subprocess.run([sys.executable, str(ROOT / "scripts/validate_contract.py"), "--schema", "product-registry", "--input", "-"], input=b"{}", capture_output=True, timeout=15)
        response = json.loads(result.stdout)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(response["ok"])
        self.assertIn("development", response["error"]["message"])


if __name__ == "__main__":
    unittest.main()
