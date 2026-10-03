"""Exercise the offline validator at its subprocess boundary, without native tools."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "validate_contract.py"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate output key: {key}")
        value[key] = item
    return value


def reject_json_constant(value):
    raise ValueError(f"non-JSON output constant: {value}")


class ConformanceCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="driver-conformance-")
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name) / "独立工作目录"
        self.cwd.mkdir()

    def invoke(self, *arguments: str, payload: bytes | None = None):
        return subprocess.run(
            [sys.executable, "-B", str(CLI), *arguments],
            input=payload,
            stdin=subprocess.DEVNULL if payload is None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            timeout=20,
            check=False,
        )

    def assert_response(self, result, expected_exit: int):
        self.assertEqual(
            result.returncode,
            expected_exit,
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}",
        )
        self.assertFalse(result.stdout.startswith(b"\xef\xbb\xbf"), "stdout has a BOM")
        self.assertNotIn(b"\x1b", result.stdout, "stdout has terminal control bytes")
        text = result.stdout.decode("utf-8", errors="strict")
        response = json.loads(
            text,
            object_pairs_hook=unique_json_object,
            parse_constant=reject_json_constant,
        )
        self.assertIsInstance(response, dict)
        self.assertIs(response["ok"], expected_exit == 0)
        self.assertEqual(response["schema_version"], "1.0")
        self.assertIsInstance(response["request_id"], str)
        self.assertTrue(response["request_id"])
        self.assertEqual(response["phase"], "verify")
        self.assertIsInstance(response["meta"], dict)
        self.assertGreaterEqual(response["meta"]["duration_ms"], 0)
        if expected_exit == 0:
            self.assertIsInstance(response["data"], dict)
            self.assertNotIn("error", response)
        else:
            self.assertIsInstance(response["error"], dict)
            self.assertTrue(response["error"]["code"].startswith("E_"))
            self.assertIs(response["error"]["retryable"], False)
            self.assertIsInstance(response["error"]["details"], dict)
        return response

    def receipt_bytes(self, value=None):
        if value is None:
            value = load_json(ROOT / "examples" / "valid" / "receipt-applied-unsaved.json")
        return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")

    def assert_stdin_rejected(self, payload: bytes):
        return self.assert_response(
            self.invoke("--schema", "receipt", "--input", "-", payload=payload),
            2,
        )

    def test_every_indexed_fixture_via_subprocess(self):
        examples = load_json(ROOT / "examples" / "index.json")["examples"]
        self.assertGreaterEqual(len(examples), 36)
        self.assertTrue(any(item["valid"] for item in examples))
        self.assertTrue(any(not item["valid"] for item in examples))
        for item in examples:
            with self.subTest(path=item["path"], schema=item["schema"]):
                result = self.invoke(
                    "--schema", item["schema"], "--input", str(ROOT / item["path"])
                )
                self.assert_response(result, 0 if item["valid"] else 2)

    def test_unicode_json_on_stdin_from_unrelated_cwd(self):
        value = load_json(ROOT / "examples" / "valid" / "receipt-applied-unsaved.json")
        value["extensions"] = {"说明": "中文工程、毫米和模型 🛠️"}
        result = self.invoke(
            "--schema", "receipt", "--input", "-", payload=self.receipt_bytes(value)
        )
        self.assert_response(result, 0)

    def test_duplicate_keys_are_rejected_in_otherwise_valid_json(self):
        original = self.receipt_bytes()
        payload = b'{"operation_id":"duplicate-first",' + original[1:]
        self.assert_stdin_rejected(payload)

    def test_nan_is_rejected_even_in_unconstrained_extensions(self):
        value = load_json(ROOT / "examples" / "valid" / "receipt-applied-unsaved.json")
        value["extensions"] = {"invalid_number": float("nan")}
        self.assert_stdin_rejected(json.dumps(value, allow_nan=True).encode("utf-8"))

    def test_utf8_bom_is_rejected(self):
        self.assert_stdin_rejected(b"\xef\xbb\xbf" + self.receipt_bytes())

    def test_invalid_utf8_is_rejected(self):
        self.assert_stdin_rejected(b'{"operation_id":"\xff"}')

    def test_multiple_json_documents_are_rejected(self):
        self.assert_stdin_rejected(self.receipt_bytes() + b"\n{}")

    def test_input_above_declared_byte_limit_is_rejected(self):
        result = self.invoke(
            "--schema", "receipt", "--input", "-", "--max-bytes", "16",
            payload=self.receipt_bytes(),
        )
        self.assert_response(result, 2)

    def test_missing_file_returns_io_error_json(self):
        result = self.invoke(
            "--schema", "receipt", "--input", str(self.cwd / "不存在的输入.json")
        )
        response = self.assert_response(result, 1)
        self.assertEqual(response["error"]["code"], "E_IO")

    def test_unresolved_parameter_binding_returns_contract_error(self):
        result = self.invoke(
            "--schema", "reference",
            "--input", str(ROOT / "examples" / "invalid" / "reference-unresolved-parameter.json"),
        )
        response = self.assert_response(result, 2)
        self.assertEqual(response["error"]["code"], "E_VALIDATION")

    def test_reference_examples_are_never_executed(self):
        value = copy.deepcopy(load_json(ROOT / "examples" / "valid" / "reference-experimental.json"))
        capability = value["capabilities"][0]
        marker = self.cwd / "must-not-be-created.txt"
        capability["command"] = "python"
        example = copy.deepcopy(capability["examples"][0])
        example["argv"] = [
            "python", "-c",
            f"from pathlib import Path; Path({str(marker)!r}).write_text('unexpected', encoding='utf-8')",
        ]
        example["description"] = "A synthetic invocation which the validator must not execute."
        capability["examples"] = [example]
        result = self.invoke(
            "--schema", "reference", "--input", "-",
            payload=json.dumps(value, ensure_ascii=False).encode("utf-8"),
        )
        self.assert_response(result, 0)
        self.assertFalse(marker.exists(), "the validator executed a reference example")

    def test_unknown_schema_returns_json_usage_error(self):
        result = self.invoke(
            "--schema", "unknown-contract-profile", "--input", "-",
            payload=self.receipt_bytes(),
        )
        self.assert_response(result, 2)
        self.assertNotIn(b"usage:", result.stderr.lower())

    def test_unknown_flag_returns_json_usage_error(self):
        result = self.invoke(
            "--schema", "receipt", "--input", "-", "--unknown-flag",
            payload=self.receipt_bytes(),
        )
        self.assert_response(result, 2)
        self.assertNotIn(b"usage:", result.stderr.lower())

    def test_unsupported_profile_option_returns_json_usage_error(self):
        result = self.invoke(
            "--schema", "receipt", "--input", "-", "--profile", "unknown-profile",
            payload=self.receipt_bytes(),
        )
        self.assert_response(result, 2)
        self.assertNotIn(b"usage:", result.stderr.lower())

    def test_nonpositive_byte_limit_returns_json_usage_error(self):
        result = self.invoke(
            "--schema", "receipt", "--input", "-", "--max-bytes", "0",
            payload=self.receipt_bytes(),
        )
        self.assert_response(result, 2)
        self.assertNotIn(b"usage:", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
