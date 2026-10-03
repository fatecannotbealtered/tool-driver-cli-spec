"""Declaration-driven CLI parsing and dispatch to caller-supplied adapter objects."""

from __future__ import annotations

import argparse
import math
import os
import re
import stat
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urldefrag, urljoin

from .messages import CommandResult, ErrorCatalog, HelpResult, failure, success, validate_result
from .models import Invocation, Phase
from .validation import ContractError, ContractValidator, clone_json, json_bytes, parse_json

RESERVED_FLAGS = {"--phase", "--request-id", "--help", "-h", "--full", "--index", "--capability"}
MODIFYING_EFFECTS = {"change", "persist", "configure", "deliver", "physical"}
RUNTIME_CODES = {"E_VALIDATION", "E_UNSUPPORTED", "E_OUTCOME_UNKNOWN"}


def _bootstrap_catalog():
    return ErrorCatalog([{"code": "E_VALIDATION", "exit_code": 2, "description": "Invalid SDK configuration or input."},
                         {"code": "E_UNSUPPORTED", "exit_code": 2, "description": "No supported endpoint."},
                         {"code": "E_OUTCOME_UNKNOWN", "exit_code": 1, "description": "Dispatched outcome requires reconciliation."}])


def _rejected(validator, catalog, request_id, message, phase=Phase.OBSERVE):
    return failure(validator, phase=phase, request_id=request_id, catalog=catalog,
                   code="E_VALIDATION", message=message, retryable=False,
                   details={"dispatch_state": "not_started"})


def _unknown(validator, catalog, invocation, candidate=None):
    data = None
    if isinstance(candidate, CommandResult):
        try:
            attributed = candidate.envelope
            if attributed["request_id"] != invocation.request_id or attributed["phase"] != invocation.phase:
                raise ContractError("adapter output is not attributed to this invocation")
            receipt = attributed.get("data", {}).get("receipt")
            if receipt is not None:
                data = {"receipt": validator.validate("receipt", receipt)}
        except Exception:
            pass
    return failure(validator, phase=invocation.phase, request_id=invocation.request_id,
                   catalog=catalog, code="E_OUTCOME_UNKNOWN", message="Adapter outcome could not be established.",
                   retryable=False, data=data,
                   details={"dispatch_state": "unknown", "capability_id": invocation.capability_id,
                            "request_id": invocation.request_id,
                            "recovery_direction": "Query the backend using this known request ID before considering another modification.",
                            "limitations": ["The SDK cannot invent a missing native receipt, target observation or persistent operation mapping."]})


@dataclass(frozen=True)
class _Endpoint:
    handler: object
    effects: tuple[str, ...]


class EndpointDispatcher:
    def __init__(self, validator: ContractValidator, catalog: ErrorCatalog):
        self.validator, self.catalog = validator, catalog
        self._endpoints = {}

    def register(self, capability_id, phase, handler, *, effects):
        key = (capability_id, Phase(phase))
        if not isinstance(capability_id, str) or not capability_id or not callable(handler) or key in self._endpoints:
            raise ContractError("endpoints need explicit unique callable handlers")
        allowed = {"observe", "session", "artifact", *MODIFYING_EFFECTS}
        if isinstance(effects, str) or not effects or any(effect not in allowed for effect in effects):
            raise ContractError("endpoint effects must be an explicit list of supported effects")
        self._endpoints[key] = _Endpoint(handler, tuple(effects))

    def dispatch(self, invocation: Invocation) -> CommandResult:
        endpoint = self._endpoints.get((invocation.capability_id, invocation.phase))
        if endpoint is None:
            return failure(self.validator, phase=invocation.phase, request_id=invocation.request_id,
                           catalog=self.catalog, code="E_UNSUPPORTED", message="No endpoint is registered.",
                           retryable=False, details={"dispatch_state": "not_started"})
        actual_modification = invocation.phase not in {Phase.PLAN, Phase.SUBMIT, Phase.STATUS} and MODIFYING_EFFECTS.intersection(endpoint.effects)
        if actual_modification and not invocation.caller_known_request_id:
            return _rejected(self.validator, self.catalog, invocation.request_id,
                             "A caller-known request ID is required before dispatch.", invocation.phase)
        try:
            cloned = Invocation(invocation.capability_id, invocation.phase, invocation.request_id,
                                clone_json(invocation.payload), invocation.caller_known_request_id)
        except ContractError:
            return _rejected(self.validator, self.catalog, invocation.request_id,
                             "Invocation input cannot be represented as JSON.", invocation.phase)
        candidate = None
        try:
            candidate = endpoint.handler(cloned)
            result = validate_result(self.validator, candidate, self.catalog, cloned)
            if actual_modification and result.envelope["ok"]:
                # Apply/result readback obligations also apply to modifying observe/verify endpoints.
                self.validator.validate("response", {**result.envelope, "phase": Phase.APPLY.value})
            return result
        except Exception:
            return _unknown(self.validator, self.catalog, cloned, candidate)


