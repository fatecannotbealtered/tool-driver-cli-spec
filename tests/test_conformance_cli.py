"""The offline validator at its subprocess boundary: base envelopes, exit codes, every indexed fixture."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "validate_contract.py"
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
sys.path.insert(0, str(ROOT / "scripts"))
from validate_contract import instance_schemas, validate_value  # noqa: E402


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def strict(text: str):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate output key: {key}")
            value[key] = item
        return value

    def constant(value):
        raise ValueError(f"non-JSON output constant: {value}")

    return json.loads(text, object_pairs_hook=unique, parse_constant=constant)


class ConformanceCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="driver-conformance-")
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name) / "独立工作目录"
        self.cwd.mkdir()

    def invoke(self, *arguments: str, payload: bytes | None = None):
        return subprocess.run([sys.executable, "-B", str(CLI), *arguments], input=payload,
                              stdin=subprocess.DEVNULL if payload is None else None, capture_output=True, cwd=self.cwd,
                              timeout=30, check=False, creationflags=HIDDEN)

    def assert_response(self, result, expected_exit: int):
        self.assertEqual(result.returncode, expected_exit, f"stdout={result.stdout!r}\nstderr={result.stderr!r}")
        self.assertFalse(result.stdout.startswith(b"\xef\xbb\xbf"), "stdout has a BOM")
        self.assertNotIn(b"\x1b", result.stdout, "stdout has terminal control bytes")
        response = strict(result.stdout.decode("utf-8", errors="strict"))
        self.assertEqual(set(response), {"ok", "schema_version", "meta", "data" if expected_exit == 0 else "error"})
        self.assertIs(response["ok"], expected_exit == 0)
        self.assertEqual(response["schema_version"], "1.0")
        self.assertEqual(set(response["meta"]), {"duration_ms"})
        if expected_exit:
            self.assertEqual(set(response["error"]), {"code", "message", "retryable", "details"})
            self.assertIs(response["error"]["retryable"], False)
            self.assertIn("next_action", response["error"]["details"])
        return response

    def test_every_indexed_fixture_in_process(self):
        examples = load_json(ROOT / "examples" / "index.json")["examples"]
        self.assertGreaterEqual(len(examples), 150)
        for item in examples:
            with self.subTest(path=item["path"]):
                errors = validate_value(item["schema"], load_json(ROOT / item["path"]))
                self.assertEqual(not errors, item["valid"], errors)

    def test_a_sample_of_fixtures_via_subprocess(self):
        sample = ["examples/valid/response-applied-unsaved.json", "examples/invalid/response-partial-as-success.json",
                  "examples/valid/reference-beta.json", "examples/invalid/reference-core-code-changed.json",
                  "examples/valid/context-connected.json", "examples/invalid/scope-deliver-without-dangerous.json"]
        index = {item["path"]: item for item in load_json(ROOT / "examples" / "index.json")["examples"]}
        for path in sample:
            with self.subTest(path=path):
                item = index[path]
                response = self.assert_response(self.invoke("--schema", item["schema"].removesuffix(".schema.json"),
                                                             "--input", str(ROOT / path)), 0 if item["valid"] else 2)
                if not item["valid"]:
                    self.assertEqual(response["error"]["code"], "E_VALIDATION")
                    self.assertTrue(response["error"]["details"]["errors"])

    def test_stdin_input_and_size_limit(self):
        payload = (ROOT / "examples" / "valid" / "receipt-applied-unsaved.json").read_bytes()
        self.assert_response(self.invoke("--schema", "receipt", "--input", "-", payload=payload), 0)
        response = self.assert_response(self.invoke("--schema", "receipt", "--input", "-", "--max-bytes", "10", payload=payload), 2)
        self.assertIn("limit", response["error"]["message"])

    def test_bom_duplicate_keys_and_constants_are_rejected(self):
        for payload in [b"\xef\xbb\xbf{}", b'{"a":1,"a":2}', b'{"a":NaN}', b"{", b'{"a":1}{"b":2}']:
            with self.subTest(payload=payload):
                self.assert_response(self.invoke("--schema", "receipt", "--input", "-", payload=payload), 2)

    def test_unknown_common_and_development_schemas_are_usage_errors(self):
        for schema in ["missing", "common", "product-registry"]:
            with self.subTest(schema=schema):
                response = self.assert_response(self.invoke("--schema", schema, "--input", "-", payload=b"{}"), 2)
                self.assertEqual(response["error"]["code"], "E_USAGE")
        self.assertIn("reference", instance_schemas())
        self.assertNotIn("common", instance_schemas())

    def test_missing_file_is_io_failure(self):
        response = self.assert_response(self.invoke("--schema", "receipt", "--input", str(self.cwd / "missing.json")), 1)
        self.assertEqual(response["error"]["code"], "E_IO")

    def test_bad_arguments_are_usage_errors(self):
        response = self.assert_response(self.invoke("--schema", "receipt"), 2)
        self.assertEqual(response["error"]["code"], "E_USAGE")
        response = self.assert_response(self.invoke("--schema", "receipt", "--input", "-", "--bogus", payload=b"{}"), 2)
        self.assertEqual(response["error"]["code"], "E_USAGE")

    def test_errors_name_paths_not_values(self):
        value = load_json(ROOT / "examples" / "valid" / "receipt-applied-unsaved.json")
        value["outcome"]["execution"] = "SECRET-VALUE-done"
        response = self.assert_response(self.invoke("--schema", "receipt", "--input", "-",
                                                     payload=json.dumps(value).encode("utf-8")), 2)
        text = json.dumps(response)
        self.assertNotIn("SECRET-VALUE", text)
        self.assertIn("outcome/execution", text)


if __name__ == "__main__":
    unittest.main()
