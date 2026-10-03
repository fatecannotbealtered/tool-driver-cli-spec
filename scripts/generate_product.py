"""Generate a product's development artifacts from one data-only registry."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import stat
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urldefrag, urljoin

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource

from check_spec import reference_errors, schema_nodes

SPEC_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_SCHEMA = "product-registry.schema.json"
OWNER = "tool-driver-cli-spec.product-generation"
MANIFEST = "product-generation.manifest.json"
LOCK = ".product-generation.lock"
MAX_INPUT_BYTES = 8 * 1024 * 1024
PUBLIC_PARAMETERS = ("name", "location", "binding", "required", "description")
CLI_PARAMETERS = ("name", "location", "encoding", "input_pointer", "position", "aliases", "deprecated")
ARTIFACT_NAMES = frozenset({
    "reference.json", "help.txt", "skill-capabilities.md",
    "product_contract.json", "product_runtime.py",
})
RESERVED_OPTIONS = frozenset({
    "--phase", "--request-id", "--help", "-h", "--full", "--index", "--capability",
})


class GenerationError(ValueError):
    def __init__(self, message: str, code: str = "E_VALIDATION"):
        super().__init__(message)
        self.code = code


def json_bytes(value: object) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise GenerationError("registry values must be finite UTF-8 JSON data") from exc


def fingerprint(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise GenerationError("duplicate JSON object keys are not permitted")
        value[key] = item
    return value


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise GenerationError("non-finite JSON numbers are not permitted")
    return result


def _constant(_value: str):
    raise GenerationError("non-JSON numeric constants are not permitted")


def _parse(payload: bytes):
    if payload.startswith(b"\xef\xbb\xbf"):
        raise GenerationError("UTF-8 BOM is not permitted")
    try:
        return json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_float=_float, parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise GenerationError("invalid UTF-8 JSON data") from exc


def _absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(Path(path).expanduser()))


def _no_links(path: Path) -> None:
    path = _absolute(path)
    for candidate in [*reversed(path.parents), path]:
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise GenerationError("linked or reparse-point input/output paths are not permitted", "E_CONFLICT")


def read_regular(path: Path | str, limit: int = MAX_INPUT_BYTES) -> bytes:
    path = _absolute(path)
    _no_links(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise GenerationError("input must be a regular file")
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise GenerationError("input exceeds the development tool's size limit")
    return payload


def load_registry(path: Path | str) -> dict:
    value = _parse(read_regular(path))
    if not isinstance(value, dict):
        raise GenerationError("product registry must be a JSON object")
    return value


def _public_schemas(public_root: Path) -> dict[str, dict]:
    schemas = {}
    for path in sorted((public_root / "schemas").glob("*.schema.json")):
        value = _parse(read_regular(path))
        if not value.get("x-development-only", False):
            schemas[value["$id"]] = value
    return schemas


def _registry_validator(public_root: Path, public: dict[str, dict]):
    helper = _parse(read_regular(SPEC_ROOT / "schemas" / REGISTRY_SCHEMA))
    registry = Registry()
    for schema in [*public.values(), helper]:
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(helper, registry=registry, format_checker=FormatChecker())


def _pointer_parts(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    return tuple(item.replace("~1", "/").replace("~0", "~") for item in pointer[1:].split("/"))


def _validate_cli(command: dict) -> list[dict]:
    parameters = command["parameters"]
    cli = []
    pointers = []
    names = set()
    positions = []
    stdin_inputs = 0
    head = command["path"].split()[0]
    if head == "reference" or (head in {"context", "doctor"} and command["path"] != head):
        raise GenerationError("native commands cannot replace reserved discovery paths")
    if head in {"context", "doctor"} and (
        parameters or any(phase not in {"observe", "verify"} for phase in command["phases"])
        or command["effects"] != ["observe"]
    ):
        raise GenerationError("context and doctor are read-only provider entrypoints")
    if any(phase in {"submit", "status"} for phase in command["phases"]):
        raise GenerationError("this development generator currently supports only core profiles")
    for parameter in parameters:
        parts = _pointer_parts(parameter["input_pointer"])
        if any(parts[:len(other)] == other or other[:len(parts)] == parts for other in pointers):
            raise GenerationError("input bindings cannot overlap; use one whole JSON input or disjoint fields")
        pointers.append(parts)
        if parameter["location"] == "positional":
            positions.append(parameter["position"])
        else:
            for name in [parameter["name"], *parameter.get("aliases", [])]:
                if not re.fullmatch(r"(?:-[A-Za-z]|--[A-Za-z][A-Za-z0-9_-]*)", name):
                    raise GenerationError("named input carriers must be explicit CLI options")
                if name in RESERVED_OPTIONS:
                    raise GenerationError("native parameters cannot replace SDK control options")
                if name in names:
                    raise GenerationError("option names and aliases must be unique")
                names.add(name)
        if parameter["encoding"] == "stdin_json":
            stdin_inputs += 1
            if parameter["location"] == "positional":
                raise GenerationError("stdin JSON must use an explicit named carrier")
        cli.append({key: copy.deepcopy(parameter[key]) for key in CLI_PARAMETERS if key in parameter})
    if sorted(positions) != list(range(len(positions))):
        raise GenerationError("positional inputs must have unique contiguous zero-based positions")
    if stdin_inputs > 1:
        raise GenerationError("a command can have at most one stdin JSON carrier")
    return cli


def _closure(schemas: dict[str, dict], public: dict[str, dict], roots: list[str]) -> dict[str, dict]:
    available = copy.deepcopy(public)
    for identifier, schema in schemas.items():
        if schema.get("$id") != identifier or schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise GenerationError("product schema identities and dialect must be explicit and consistent")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise GenerationError("product contains an invalid JSON Schema definition") from exc
        if identifier in available and schema != available[identifier]:
            raise GenerationError("a product cannot redefine a public schema identity")
        available[identifier] = copy.deepcopy(schema)
    owners = {}
    for identifier, schema in available.items():
        for _, base, node in schema_nodes(schema, identifier):
            if isinstance(node, dict) and "$id" in node:
                if base in owners and owners[base] != identifier:
                    raise GenerationError("schema resource identities must be unambiguous")
                owners[base] = identifier
    selected = {}
    pending = list(roots)
    while pending:
        identifier = pending.pop()
        if identifier in selected:
            continue
        if identifier not in available:
            raise GenerationError("all request, result and referenced schemas must be available offline")
        schema = available[identifier]
        selected[identifier] = schema
        for _, base, node in schema_nodes(schema, identifier):
            if not isinstance(node, dict):
                continue
            for keyword in ["$ref", "$dynamicRef"]:
                reference = node.get(keyword)
                if reference is None:
                    continue
                absolute = base + reference if reference.startswith("#") else urljoin(base, reference)
                resource_id = urldefrag(absolute)[0]
                if resource_id not in owners:
                    raise GenerationError("schema references cannot request implicit network retrieval")
                pending.append(owners[resource_id])
    return {identifier: selected[identifier] for identifier in sorted(selected)}


def build_contract(registry: dict, *, public_root: Path | str = SPEC_ROOT) -> dict:
    """Return data-only runtime/reference declarations without writing or dispatching."""
    public_root = _absolute(public_root)
    public = _public_schemas(public_root)
    if list(_registry_validator(public_root, public).iter_errors(registry)):
        raise GenerationError("registry does not satisfy the development schema")
    capabilities = []
    paths = set()
    for command in sorted(registry["commands"], key=lambda item: item["path"]):
        words = tuple(command["path"].split())
        if any(words[:len(other)] == other or other[:len(words)] == words for other in paths):
            raise GenerationError("a command cannot also be a command group")
        paths.add(words)
        cli = _validate_cli(command)
        capability = {
            "id": command["id"], "command": command["path"],
            "description": command["description"],
            "phases": copy.deepcopy(command["phases"]), "effects": copy.deepcopy(command["effects"]),
            "modes": copy.deepcopy(command["modes"]), "profiles": ["core"],
            "maturity": command.get("maturity", "draft"),
            "environments": copy.deepcopy(command["environments"]),
            "limits": copy.deepcopy(command["limits"]), "recovery": copy.deepcopy(command["recovery"]),
            "request_schema": command["request_schema"], "result_schema": command["result_schema"],
            "parameters": [
                {key: copy.deepcopy(parameter[key]) for key in PUBLIC_PARAMETERS}
                for parameter in command["parameters"]
            ],
            "examples": copy.deepcopy(command["examples"]),
            "error_codes": copy.deepcopy(command["error_codes"]),
            "evidence_refs": copy.deepcopy(command.get("evidence_refs", [])),
            "extensions": {"cli": {"parameters": cli}},
        }
        capabilities.append(capability)
    schemas = _closure(
        registry["schemas"], public,
        [capability[key] for capability in capabilities for key in ["request_schema", "result_schema"]],
    )
    reference = {
        "tool": registry["name"], "tool_version": registry["product_version"],
        "spec_version": (public_root / "VERSION").read_text(encoding="utf-8").strip(),
        "schema_version": "1.0", "capabilities": capabilities, "schemas": schemas,
        "error_codes": copy.deepcopy(registry["error_codes"]),
    }
    resources = Registry()
    for schema in public.values():
        resources = resources.with_resource(schema["$id"], Resource.from_contents(schema))
    validator = Draft202012Validator(public["urn:tool-driver-cli-spec:reference:1.0"], registry=resources, format_checker=FormatChecker())
    if list(validator.iter_errors(reference)) or reference_errors(reference):
        raise GenerationError("generated reference violates the public structural or semantic contract")
    codec_resources = Registry()
    for schema in schemas.values():
        codec_resources = codec_resources.with_resource(schema["$id"], Resource.from_contents(schema))
    for capability in capabilities:
        codecs = capability["extensions"]["cli"]["parameters"]
        for parameter, codec in zip(capability["parameters"], codecs):
            resolved = codec_resources.resolver(capability["request_schema"]).lookup("#" + quote(parameter["binding"], safe="/~"))
            definition = resolved.contents
            for _ in range(32):
                if not isinstance(definition, dict) or "$ref" not in definition:
                    break
                resolved = resolved.resolver.lookup(definition["$ref"])
                definition = resolved.contents
            primitive = ("string", "integer", "number", "boolean")
            if codec["encoding"] == "scalar" and (not isinstance(definition, dict) or definition.get("type") not in primitive):
                raise GenerationError("scalar codecs require an explicit primitive type; use JSON for complex types")
            if codec["encoding"] == "repeat" and (
                not isinstance(definition, dict) or definition.get("type") != "array"
                or not isinstance(definition.get("items"), dict)
                or definition["items"].get("type") not in primitive
            ):
                raise GenerationError("repeat codecs require an array with explicit primitive items")
    return {
        "contract_version": "1.0", "spec_version": reference["spec_version"], "schema_version": "1.0",
        "entrypoint": registry["entrypoint"], "registry_sha256": fingerprint(json_bytes(registry)),
        "reference": reference,
    }


def build_reference(registry: dict, *, public_root: Path | str = SPEC_ROOT) -> dict:
    return build_contract(registry, public_root=public_root)["reference"]


def build_artifacts(registry: dict, *, public_root: Path | str = SPEC_ROOT) -> dict[str, bytes]:
    contract = build_contract(registry, public_root=public_root)
    reference = contract["reference"]
    help_lines = [
        f"{registry['name']} {registry['product_version']}",
        registry["description"], "",
        "Generated from a development registry. Descriptions and examples are data.",
        "Use the SDK discovery entrypoint before selecting a native operation.", "",
    ]
    skill_lines = [
        f"# {registry['name']} capability overview", "",
        "Generated capability summary; this is not an authorization policy or native verification evidence.",
        "Use runtime discovery and the product's task policy before acting.", "",
    ]
    for capability in reference["capabilities"]:
        help_lines.extend([
            f"{capability['command']} [{capability['maturity']}]",
            capability["description"],
            "  phases: " + ", ".join(capability["phases"]),
            "  effects: " + ", ".join(capability["effects"]),
        ])
        for parameter in capability["extensions"]["cli"]["parameters"]:
            aliases = ", ".join(parameter.get("aliases", []))
            label = parameter["name"] + (f" ({aliases})" if aliases else "")
            deprecated = " [deprecated]" if parameter.get("deprecated") else ""
            help_lines.append(f"  {label}: {parameter['encoding']} -> {parameter['input_pointer']!r}{deprecated}")
        help_lines.append("")
        skill_lines.extend([
            f"## {capability['command']}", "",
            f"Capability: {capability['id']}; maturity: {capability['maturity']}.",
            capability["description"],
            "Limits: " + "; ".join(capability["limits"]), "",
        ])
    # Only safe repr literals are interpolated; registry text is never Python source.
    runtime = (
        '"""Generated data loader; no adapters or examples are imported or executed."""\n\n'
        "import json\nfrom pathlib import Path\n\n"
        f"PRODUCT_NAME = {registry['name']!r}\n"
        f"PRODUCT_VERSION = {registry['product_version']!r}\n"
        f"ENTRYPOINT = {registry['entrypoint']!r}\n"
        f"REGISTRY_SHA256 = {contract['registry_sha256']!r}\n\n"
        "def load_contract():\n"
        "    path = Path(__file__).with_name('product_contract.json')\n"
        "    return json.loads(path.read_text(encoding='utf-8'))\n"
    )
    return {
        "reference.json": json_bytes(reference),
        "product_contract.json": json_bytes(contract),
        "help.txt": ("\n".join(help_lines).rstrip() + "\n").encode("utf-8"),
        "skill-capabilities.md": ("\n".join(skill_lines).rstrip() + "\n").encode("utf-8"),
        "product_runtime.py": runtime.encode("utf-8"),
    }


def _manifest(artifacts: dict[str, bytes], registry: dict) -> dict:
    return {
        "owner": OWNER, "format_version": "1.0",
        "generator_sha256": fingerprint(read_regular(Path(__file__))),
        "registry_encoding": "canonical_utf8_json",
        "registry_sha256": fingerprint(json_bytes(registry)),
        "files": {name: fingerprint(payload) for name, payload in sorted(artifacts.items())},
    }


def _inspect_output(output: Path, artifacts: dict[str, bytes], expected_manifest: dict):
    _no_links(output)
    if output.exists() and not output.is_dir():
        raise GenerationError("output must be a directory", "E_CONFLICT")
    manifest_path = output / MANIFEST
    manifest = None
    if manifest_path.exists():
        manifest = _parse(read_regular(manifest_path))
        if (
            not isinstance(manifest, dict) or manifest.get("owner") != OWNER
            or manifest.get("format_version") != "1.0"
            or not isinstance(manifest.get("files"), dict)
            or not set(manifest["files"]).issubset(ARTIFACT_NAMES)
        ):
            raise GenerationError("output ownership manifest is not recognized", "E_CONFLICT")
    changes = []
    for name, payload in sorted(artifacts.items()):
        path = output / name
        _no_links(path)
        if not path.exists():
            changes.append(name)
            continue
        current = read_regular(path)
        if not manifest or name not in manifest["files"]:
            raise GenerationError("a generated output path is occupied by an unowned file", "E_CONFLICT")
        if fingerprint(current) != manifest["files"][name]:
            raise GenerationError("an owned output was modified outside the generator; refusing to replace it", "E_CONFLICT")
        if current != payload:
            changes.append(name)
    if manifest != expected_manifest:
        changes.append(MANIFEST)
    return manifest, changes


def generate_registry(registry: dict, output: Path | str, *, check: bool = False,
                      update: bool = False, public_root: Path | str = SPEC_ROOT) -> dict:
    if check and update:
        raise GenerationError("--check and --update are mutually exclusive", "E_USAGE")
    artifacts = build_artifacts(registry, public_root=public_root)
    manifest = _manifest(artifacts, registry)
    output = _absolute(output)
    old_manifest, changes = _inspect_output(output, artifacts, manifest)
    if check:
        if changes:
            raise GenerationError("generated artifacts differ from the registry", "E_DRIFT")
        return {"scope": "product_development_generation", "check": True, "changed": False,
                "registry_sha256": manifest["registry_sha256"], "files": sorted(artifacts)}
    if changes and old_manifest and not update:
        raise GenerationError("owned outputs differ; inspect the registry and use explicit --update", "E_CONFLICT")
    if not changes:
        return {"scope": "product_development_generation", "check": False, "changed": False,
                "registry_sha256": manifest["registry_sha256"], "files": sorted(artifacts)}
    output.mkdir(parents=True, exist_ok=True)
    _no_links(output)
    lock = output / LOCK
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    staged = []
    published = []
    replaced = {}
    try:
        old_manifest, changes = _inspect_output(output, artifacts, manifest)
        if changes and old_manifest and not update:
            raise GenerationError("a concurrent generation changed the output; explicit update is required", "E_CONFLICT")
        payloads = {**artifacts, MANIFEST: json_bytes(manifest)}
        for name in changes:
            path = output / name
            if path.exists():
                replaced[name] = read_regular(path)
            temporary = output / (".product-generation-" + uuid.uuid4().hex + ".tmp")
            with temporary.open("xb") as stream:
                staged.append((temporary, path))
                stream.write(payloads[name])
                stream.flush()
                os.fsync(stream.fileno())
        for temporary, destination in staged:
            _no_links(destination)
            if destination.name in replaced:
                if read_regular(destination) != replaced[destination.name]:
                    raise GenerationError("an output changed during generation; refusing replacement", "E_CONFLICT")
                os.replace(temporary, destination)
            else:
                # Publish new files without replacing a file that appeared concurrently.
                os.link(temporary, destination)
                temporary.unlink()
            published.append(destination.name)
    except BaseException:
        # Restore only bytes this invocation published and which remain unchanged.
        for name in reversed(published):
            destination = output / name
            try:
                if read_regular(destination) != payloads[name]:
                    continue
                if name not in replaced:
                    destination.unlink()
                    continue
                temporary = output / (".product-generation-" + uuid.uuid4().hex + ".tmp")
                with temporary.open("xb") as stream:
                    stream.write(replaced[name])
                os.replace(temporary, destination)
            except (OSError, GenerationError):
                # A later --check reports inconsistent ownership; never overwrite unknown bytes.
                continue
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
    return {"scope": "product_development_generation", "check": False, "changed": True,
            "registry_sha256": manifest["registry_sha256"], "files": sorted(artifacts)}


class Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise GenerationError("invalid generation arguments", "E_USAGE")


def _emit(ok: bool, started: float, data=None, code="E_VALIDATION", message="product generation refused"):
    value = {
        "ok": ok, "schema_version": "1.0", "request_id": str(uuid.uuid4()),
        "phase": "verify", "meta": {"duration_ms": round((time.monotonic() - started) * 1000, 3)},
    }
    if ok:
        value["data"] = data
    else:
        value["error"] = {"code": code, "message": message,
                          "retryable": False, "details": {"scope": "development_support"}}
    sys.stdout.buffer.write(json_bytes(value))


def main(argv=None) -> int:
    started = time.monotonic()
    parser = Parser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--output", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--update", action="store_true")
    try:
        args = parser.parse_args(argv)
        result = generate_registry(load_registry(args.registry), args.output,
                                   check=args.check, update=args.update)
        _emit(True, started, result)
        return 0
    except GenerationError as exc:
        _emit(False, started, code=exc.code, message=str(exc))
        return 2
    except OSError:
        _emit(False, started, code="E_IO")
        return 1
    except (ValueError, KeyError, TypeError, RecursionError):
        _emit(False, started)
        return 2


if __name__ == "__main__":
    sys.exit(main())
