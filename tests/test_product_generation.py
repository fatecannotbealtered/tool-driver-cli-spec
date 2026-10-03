"""Generation ownership, drift and data-only compilation at the CLI boundary."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from generate_product import (
    ARTIFACT_NAMES, MANIFEST, GenerationError, build_artifacts, build_contract,
    generate_registry, load_registry,
)


class ProductGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="product-generation-")
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.output = self.work / "generated"
        self.registry = load_registry(ROOT / "examples/development/product-registry.json")

    def command(self, value=None):
        registry = self.registry if value is None else value
        return next(item for item in registry["commands"] if item["path"] == "native inspect")

    def test_runtime_and_reference_share_one_parameter_declaration(self):
        contract = build_contract(self.registry)
        self.assertEqual(contract["spec_version"], "1.0.0")
        self.assertEqual(contract["reference"]["tool_version"], "0.1.0")
        command = self.command()
        capability = next(item for item in contract["reference"]["capabilities"]
                          if item["command"] == command["path"])
        self.assertEqual(capability["profiles"], ["core"])
        self.assertEqual(capability["maturity"], "draft")
        self.assertEqual(capability["parameters"][0]["binding"], command["parameters"][0]["binding"])
        codec = capability["extensions"]["cli"]["parameters"][0]
        self.assertEqual(codec["input_pointer"], "/target")
        self.assertEqual(codec["encoding"], "scalar")
        self.assertEqual(codec["aliases"], ["-t"])
        self.assertNotIn("encoding", capability["parameters"][0])
        self.assertIn("urn:tool-driver-cli-spec:response:1.0", contract["reference"]["schemas"])
        self.assertIn("urn:tool-driver-cli-spec:common:1.0", contract["reference"]["schemas"])

    def test_generation_is_deterministic_and_an_owned_repeat_is_noop(self):
        expected = build_artifacts(self.registry)
        self.assertEqual(expected, build_artifacts(copy.deepcopy(self.registry)))
        first = generate_registry(self.registry, self.output)
        self.assertTrue(first["changed"])
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.output.iterdir()}
        second = generate_registry(self.registry, self.output)
        self.assertFalse(second["changed"])
        self.assertEqual(before, {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                                 for path in self.output.iterdir()})
        other = self.work / "other"
        generate_registry(self.registry, other)
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.output.iterdir()},
            {p.name: p.read_bytes() for p in other.iterdir()},
        )

    def test_check_is_read_only_and_detects_registry_drift(self):
        absent = self.work / "not-created-by-check"
        with self.assertRaises(GenerationError):
            generate_registry(self.registry, absent, check=True)
        self.assertFalse(absent.exists())
        generate_registry(self.registry, self.output)
        changed = copy.deepcopy(self.registry)
        changed["description"] = "A reviewed development description change."
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.output.iterdir()}
        with self.assertRaises(GenerationError):
            generate_registry(changed, self.output, check=True)
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                                 for p in self.output.iterdir()})
        with self.assertRaises(GenerationError):
            generate_registry(changed, self.output)
        self.assertTrue(generate_registry(changed, self.output, update=True)["changed"])
        self.assertFalse(generate_registry(changed, self.output, check=True)["changed"])

    def test_unowned_files_are_not_adopted_or_overwritten(self):
        self.output.mkdir()
        protected = self.output / "reference.json"
        protected.write_bytes(b"someone else's file\n")
        unrelated = self.output / "notes.txt"
        unrelated.write_text("keep me", encoding="utf-8")
        with self.assertRaises(GenerationError):
            generate_registry(self.registry, self.output, update=True)
        self.assertEqual(protected.read_bytes(), b"someone else's file\n")
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep me")
        self.assertFalse((self.output / MANIFEST).exists())

    def test_update_refuses_modified_owned_files(self):
        generate_registry(self.registry, self.output)
        protected = self.output / "help.txt"
        protected.write_text("a human edit", encoding="utf-8")
        with self.assertRaises(GenerationError):
            generate_registry(self.registry, self.output, update=True)
        self.assertEqual(protected.read_text(encoding="utf-8"), "a human edit")

    def test_missing_input_pointer_and_overlapping_bindings_are_rejected(self):
        value = copy.deepcopy(self.registry)
        del self.command(value)["parameters"][0]["input_pointer"]
        with self.assertRaises(GenerationError):
            build_contract(value)
        value = copy.deepcopy(self.registry)
        parameter = copy.deepcopy(self.command(value)["parameters"][0])
        parameter.update(name="--whole-request", binding="", encoding="json",
                         input_pointer="", aliases=[])
        self.command(value)["parameters"].append(parameter)
        with self.assertRaises(GenerationError):
            build_contract(value)

    def test_control_flags_and_unverified_maturity_are_not_hidden(self):
        for alias in ["--phase", "--request-id", "--capability"]:
            with self.subTest(alias=alias):
                value = copy.deepcopy(self.registry)
                self.command(value)["parameters"][0]["aliases"] = [alias]
                with self.assertRaises(GenerationError):
                    build_contract(value)
        value = copy.deepcopy(self.registry)
        self.command(value)["maturity"] = "verified"
        with self.assertRaises(GenerationError):
            build_contract(value)

    def test_unresolved_refs_and_public_redefinition_are_rejected(self):
        value = copy.deepcopy(self.registry)
        request_id = self.command(value)["request_schema"]
        value["schemas"][request_id]["$ref"] = "https://invalid.example/schema.json"
        with self.assertRaises(GenerationError):
            build_contract(value)
        value = copy.deepcopy(self.registry)
        identifier = "urn:tool-driver-cli-spec:response:1.0"
        value["schemas"][identifier] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": identifier, "type": "object",
        }
        with self.assertRaises(GenerationError):
            build_contract(value)

    def test_bad_schema_and_incompatible_or_unknown_codecs_are_rejected(self):
        value = copy.deepcopy(self.registry)
        request_id = self.command(value)["request_schema"]
        value["schemas"][request_id]["type"] = "not-a-json-schema-type"
        with self.assertRaises(GenerationError):
            build_contract(value)
        for encoding in ["evaluate", "repeat"]:
            with self.subTest(encoding=encoding):
                value = copy.deepcopy(self.registry)
                self.command(value)["parameters"][0]["encoding"] = encoding
                with self.assertRaises(GenerationError):
                    build_contract(value)
        value = copy.deepcopy(self.registry)
        request_id = self.command(value)["request_schema"]
        value["schemas"][request_id]["properties"]["target"]["type"] = ["string", "null"]
        with self.assertRaises(GenerationError):
            build_contract(value)
        value = copy.deepcopy(self.registry)
        command = copy.deepcopy(self.command(value))
        command.update(id="conflicting-group", path="native")
        command["examples"][0]["argv"] = ["native", "--target", "object-01"]
        value["commands"].append(command)
        with self.assertRaises(GenerationError):
            build_contract(value)

    def test_sdk_preserves_quoted_unicode_and_uses_generated_input_declaration(self):
        packages = ROOT / "packages"
        if str(packages) not in sys.path:
            sys.path.insert(0, str(packages))
        from tool_driver_sdk import ContractValidator, ErrorCatalog, serve_cli, success
        contract = build_contract(self.registry)
        validator = ContractValidator(ROOT)
        catalog = ErrorCatalog.from_reference(contract["reference"])
        calls = []

        class Adapter:
            def execute(self, invocation):
                calls.append(invocation)
                return success(
                    validator, phase=invocation.phase, request_id=invocation.request_id,
                    data={"target": invocation.payload["target"], "observations": []},
                )

        target = '中文对象 "quoted" \\path with spaces'
        result = serve_cli(contract, validator, Adapter(),
                           ["native", "inspect", "-t", target])
        self.assertEqual(result.exit_code, 0, result.envelope)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].payload, {"target": target})
        self.assertEqual(result.envelope["data"]["target"], target)
        declared = next(cap for cap in contract["reference"]["capabilities"]
                        if cap["command"] == "native inspect")
        self.assertEqual(declared["parameters"][0]["binding"], "/properties/target")
        self.assertEqual(declared["extensions"]["cli"]["parameters"][0]["input_pointer"], "/target")

    def test_generated_module_and_examples_never_execute_registry_text(self):
        value = copy.deepcopy(self.registry)
        marker = self.work / "must-not-exist"
        code = f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')"
        value["entrypoint"] = "sample-driver'''\n" + code + "\n#"
        value["description"] = "A description containing ''' and source text: " + code
        self.command(value)["description"] += "\n" + code
        self.command(value)["examples"][0]["argv"].append(code)
        generate_registry(value, self.output)
        script = (
            "import runpy; "
            f"ns=runpy.run_path({str(self.output / 'product_runtime.py')!r}); "
            "data=ns['load_contract'](); "
            "assert data['entrypoint']==ns['ENTRYPOINT']"
        )
        result = subprocess.run([sys.executable, "-B", "-c", script],
                                cwd=self.work, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertFalse(marker.exists())
        value["commands"][0]["handler"] = code
        with self.assertRaises(GenerationError):
            build_contract(value)

    def test_cli_generate_and_check_from_an_unrelated_working_directory(self):
        registry_file = self.work / "registry.json"
        registry_file.write_text(json.dumps(self.registry, ensure_ascii=False), encoding="utf-8")
        command = [
            sys.executable, "-B", str(SCRIPTS / "generate_product.py"),
            "--registry", str(registry_file), "--output", str(self.output),
        ]
        for suffix in [[], ["--check"]]:
            result = subprocess.run(command + suffix, cwd=self.work, capture_output=True, timeout=15)
            response = json.loads(result.stdout.decode("utf-8"))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(response["ok"])
            self.assertEqual(response["phase"], "verify")
        self.assertEqual(set(json.loads((self.output / MANIFEST).read_text())["files"]), ARTIFACT_NAMES)


if __name__ == "__main__":
    unittest.main()
