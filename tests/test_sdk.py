"""SDK framing and real parser/adapter boundaries; adapters below are protocol fakes."""

from __future__ import annotations

import copy
import io
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from tool_driver_sdk import (
    Change, CommandResult, ContractError, ContractValidator, EndpointDispatcher, ErrorCatalog,
    Execution, HelpResult, Invocation, Outcome, Persistence, Phase, StubAdapter,
    failure, make_receipt, parse_json, serve_cli, success,
)


def fixture(name):
    return json.loads((ROOT / "examples" / "valid" / (name + ".json")).read_text(encoding="utf-8"))


class RecordingAdapter:
    def __init__(self, callback):
        self.callback, self.calls = callback, []

    def execute(self, invocation):
        self.calls.append(invocation)
        return self.callback(invocation)


class SDKTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = ContractValidator(ROOT)
        cls.public = {identity: copy.deepcopy(schema) for identity, schema in cls.validator.schemas.items()}
        cls.catalog = ErrorCatalog([
            {"code": "E_VALIDATION", "exit_code": 2, "description": "Invalid input."},
            {"code": "E_UNSUPPORTED", "exit_code": 3, "description": "No native implementation."},
            {"code": "E_OUTCOME_UNKNOWN", "exit_code": 1, "description": "Query the known request."},
            {"code": "E_TIMEOUT", "exit_code": 8, "description": "Context-dependent timeout."},
        ])

    def contract(self, *, properties=None, required=None, parameters=None, example=None, phases=None, effects=None):
        properties = properties if properties is not None else {"name": {"type": "string", "minLength": 1}}
        required = required if required is not None else ["name"]
        parameters = parameters if parameters is not None else [{"name": "--name", "location": "option", "encoding": "scalar", "input_pointer": "/name"}]
        example = example if example is not None else {"name": "sample"}
        phases = phases if phases is not None else ["observe"]
        effects = effects if effects is not None else ["observe"]
        request_id = "urn:sdk-fixture:request:1.0"
        schemas = copy.deepcopy(self.public)
        schemas[request_id] = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": request_id,
                               "type": "object", "properties": properties, "required": required, "additionalProperties": False}
        public_parameters = []
        metadata = []
        argv = ["document", "inspect"]
        for parameter in parameters:
            instance = parameter["input_pointer"]
            binding = "" if instance == "" else "/properties/" + instance.removeprefix("/")
            definition = {"name": parameter["name"], "location": parameter["location"], "binding": binding,
                          "required": instance == "" or instance.removeprefix("/") in required,
                          "description": "Synthetic parameter."}
            public_parameters.append(definition)
            metadata.append(copy.deepcopy(parameter))
            sample = example if instance == "" else example.get(instance.removeprefix("/"), "sample")
            if parameter["location"] != "positional":
                argv.append(parameter["name"])
            if parameter["encoding"] == "stdin_json":
                continue
            if parameter["encoding"] == "repeat":
                sample = sample[0] if isinstance(sample, list) and sample else "sample"
            argv.append(json.dumps(sample) if parameter["encoding"] == "json" else str(sample))
        capability = {
            "id": "document-inspect", "command": "document inspect", "description": "Synthetic protocol fixture.",
            "phases": phases, "effects": effects, "modes": ["file"], "profiles": ["core"],
            "request_schema": request_id, "result_schema": "urn:tool-driver-cli-spec:response:1.0",
            "maturity": "experimental", "limits": ["No native application is connected."],
            "environments": [{"application": "synthetic", "application_version": "not-run", "platform": "any",
                              "arch": "any", "adapter_version": "1.0.0", "mode": "file", "limitations": ["Protocol test only."]}],
            "recovery": {"atomicity": "none", "undo": False, "idempotent": False, "cancel": False},
            "evidence_refs": [], "parameters": public_parameters,
            "examples": [{"argv": argv, "description": "Test fixture only; files/stdin are supplied explicitly in tests.",
                          "phase": phases[0], "request": example}],
            "error_codes": ["E_VALIDATION", "E_UNSUPPORTED", "E_OUTCOME_UNKNOWN"],
            "extensions": {"cli": {"parameters": metadata}},
        }
        reference = {"tool": "sdk-fixture", "tool_version": "1.0.0", "spec_version": "1.0.0", "schema_version": "1.0",
                     "capabilities": [capability], "schemas": schemas,
                     "error_codes": [{"code": code, "exit_code": self.catalog.exit_for(code), "description": code}
                                     for code in ["E_VALIDATION", "E_UNSUPPORTED", "E_OUTCOME_UNKNOWN"]]}
        return {"contract_version": "1.0", "spec_version": "1.0.0", "schema_version": "1.0", "entrypoint": "sdk-fixture",
                "registry_sha256": "a" * 64, "reference": reference}

    def echo_adapter(self):
        return RecordingAdapter(lambda invocation: success(self.validator, phase=invocation.phase,
                                request_id=invocation.request_id, data={"echo": invocation.payload}))

    def receipt(self):
        return fixture("receipt-applied-unsaved")

    def call(self, contract, adapter, *argv, **kwargs):
        result = serve_cli(contract, self.validator, adapter, list(argv), **kwargs)
        if isinstance(result, CommandResult):
            self.validator.validate("response", result.envelope)
        return result

    def test_strict_utf8_json_rejects_bom_duplicates_nonfinite_and_trailing_output(self):
        for payload in [b'\xef\xbb\xbf{}', b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e400}', b'{} trailing', b'"\xff"']:
            with self.subTest(payload=payload):
                with self.assertRaises(ContractError):
                    parse_json(payload)
        self.assertEqual(parse_json('{"text":"世界"}'.encode("utf-8"))["text"], "世界")

    def test_success_preserves_all_declared_phases_and_complete_utf8_bytes(self):
        for phase in Phase:
            data = {"text": "世界"}
            if phase in {Phase.APPLY, Phase.RESULT}:
                data["receipt"] = self.receipt()
            elif phase in {Phase.SUBMIT, Phase.STATUS}:
                data["operation_status"] = fixture("status-running")
            elif phase == Phase.PLAN:
                data["plan"] = fixture("plan-estimate")
            with self.subTest(phase=phase):
                result = success(self.validator, phase=phase, request_id="caller-id", data=data)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.envelope["phase"], phase)
                self.assertIn("世界".encode(), result.to_bytes())
                self.assertFalse(result.to_bytes().startswith(b"\xef\xbb\xbf"))
                output = io.BytesIO()
                result.write_to(output)
                self.assertEqual(output.getvalue(), result.to_bytes())

    def test_result_dictionaries_are_defensive_copies(self):
        data = {"items": ["original"]}
        result = success(self.validator, phase="observe", request_id="known", data=data)
        data["items"].append("later")
        result.envelope["data"]["items"].append("another")
        self.assertEqual(result.envelope["data"]["items"], ["original"])

    def test_catalog_controls_error_exit_but_not_contextual_retryability(self):
        for retryable in [True, False]:
            result = failure(self.validator, phase="observe", request_id="known", catalog=self.catalog,
                             code="E_TIMEOUT", message="Timeout context provided by caller.", retryable=retryable, details={})
            self.assertEqual(result.exit_code, 8)
            self.assertEqual(result.envelope["error"]["retryable"], retryable)
        with self.assertRaises(ContractError):
            failure(self.validator, phase="observe", request_id="known", catalog=self.catalog,
                    code="E_UNDECLARED", message="Not declared.", retryable=False, details={})

    def test_receipt_requires_actual_outcome_and_authorization_without_default_promotion(self):
        original = self.receipt()
        outcome = Outcome(Execution.COMPLETED, Change.APPLIED, Persistence.UNSAVED, original["outcome"]["verification"])
        values = {key: value for key, value in original.items() if key != "outcome"}
        received = make_receipt(self.validator, outcome=outcome, **values)
        self.assertEqual(received["outcome"]["persistence"], "unsaved")
        self.assertEqual(received["authorization_scope_id"], original["authorization_scope_id"])
        values["authorization_scope_id"] = None
        with self.assertRaises(ContractError):
            make_receipt(self.validator, outcome=outcome, **values)
        with self.assertRaises(TypeError):
            make_receipt(self.validator, operation_id="not-enough")

    def test_partial_unknown_and_unchecked_results_cannot_be_success(self):
        for change in ["partial", "unknown"]:
            receipt = self.receipt()
            receipt["outcome"]["change"] = change
            with self.subTest(change=change), self.assertRaises(ContractError):
                success(self.validator, phase="apply", request_id="known", data={"receipt": receipt})
        receipt = self.receipt()
        receipt["outcome"]["verification"]["status"] = "incomplete"
        with self.assertRaises(ContractError):
            success(self.validator, phase="apply", request_id="known", data={"receipt": receipt})

    def test_vendored_semantics_load_portably_without_ambient_module_collision(self):
        with tempfile.TemporaryDirectory(prefix="sdk-vendor-") as directory:
            vendor = Path(directory) / "spec"
            shutil.copytree(ROOT / "schemas", vendor / "schemas")
            (vendor / "scripts").mkdir()
            for name in ["check_spec.py", "contract_io.py"]:
                shutil.copyfile(ROOT / "scripts" / name, vendor / "scripts" / name)
            sentinel = types.ModuleType("contract_io")
            with patch.dict(sys.modules, {"contract_io": sentinel}):
                loaded = ContractValidator(vendor)
                self.assertIs(sys.modules["contract_io"], sentinel)
                receipt = self.receipt()
                receipt["outcome"]["change"] = "unknown"
                with self.assertRaises(ContractError):
                    success(loaded, phase="apply", request_id="known", data={"receipt": receipt})
            self.assertFalse((vendor / "scripts" / "__pycache__").exists())

    def test_catalog_cache_tracks_content_and_keeps_prior_resources_immutable(self):
        identity = "urn:sdk-fixture:cache:1.0"
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": identity, "type": "string"}
        directory = {identity: schema}
        prior = self.validator.catalog(directory)
        schema["type"] = "integer"
        current = self.validator.catalog(directory)
        self.assertEqual(prior.resolver(identity).lookup("#").contents["type"], "string")
        self.assertEqual(current.resolver(identity).lookup("#").contents["type"], "integer")
        with self.assertRaises(ContractError):
            self.validator.validate_schema(identity, "not-an-integer", directory)

    def test_default_reference_is_a_small_index_and_detail_has_only_required_closure(self):
        contract = self.contract()
        unrelated = "urn:sdk-fixture:unrelated:1.0"
        contract["reference"]["schemas"][unrelated] = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": unrelated, "type": "object"}
        adapter = self.echo_adapter()
        index = self.call(contract, adapter, "reference")
        self.assertEqual(index.envelope["data"]["kind"], "capability_index")
        self.assertNotIn("schemas", index.envelope["data"])
        detail = self.call(contract, adapter, "reference", "--capability", "document-inspect")
        ref = detail.envelope["data"]["reference"]
        self.validator.validate_reference(ref)
        self.assertNotIn(unrelated, ref["schemas"])
        self.assertEqual(len(ref["capabilities"]), 1)
        self.assertEqual(adapter.calls, [])

    def test_scalar_alias_defaults_unicode_and_quotes_map_to_actual_adapter_payload(self):
        contract = self.contract(properties={"name": {"type": "string"}, "count": {"type": "integer", "default": 2}},
            required=["name"], parameters=[
                {"name": "--name", "location": "option", "encoding": "scalar", "input_pointer": "/name", "aliases": ["-n", "--label"], "deprecated": True},
                {"name": "--count", "location": "option", "encoding": "scalar", "input_pointer": "/count"}], example={"name": "sample", "count": 2})
        adapter = self.echo_adapter()
        value = '中文 "quote" and spaces'
        result = self.call(contract, adapter, "document", "inspect", "-n", value)
        self.assertTrue(result.envelope["ok"])
        self.assertEqual(adapter.calls[0].payload, {"name": value, "count": 2})
        self.assertIn("Deprecated", result.envelope["meta"]["notices"][0])

    def test_repeat_numeric_boolean_and_positional_codecs_are_real_parser_paths(self):
        contract = self.contract(properties={"name": {"type": "string"}, "tags": {"type": "array", "items": {"type": "integer"}},
            "enabled": {"type": "boolean"}, "ratio": {"type": "number"}}, required=["name"], parameters=[
                {"name": "name", "location": "positional", "position": 0, "encoding": "scalar", "input_pointer": "/name"},
                {"name": "--tag", "location": "option", "encoding": "repeat", "input_pointer": "/tags"},
                {"name": "--enabled", "location": "option", "encoding": "scalar", "input_pointer": "/enabled"},
                {"name": "--ratio", "location": "option", "encoding": "scalar", "input_pointer": "/ratio"}],
            example={"name": "sample", "tags": [1], "enabled": True, "ratio": 0.5})
        # Bindings refer to business field definitions, not flag spellings.
        for parameter, binding in zip(contract["reference"]["capabilities"][0]["parameters"], ["name", "tags", "enabled", "ratio"]):
            parameter["binding"] = "/properties/" + binding
        adapter = self.echo_adapter()
        result = self.call(contract, adapter, "document", "inspect", "positional", "--tag", "1", "--tag", "2", "--enabled", "false", "--ratio", "0.5")
        self.assertTrue(result.envelope["ok"])
        self.assertEqual(adapter.calls[0].payload, {"name": "positional", "tags": [1, 2], "enabled": False, "ratio": 0.5})

    def test_inline_file_and_explicit_stdin_json(self):
        for encoding in ["json", "file_json", "stdin_json"]:
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory(prefix="sdk-input-") as directory:
                contract = self.contract(parameters=[{"name": "--payload", "location": "json", "encoding": encoding, "input_pointer": ""}])
                adapter = self.echo_adapter()
                payload = '{"name":"世界"}'.encode()
                argv = ["document", "inspect", "--payload"]
                keyword = {}
                if encoding == "json":
                    argv.append(payload.decode())
                elif encoding == "file_json":
                    path = Path(directory) / "input.json"
                    path.write_bytes(payload)
                    argv.append(str(path))
                else:
                    keyword["stdin"] = io.BytesIO(payload)
                result = self.call(contract, adapter, *argv, **keyword)
                self.assertTrue(result.envelope["ok"])
                self.assertEqual(adapter.calls[0].payload, {"name": "世界"})

    def test_bad_input_and_unknown_flags_never_call_adapter(self):
        contract = self.contract(properties={"name": {"type": "string", "enum": ["valid"]}}, example={"name": "valid"})
        for argv in [["document", "inspect", "--name", "invalid"], ["document", "inspect", "--nam", "valid"],
                     ["document", "inspect", "--name", "valid", "--phase", "apply"]]:
            with self.subTest(argv=argv):
                adapter = self.echo_adapter()
                result = self.call(contract, adapter, *argv)
                self.assertFalse(result.envelope["ok"])
                self.assertEqual(result.envelope["error"]["details"]["dispatch_state"], "not_started")
                self.assertEqual(adapter.calls, [])

    def test_complex_binding_does_not_guess_missing_input_pointer(self):
        contract = self.contract()
        del contract["reference"]["capabilities"][0]["extensions"]["cli"]["parameters"][0]["input_pointer"]
        adapter = self.echo_adapter()
        self.assertFalse(self.call(contract, adapter, "document", "inspect", "--name", "sample").envelope["ok"])
        self.assertEqual(adapter.calls, [])

    def test_reserved_alias_or_codec_core_override_cannot_bypass_frontend(self):
        for changes in [{"aliases": ["--request-id"]}, {"aliases": ["-h"]}, {"required": False}, {"encoding": "shell"}]:
            with self.subTest(changes=changes):
                contract = self.contract()
                contract["reference"]["capabilities"][0]["extensions"]["cli"]["parameters"][0].update(changes)
                adapter = self.echo_adapter()
                self.assertFalse(self.call(contract, adapter, "document", "inspect", "--name", "sample").envelope["ok"])
                self.assertEqual(adapter.calls, [])

    def test_multi_phase_requires_explicit_phase_before_dispatch(self):
        contract = self.contract(phases=["observe", "verify"])
        adapter = self.echo_adapter()
        self.assertFalse(self.call(contract, adapter, "document", "inspect", "--name", "sample").envelope["ok"])
        self.assertEqual(adapter.calls, [])
        self.assertEqual(self.call(contract, adapter, "document", "inspect", "--name", "sample", "--phase", "verify").envelope["phase"], "verify")

    def test_actual_modification_requires_caller_id_but_stub_honors_catalog_exit(self):
        contract = self.contract(phases=["apply"], effects=["change"])
        adapter = RecordingAdapter(StubAdapter(self.validator, ErrorCatalog.from_reference(contract["reference"])).execute)
        rejected = self.call(contract, adapter, "document", "inspect", "--name", "sample")
        self.assertEqual(rejected.envelope["error"]["code"], "E_VALIDATION")
        self.assertEqual(adapter.calls, [])
        accepted = self.call(contract, adapter, "document", "inspect", "--name", "sample", "--request-id", "caller-known")
        self.assertEqual(accepted.envelope["error"]["code"], "E_UNSUPPORTED")
        self.assertEqual(accepted.exit_code, 3)
        self.assertEqual(adapter.calls[0].request_id, "caller-known")

    def test_adapter_exception_is_unknown_not_unstarted_and_does_not_echo_secrets(self):
        def explode(_invocation):
            raise RuntimeError("password=DO-NOT-ECHO")
        adapter = RecordingAdapter(explode)
        result = self.call(self.contract(), adapter, "document", "inspect", "--name", "sample", "--request-id", "known-before-call")
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(result.envelope["request_id"], "known-before-call")
        self.assertEqual(result.envelope["error"]["code"], "E_OUTCOME_UNKNOWN")
        self.assertEqual(result.envelope["error"]["details"]["dispatch_state"], "unknown")
        self.assertFalse(result.envelope["error"]["retryable"])
        self.assertNotIn(b"DO-NOT-ECHO", result.to_bytes())

    def test_adapter_phase_and_identity_mismatches_are_unknown_after_dispatch(self):
        for phase, request_id in [("verify", "caller"), ("observe", "another-request")]:
            with self.subTest(phase=phase, request_id=request_id):
                adapter = RecordingAdapter(lambda _inv: success(self.validator, phase=phase, request_id=request_id, data={}))
                result = self.call(self.contract(), adapter, "document", "inspect", "--name", "sample", "--request-id", "caller")
                self.assertEqual(result.envelope["request_id"], "caller")
                self.assertEqual(result.envelope["phase"], "observe")
                self.assertEqual(result.envelope["error"]["code"], "E_OUTCOME_UNKNOWN")

    def test_adapter_wrong_exit_undeclared_code_or_nonzero_success_are_unknown(self):
        for code, exit_code, ok in [("E_UNSUPPORTED", 1, False), ("E_NOT_REGISTERED", 1, False), (None, 9, True)]:
            with self.subTest(code=code, exit_code=exit_code, ok=ok):
                def corrupt(invocation):
                    value = {"ok": ok, "schema_version": "1.0", "request_id": invocation.request_id,
                             "phase": invocation.phase, "meta": {"duration_ms": 0}, "data": {}}
                    if not ok:
                        value["error"] = {"code": code, "message": "Known invalid adapter output.", "retryable": False, "details": {}}
                    return CommandResult(json.dumps(value).encode(), exit_code)
                result = self.call(self.contract(), RecordingAdapter(corrupt), "document", "inspect", "--name", "sample", "--request-id", "caller")
                self.assertEqual(result.envelope["error"]["code"], "E_OUTCOME_UNKNOWN")

    def test_nonfinite_or_nonserializable_adapter_output_is_rejected_before_any_write(self):
        for value in [float("nan"), float("inf"), object()]:
            with self.subTest(value=type(value).__name__):
                adapter = RecordingAdapter(lambda invocation: success(self.validator, phase=invocation.phase,
                    request_id=invocation.request_id, data={"value": value}))
                result = self.call(self.contract(), adapter, "document", "inspect", "--name", "sample", "--request-id", "caller")
                self.assertEqual(result.envelope["error"]["code"], "E_OUTCOME_UNKNOWN")
                output = io.BytesIO()
                result.write_to(output)
                self.assertFalse(parse_json(output.getvalue())["ok"])

    def test_modifying_observe_cannot_hide_missing_readback_receipt(self):
        contract = self.contract(effects=["change"])
        adapter = self.echo_adapter()
        result = self.call(contract, adapter, "document", "inspect", "--name", "sample", "--request-id", "known")
        self.assertEqual(result.envelope["error"]["code"], "E_OUTCOME_UNKNOWN")

    def test_partial_invalid_success_preserves_attributed_receipt(self):
        receipt = self.receipt()
        receipt["outcome"]["change"] = "partial"
        def invalid_success(invocation):
            return CommandResult(json.dumps({"ok": True, "schema_version": "1.0", "request_id": invocation.request_id,
                "phase": invocation.phase, "meta": {"duration_ms": 0}, "data": {"receipt": receipt}}).encode(), 0)
        contract = self.contract(phases=["apply"], effects=["change"])
        result = self.call(contract, RecordingAdapter(invalid_success), "document", "inspect", "--name", "sample", "--request-id", "known")
        self.assertFalse(result.envelope["ok"])
        self.assertEqual(result.envelope["data"]["receipt"]["outcome"]["change"], "partial")
        self.assertEqual(result.envelope["data"]["receipt"]["outcome"]["persistence"], "unsaved")

    def test_only_explicit_handler_objects_are_callable_and_registry_examples_never_run(self):
        dispatcher = EndpointDispatcher(self.validator, self.catalog)
        with self.assertRaises(ContractError):
            dispatcher.register("data-not-code", "observe", "os.system", effects=["observe"])
        contract = self.contract()
        contract["handler"] = "os.system"
        contract["reference"]["capabilities"][0]["examples"][0]["argv"].append("__import__('os')")
        adapter = self.echo_adapter()
        self.call(contract, adapter, "reference", "--full")
        self.assertEqual(adapter.calls, [])

    def test_missing_context_or_doctor_never_claims_native_ready(self):
        adapter = self.echo_adapter()
        for endpoint in ["context", "doctor"]:
            with self.subTest(endpoint=endpoint):
                result = self.call(self.contract(), adapter, endpoint)
                self.assertEqual(result.envelope["data"]["native"]["status"], "unsupported")
                self.assertIsNone(result.envelope["data"]["native"]["application_version"])
                self.assertFalse(result.envelope["ok"])
        self.assertEqual(adapter.calls, [])

    def test_provider_dto_is_direct_data_and_does_not_dispatch_native_adapter(self):
        adapter = self.echo_adapter()
        result = self.call(self.contract(), adapter, "doctor", doctor_provider=lambda _inv: {"ready": False, "checks": []})
        self.assertEqual(result.envelope["data"], {"ready": False, "checks": []})
        self.assertEqual(adapter.calls, [])

    def test_explicit_help_is_human_text_and_no_adapter_invocation(self):
        adapter = self.echo_adapter()
        result = self.call(self.contract(), adapter, "--help")
        self.assertIsInstance(result, HelpResult)
        self.assertIn("Bootstrap", result.text)
        self.assertEqual(adapter.calls, [])

    def test_missing_remote_schema_cannot_trigger_network_lookup(self):
        contract = self.contract()
        schema = contract["reference"]["schemas"]["urn:sdk-fixture:request:1.0"]
        schema["properties"]["name"] = {"$ref": "https://not-available.invalid/schema.json"}
        adapter = self.echo_adapter()
        with patch("socket.create_connection", side_effect=AssertionError("must stay offline")):
            result = self.call(contract, adapter, "document", "inspect", "--name", "sample")
        self.assertFalse(result.envelope["ok"])
        self.assertEqual(adapter.calls, [])


if __name__ == "__main__":
    unittest.main()