class StubAdapter:
    """An explicitly unavailable adapter; its invocation performs no native work."""
    def __init__(self, validator: ContractValidator, catalog: ErrorCatalog):
        self.validator, self.catalog = validator, catalog

    def execute(self, invocation: Invocation) -> CommandResult:
        return failure(self.validator, phase=invocation.phase, request_id=invocation.request_id,
                       catalog=self.catalog, code="E_UNSUPPORTED", message="Native adapter is not configured.",
                       retryable=False, details={"dispatch_state": "not_started", "native_available": False})


class _Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, add_help=False, allow_abbrev=False, **kwargs)

    def error(self, _message):
        raise ContractError("CLI arguments do not satisfy the declared command syntax")


def _controls(parser):
    parser.add_argument("--phase", choices=[phase.value for phase in Phase], default=argparse.SUPPRESS)
    parser.add_argument("--request-id", default=argparse.SUPPRESS)


def _pointer_parts(pointer):
    if pointer == "":
        return []
    if not isinstance(pointer, str) or not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise ContractError("an explicit JSON instance pointer is required")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _set_value(payload, pointer, value):
    parts = _pointer_parts(pointer)
    if not parts:
        if not isinstance(value, dict):
            raise ContractError("a whole-request JSON value must be an object")
        return value
    target = payload
    for key in parts[:-1]:
        existing = target.setdefault(key, {})
        if not isinstance(existing, dict):
            raise ContractError("this codec cannot combine overlapping instance paths")
        target = existing
    target[parts[-1]] = value
    return payload


def _bound_schema(validator, reference, capability, parameter):
    catalog = validator.catalog(reference["schemas"])
    resolver = catalog.resolver(capability["request_schema"])
    resolved = resolver.lookup("#" + quote(parameter["binding"], safe="/~"))
    value = resolved.contents
    for _ in range(32):
        if not isinstance(value, dict) or "$ref" not in value:
            return value
        resolved = resolved.resolver.lookup(value["$ref"])
        value = resolved.contents
    raise ContractError("parameter Schema reference depth exceeds this codec's bound")


def _scalar(raw, schema):
    if not isinstance(schema, dict):
        raise ContractError("scalar parameters require an explicitly typed Schema")
    kind = schema.get("type")
    if kind == "string":
        return raw
    if kind == "integer":
        if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", raw):
            raise ContractError("integer parameter has invalid syntax")
        return int(raw)
    if kind == "number":
        if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", raw):
            raise ContractError("number parameter has invalid syntax")
        try:
            value = float(raw)
        except ValueError as exc:
            raise ContractError("number parameter has invalid syntax") from exc
        if not math.isfinite(value):
            raise ContractError("numeric parameter must be finite")
        return value
    if kind == "boolean" and raw in {"true", "false"}:
        return raw == "true"
    raise ContractError("this scalar type requires an explicit JSON encoding")


def _file_json(path, limit):
    location = Path(path)
    if not stat.S_ISREG(location.stat().st_mode):
        raise ContractError("explicit JSON file input must be a regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(location, flags), "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ContractError("JSON file changed while opening")
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ContractError("JSON file input exceeds the declared size limit")
    return parse_json(payload)


def _compile(validator, reference, entrypoint):
    parser = _Parser(prog=entrypoint, description="Declared tool driver commands; native availability is checked separately.",
                     epilog="Bootstrap: reference [--index | --full | --capability ID], context, doctor.")
    _controls(parser)
    tree = {(): parser}
    subparsers = {}
    leaves = {}
    codecs = {}
    stdin_count = {}
    for capability in reference["capabilities"]:
        words = tuple(capability["command"].split())
        if not words or words[0] in {"reference", "context", "doctor"}:
            if words in {("context",), ("doctor",)}:
                continue
            raise ContractError("native commands cannot replace bootstrap endpoints")
        for depth, word in enumerate(words):
            prefix = words[:depth]
            if prefix in leaves:
                raise ContractError("a command cannot be both an endpoint and a group")
            if prefix not in subparsers:
                subparsers[prefix] = tree[prefix].add_subparsers(dest=f"_group_{depth}", parser_class=_Parser)
            current = words[:depth + 1]
            if current not in tree:
                tree[current] = subparsers[prefix].add_parser(word, description=capability["description"])
                _controls(tree[current])
        if words in leaves:
            raise ContractError("command paths must be unique")
        leaves[words] = capability
        leaf = tree[words]
        leaf.set_defaults(_capability_id=capability["id"])
        public = {(parameter["location"], parameter["name"]): parameter for parameter in capability["parameters"]}
        metadata = capability.get("extensions", {}).get("cli", {}).get("parameters", [])
        metadata_keys = [(item["location"], item["name"]) for item in metadata]
        if len(metadata_keys) != len(set(metadata_keys)) or set(metadata_keys) != set(public):
            raise ContractError("every public parameter needs explicit CLI codec metadata")
        used_flags, used_pointers, positions = set(), [], []
        compiled = []
        stdin_count[capability["id"]] = 0
        for index, metadata_item in enumerate(metadata):
            if set(metadata_item) - {"name", "location", "encoding", "input_pointer", "position", "aliases", "deprecated"}:
                raise ContractError("CLI codec metadata cannot override public parameter definitions")
            key = (metadata_item["location"], metadata_item["name"])
            if key not in public:
                raise ContractError("CLI codec does not refer to a public parameter")
            parameter = {**public[key], **metadata_item}
            if ("aliases" in parameter and (not isinstance(parameter["aliases"], list) or any(not isinstance(alias, str) for alias in parameter["aliases"]))) or ("deprecated" in parameter and not isinstance(parameter["deprecated"], bool)):
                raise ContractError("CLI alias/deprecation metadata has invalid types")
            pointer = parameter.get("input_pointer")
            parts = _pointer_parts(pointer)
            if any(parts[:len(previous)] == previous or previous[:len(parts)] == parts for previous in used_pointers):
                raise ContractError("codec instance paths must not overlap")
            used_pointers.append(parts)
            encoding = parameter.get("encoding")
            if encoding not in {"scalar", "repeat", "json", "file_json", "stdin_json"}:
                raise ContractError("unsupported parameter encoding")
            destination = f"_value_{index}"
            options = {"default": argparse.SUPPRESS, "help": parameter["description"]}
            if parameter["location"] == "positional":
                if parameter.get("aliases") or encoding == "stdin_json":
                    raise ContractError("this positional codec does not support aliases or stdin triggers")
                position = parameter.get("position")
                if type(position) is not int:
                    raise ContractError("positionals need explicit continuous positions")
                positions.append(position)
                if encoding == "repeat":
                    options["nargs"] = "+" if parameter["required"] else "*"
                elif not parameter["required"]:
                    options["nargs"] = "?"
                arguments = [destination]
            elif parameter["location"] in {"option", "json"}:
                arguments = [parameter["name"], *parameter.get("aliases", [])]
                if any(not isinstance(flag, str) or not re.fullmatch(r"(?:--[A-Za-z][A-Za-z0-9_-]*|-[A-Za-z])", flag) or flag in RESERVED_FLAGS or flag in used_flags for flag in arguments):
                    raise ContractError("options and aliases must not collide with SDK controls")
                used_flags.update(arguments)
                options.update(dest=destination, required=parameter["required"])
                if encoding == "repeat":
                    options["action"] = "append"
                elif encoding == "stdin_json":
                    options["action"] = "store_true"
                    stdin_count[capability["id"]] += 1
            else:
                raise ContractError("unsupported parameter location")
            parameter["_dest"] = destination
            parameter["_schema"] = _bound_schema(validator, reference, capability, parameter)
            compiled.append((parameter, arguments, options))
        if sorted(positions) != list(range(len(positions))) or stdin_count[capability["id"]] > 1:
            raise ContractError("positionals or stdin codecs are ambiguous")
        positional = sorted((item for item in compiled if item[0]["location"] == "positional"), key=lambda item: item[0]["position"])
        for parameter, arguments, options in positional + [item for item in compiled if item[0]["location"] != "positional"]:
            leaf.add_argument(*arguments, **options)
        codecs[capability["id"]] = [parameter for parameter, _, _ in compiled]
    return parser, tree, codecs


def _request(namespace, parameters, max_input_bytes, stdin):
    payload = {}
    notices = []
    for parameter in parameters:
        if not hasattr(namespace, parameter["_dest"]):
            bound = parameter["_schema"]
            if isinstance(bound, dict) and "default" in bound:
                payload = _set_value(payload, parameter["input_pointer"], clone_json(bound["default"]))
            continue
        raw = getattr(namespace, parameter["_dest"])
        encoding = parameter["encoding"]
        if encoding == "scalar":
            value = _scalar(raw, parameter["_schema"])
        elif encoding == "repeat":
            bound = parameter["_schema"]
            if not isinstance(bound, dict) or bound.get("type") != "array":
                raise ContractError("repeat encoding requires an array Schema")
            value = [_scalar(item, bound.get("items")) for item in raw]
        elif encoding == "json":
            encoded = raw.encode("utf-8")
            if len(encoded) > max_input_bytes:
                raise ContractError("inline JSON exceeds its size limit")
            value = parse_json(encoded)
        elif encoding == "file_json":
            value = _file_json(raw, max_input_bytes)
        else:
            stream = sys.stdin.buffer if stdin is None else stdin
            encoded = stream.read(max_input_bytes + 1)
            if len(encoded) > max_input_bytes:
                raise ContractError("explicit stdin JSON exceeds its size limit")
            value = parse_json(encoded)
        payload = _set_value(payload, parameter["input_pointer"], value)
        if parameter.get("deprecated"):
            notices.append("Deprecated parameter: " + parameter["name"])
    return payload, notices


def _reference_detail(validator, reference, capability_id):
    selected = [capability for capability in reference["capabilities"] if capability["id"] == capability_id]
    if not selected:
        raise ContractError("unknown capability ID")
    detail = clone_json(reference)
    detail["capabilities"] = selected
    resource_owners = {}
    nodes = {}
    for owner, schema in reference["schemas"].items():
        nodes[owner] = list(validator._semantic.schema_nodes(schema, owner))
        resource_owners[owner] = owner
        for _, base, node in nodes[owner]:
            if isinstance(node, dict) and "$id" in node:
                resource_owners[base] = owner
    pending = [selected[0]["request_schema"], selected[0]["result_schema"]]
    included = set()
    while pending:
        identity = pending.pop()
        owner = resource_owners.get(identity)
        if owner is None:
            raise ContractError("discovered Schema reference is not in the offline directory")
        if owner in included:
            continue
        included.add(owner)
        for _, base, node in nodes[owner]:
            if not isinstance(node, dict):
                continue
            for key in ("$ref", "$dynamicRef"):
                if key in node:
                    uri = base + node[key] if node[key].startswith("#") else urljoin(base, node[key])
                    pending.append(urldefrag(uri)[0])
    detail["schemas"] = {identity: reference["schemas"][identity] for identity in sorted(included)}
    detail["error_codes"] = [entry for entry in reference["error_codes"] if entry["code"] in selected[0]["error_codes"]]
    return validator.validate_reference(detail)


def serve_cli(contract, validator: ContractValidator, adapter, argv, context_provider=None, doctor_provider=None,
              *, max_input_bytes=8 * 1024 * 1024, stdin=None) -> CommandResult | HelpResult:
    """Return complete bytes/results; the caller chooses its binary stdout stream."""
    catalog = _bootstrap_catalog()
    request_id = str(uuid.uuid4())
    phase = Phase.OBSERVE
    invocation = None
    try:
        if type(max_input_bytes) is not int or max_input_bytes <= 0:
            raise ContractError("input limit must be positive")
        reference = validator.validate_reference(contract["reference"])
        if contract.get("contract_version") != "1.0" or contract.get("spec_version") != reference["spec_version"] or contract.get("schema_version") != reference["schema_version"]:
            raise ContractError("product contract and public reference versions disagree")
        configured_catalog = ErrorCatalog.from_reference(reference)
        for code in RUNTIME_CODES:
            configured_catalog.exit_for(code)
        catalog = configured_catalog
        entrypoint = contract["entrypoint"]
        if not isinstance(entrypoint, str) or not entrypoint:
            raise ContractError("an explicit executable entrypoint is required")
        arguments = list(argv)
        if any(not isinstance(argument, str) for argument in arguments):
            raise ContractError("argv must contain strings")
        command_index = 0
        controls_seen = set()
        index = 0
        while index < len(arguments) and arguments[index] != "--":
            token = arguments[index]
            option = token.split("=", 1)[0]
            if option in {"--request-id", "--phase"}:
                if option in controls_seen:
                    raise ContractError("SDK controls may only be supplied once")
                controls_seen.add(option)
                value = token.split("=", 1)[1] if "=" in token else (arguments[index + 1] if index + 1 < len(arguments) else "")
                if option == "--request-id" and value:
                    request_id = value
                index += 1 if "=" in token else 2
                if command_index == index - (1 if "=" in token else 2):
                    command_index = index
                continue
            index += 1
        if command_index < len(arguments) and arguments[command_index] in {"reference", "context", "doctor"}:
            name = arguments[command_index]
            bootstrap = _Parser(prog=entrypoint + " " + name)
            _controls(bootstrap)
            if name == "reference":
                selectors = bootstrap.add_mutually_exclusive_group()
                selectors.add_argument("--index", action="store_true")
                selectors.add_argument("--full", action="store_true")
                selectors.add_argument("--capability")
            if "--help" in arguments or "-h" in arguments:
                return HelpResult(bootstrap.format_help())
            namespace = bootstrap.parse_args(arguments[:command_index] + arguments[command_index + 1:])
            request_id = getattr(namespace, "request_id", request_id)
            if getattr(namespace, "phase", Phase.OBSERVE) != Phase.OBSERVE:
                raise ContractError("bootstrap endpoints are read-only observe requests")
            invocation = Invocation(name, Phase.OBSERVE, request_id, {}, hasattr(namespace, "request_id"))
            if name == "reference":
                if namespace.full:
                    data = {"reference": reference}
                elif namespace.capability:
                    data = {"reference": _reference_detail(validator, reference, namespace.capability)}
                else:
                    data = {"kind": "capability_index", "tool": reference["tool"], "tool_version": reference["tool_version"],
                            "spec_version": reference["spec_version"], "schema_version": reference["schema_version"],
                            "scope": "all_capabilities", "complete": True,
                            "capabilities": [{key: capability[key] for key in ["id", "command", "description", "phases", "effects", "modes", "maturity", "profiles"]}
                                             for capability in reference["capabilities"]]}
                return success(validator, phase=Phase.OBSERVE, request_id=request_id, data=data)
            provider = context_provider if name == "context" else doctor_provider
            if provider is None:
                return failure(validator, phase=Phase.OBSERVE, request_id=request_id, catalog=catalog,
                               code="E_UNSUPPORTED", message="Native environment provider is not configured.", retryable=False,
                               details={"dispatch_state": "not_started"},
                               data={"native": {"status": "unsupported", "application_version": None},
                                     "limitations": ["No native connection or readiness was observed."]})
            try:
                result = success(validator, phase=Phase.OBSERVE, request_id=request_id, data=provider(invocation))
                configured = next((capability for capability in reference["capabilities"] if capability["command"] == name), None)
                if configured:
                    validator.validate_schema(configured["result_schema"], result.envelope, reference["schemas"])
                return result
            except Exception:
                return _unknown(validator, catalog, invocation)
        parser, tree, codecs = _compile(validator, reference, entrypoint)
        if "--help" in arguments or "-h" in arguments:
            selected = max((words for words in tree if list(words) == arguments[:len(words)]), key=len)
            return HelpResult(tree[selected].format_help())
        namespace = parser.parse_args(arguments)
        capability_id = getattr(namespace, "_capability_id", None)
        if capability_id is None:
            raise ContractError("a declared endpoint must be selected")
        capability = next(item for item in reference["capabilities"] if item["id"] == capability_id)
        selected_phase = getattr(namespace, "phase", None)
        if selected_phase is None:
            if len(capability["phases"]) != 1:
                raise ContractError("multi-phase endpoints require an explicit --phase")
            selected_phase = capability["phases"][0]
        phase = Phase(selected_phase)
        if phase not in capability["phases"]:
            raise ContractError("phase is not declared by the selected endpoint")
        caller_known = hasattr(namespace, "request_id")
        request_id = getattr(namespace, "request_id", request_id)
        if not request_id:
            raise ContractError("request ID must not be empty")
        if phase not in {Phase.PLAN, Phase.SUBMIT, Phase.STATUS} and MODIFYING_EFFECTS.intersection(capability["effects"]) and not caller_known:
            raise ContractError("actual modifications require a caller-known --request-id")
        payload, notices = _request(namespace, codecs[capability_id], max_input_bytes, stdin)
        payload = validator.validate_schema(capability["request_schema"], payload, reference["schemas"])
        invocation = Invocation(capability_id, phase, request_id, payload, caller_known)
        executor = getattr(adapter, "execute", None)
        if not callable(executor):
            raise ContractError("adapter must be supplied as an explicit execute object")
        dispatcher = EndpointDispatcher(validator, catalog)
        dispatcher.register(capability_id, phase, executor, effects=capability["effects"])
        result = dispatcher.dispatch(invocation)
        envelope = result.envelope
        if not envelope["ok"] and envelope["error"]["code"] == "E_OUTCOME_UNKNOWN":
            return result
        try:
            validator.validate_schema(capability["result_schema"], result.envelope, reference["schemas"])
            if notices:
                value = result.envelope
                value["meta"].setdefault("notices", []).extend(notices)
                result = CommandResult(json_bytes(validator.validate("response", value)), result.exit_code)
            return result
        except Exception:
            return _unknown(validator, catalog, invocation, result)
    except (ContractError, KeyError, TypeError, ValueError, OSError):
        return _rejected(validator, catalog, request_id, "CLI configuration or input did not pass pre-dispatch checks.", phase)
