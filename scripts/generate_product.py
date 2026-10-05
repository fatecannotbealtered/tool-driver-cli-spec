"""Generate a driver product's contract artifacts from one data-only registry.

Outputs: product_contract.json (what the SDK runtime loads), reference.json (for review and diff),
contract-ext.json (driver and product extension codes in the base contract-ext format) and
skill-capabilities.md (a capability summary for Skill authors). Built-in commands are added here,
so every product exposes the same reference, context, doctor, changelog and operation commands.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import stat
import sys
import time
import uuid
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from check_spec import base_contract, driver_contract, reference_errors

SPEC_ROOT = Path(__file__).resolve().parents[1]
OWNER = "tool-driver-cli-spec.product-generation"
MANIFEST = "product-generation.manifest.json"
LOCK = ".product-generation.lock"
MAX_INPUT_BYTES = 8 * 1024 * 1024
ARTIFACT_NAMES = frozenset({"product_contract.json", "reference.json", "contract-ext.json", "skill-capabilities.md"})
BUILTIN_HEADS = {"reference", "context", "doctor", "changelog", "operation"}
BUILTIN_SCHEMAS = {
    "reference": {"shape": "object", "fields": ["tool", "version", "risk_tier", "release_readiness", "commands", "schemas",
                                                "exit_codes", "error_codes", "driver_profile"], "untrusted_fields": []},
    "context": {"shape": "object", "fields": ["version", "credentials", "driver_profile", "authorization", "environment", "state"],
                "untrusted_fields": []},
    "doctor": {"shape": "object", "fields": ["checks"], "untrusted_fields": []},
    "changelog": {"shape": "object", "fields": ["current_version", "since", "count", "entries"], "untrusted_fields": []},
    "operation": {"shape": "object", "fields": ["operation_status"], "untrusted_fields": []},
    "operation_page": {"shape": "object", "fields": ["items", "count", "has_more", "truncated", "offset", "next_offset", "scope",
                                                     "snapshot", "snapshot_unavailable_reason", "sort", "limits"], "untrusted_fields": []},
}


DEFAULT_RECORD = {
    "store": "SQLite file in the tool state directory", "retain_days": 30,
    "survives_cli_exit": True, "survives_reconnect": True, "survives_instance_restart": True,
    "limitations": ["A synchronous apply whose CLI process ends reports unknown once its lease expires.",
                    "The record is local to this machine; after an application restart the native outcome may still need a read-back."],
}


class GenerationError(ValueError):
    def __init__(self, message: str, code: str = "E_VALIDATION", errors=None):
        super().__init__(message)
        self.code = code
        self.errors = list(errors or [])


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
        return json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object, parse_float=_float, parse_constant=_constant)
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
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
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


def _changelog_parser():
    for base in (SPEC_ROOT / "packages", SPEC_ROOT.parent / "vendor" / "sdk"):
        candidate = base / "tool_driver_sdk" / "changelog.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("_td_generator_changelog", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.parse_changelog
    raise GenerationError("the SDK changelog parser is not available next to this generator", "E_CONFIG")


def _schemas() -> dict[str, dict]:
    return {value["$id"]: value for value in (_parse(read_regular(path)) for path in sorted((SPEC_ROOT / "schemas").glob("*.schema.json")))}


def _validator(identity: str, schemas: dict[str, dict]):
    registry = Registry()
    for schema in schemas.values():
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return Draft202012Validator(schemas[identity], registry=registry, format_checker=FormatChecker())


def _builtin_commands(tool: str, version: str, modes: list[str], maturity: str, evidence: list[str]) -> list[dict]:
    environment = {"application": f"{tool} (built-in)", "application_version": "not_applicable", "platform": "any", "arch": "any",
                   "adapter_version": version, "mode": modes[0],
                   "limitations": ["Provided by tool-driver-sdk; reads only the tool's own declarations, scope and records."]}

    def command(path, description, output, params=(), examples=None, errors=("E_USAGE", "E_VALIDATION"), profiles=("core",),
                limits=()):
        return {
            "path": path, "type": "read", "description": description, "params": list(params), "output_schema": output,
            "examples": examples or [f"{tool} {path} --compact"],
            "driver": {"capability_id": path.replace(" ", "-"), "effects": ["observe"], "phases": ["observe"], "modes": list(modes),
                       "maturity": maturity, "environments": [copy.deepcopy(environment)], "limits": list(limits),
                       "recovery": {"atomicity": "none", "undo": False, "idempotent": True, "cancel": False},
                       "profiles": list(profiles), "error_codes": list(errors), "evidence_refs": list(evidence)},
        }

    status = ["planned", "pending", "running", "cancel_requested", "succeeded", "partial", "failed", "cancelled", "unknown"]
    return [
        command("changelog", "Version changes from the embedded CHANGELOG; --since returns only newer versions.", "changelog",
                [{"name": "since", "type": "string", "required": False, "multiple": False, "description": "the version you last used"}],
                [f"{tool} changelog --since 0.1.0 --compact"]),
        command("context", "CLI, adapter, running service and application identity, the task scope and the record store.", "context",
                errors=("E_USAGE", "E_VALIDATION", "E_IO")),
        command("doctor", "Readiness checks (release readiness, task scope, native backend, record store), each failure with a fix.",
                "doctor", errors=("E_USAGE", "E_VALIDATION", "E_IO")),
        command("operation list", "Recent operation records from the local store, newest first.", "operation_page",
                [{"name": "status", "type": "string", "required": False, "multiple": False, "enum": status},
                 {"name": "limit", "type": "integer", "required": False, "multiple": False, "default": 20},
                 {"name": "offset", "type": "integer", "required": False, "multiple": False, "default": 0}],
                [f"{tool} operation list --status unknown --compact"], errors=("E_USAGE", "E_VALIDATION", "E_IO"),
                profiles=("core", "query_page")),
        command("operation resolve", "Record what an independent read-back showed about an unknown or partial operation; "
                "changes only the local record, needs the scope that allowed the operation and refuses while the operation "
                "is still running.", "operation",
                [{"name": "id", "type": "string", "required": True, "multiple": False},
                 {"name": "outcome", "type": "string", "required": True, "multiple": False, "enum": ["applied", "not_applied", "partial"]},
                 {"name": "evidence", "type": "string", "required": True, "multiple": False,
                  "description": "what you read back, and with which command"}],
                [f"{tool} operation resolve --id <operation_id> --outcome not_applied --evidence \"<what the read-back showed>\""],
                errors=("E_USAGE", "E_VALIDATION", "E_NOT_FOUND", "E_FORBIDDEN", "E_CONFLICT", "E_IO"),
                limits=["Refuses with E_CONFLICT (lock_held) while the operation still runs under a live lease.",
                        "Resolves one operation; a batch is resolved item by item.",
                        "Changes only the local record, never the target or the original receipt."]),
        command("operation show", "One operation record: plan, status, receipt and resolution.", "operation",
                [{"name": "id", "type": "string", "required": True, "multiple": False}],
                [f"{tool} operation show --id <operation_id> --compact"], errors=("E_USAGE", "E_VALIDATION", "E_NOT_FOUND", "E_IO")),
        command("reference", "This reference. --index lists one line per command; --command <path> returns one command.", "reference",
                [{"name": "index", "type": "boolean", "required": False, "multiple": False, "default": False},
                 {"name": "command", "type": "string", "required": False, "multiple": False, "description": "a command path from --index"}],
                [f"{tool} reference --index --compact", f"{tool} reference --command \"context\" --compact"]),
    ]


def build_contract(registry: dict, *, registry_dir: Path | str | None = None, public_root: Path | str = SPEC_ROOT) -> dict:
    """Return the runtime contract (reference, changelog and build identity) without writing anything."""
    schemas = _schemas()
    problems = [f"{'/'.join(map(str, error.absolute_path)) or '(root)'}: {error.message}"
                for error in _validator("urn:tool-driver-cli-spec:product-registry:2.0", schemas).iter_errors(registry)]
    if problems:
        raise GenerationError("registry does not satisfy the product-registry schema", errors=problems[:20])
    for command in registry["commands"]:
        if command["path"].split()[0] in BUILTIN_HEADS:
            raise GenerationError(f"'{command['path']}' is a built-in command path; the generator provides it")
    collisions = set(registry["schemas"]) & set(BUILTIN_SCHEMAS)
    if collisions:
        raise GenerationError(f"schema labels reserved for built-in commands: {sorted(collisions)}")
    contract = driver_contract()
    base = base_contract()
    lock = json.loads((SPEC_ROOT / "base" / "base-lock.json").read_text(encoding="utf-8"))
    codes = {code: {"exit": entry["exit"], "retryable": entry["retryable"]} for code, entry in base["error_codes"]["core"].items()}
    for code, entry in contract["error_codes"]["extensions"].items():
        codes[code] = {"exit": entry["exit"], "retryable": entry["retryable"], "description": entry["meaning"]}
    for code, entry in registry.get("error_codes", {}).items():
        if code in codes:
            raise GenerationError(f"{code} is a core or driver code; products cannot redefine it")
        codes[code] = copy.deepcopy(entry)
    modes = sorted({mode for command in registry["commands"] for mode in command["driver"]["modes"]})
    builtins = registry.get("builtins", {})
    commands = _builtin_commands(registry["name"], registry["product_version"], modes,
                                 builtins.get("maturity", "experimental"), builtins.get("evidence_refs", []))
    commands += copy.deepcopy(registry["commands"])
    commands.sort(key=lambda item: item["path"])
    table = base["exit_codes"]["table"]
    reference = {
        "tool": registry["name"], "version": registry["product_version"], "risk_tier": registry["risk_tier"],
        "release_readiness": copy.deepcopy(registry.get("release_readiness") or {
            "level": "unpublishable", "fcc_status": "missing",
            "reason": "No functional contract coverage or live evidence is recorded yet."}),
        "commands": commands,
        "schemas": {**copy.deepcopy(BUILTIN_SCHEMAS), **copy.deepcopy(registry["schemas"])},
        "exit_codes": {key: table[key] for key in sorted(table, key=int)},
        "error_codes": dict(sorted(codes.items())),
        "driver_profile": {"spec": "tool-driver-cli-spec", "spec_version": contract["spec_version"],
                           "schema_version": contract["schema_version"], "base": {"spec": "ai-native-cli-spec", "version": lock["tag"]},
                           "record": copy.deepcopy(registry.get("record") or DEFAULT_RECORD)},
    }
    if registry.get("json_schemas"):
        reference["json_schemas"] = copy.deepcopy(registry["json_schemas"])
    problems = [f"{'/'.join(map(str, error.absolute_path)) or '(root)'}: {error.message}"
                for error in _validator("urn:tool-driver-cli-spec:reference:2.0", schemas).iter_errors(reference)]
    problems = problems or reference_errors(reference)
    if problems:
        raise GenerationError("the generated reference violates the driver contract", errors=problems[:20])
    changelog = []
    if registry.get("changelog"):
        if registry_dir is None:
            raise GenerationError("the registry names a changelog but its directory is unknown")
        path = Path(registry_dir) / registry["changelog"]
        changelog = _changelog_parser()(read_regular(path).decode("utf-8"))
        if changelog and changelog[0]["version"] != registry["product_version"]:
            raise GenerationError(f"the newest CHANGELOG version is {changelog[0]['version']}, but product_version is {registry['product_version']}")
    return {"contract_version": "2.0", "build_id": "registry-sha256:" + fingerprint(json_bytes(registry)),
            "reference": reference, "changelog": changelog}


def build_artifacts(registry: dict, *, registry_dir: Path | str | None = None, public_root: Path | str = SPEC_ROOT) -> dict[str, bytes]:
    contract = build_contract(registry, registry_dir=registry_dir, public_root=public_root)
    reference = contract["reference"]
    driver_codes = driver_contract()["error_codes"]["extensions"]
    extension = {"error_codes": {code: {"exit": entry["exit"], "retryable": entry["retryable"]}
                                 for code, entry in reference["error_codes"].items()
                                 if code in driver_codes or code in registry.get("error_codes", {})},
                 "note": "Generated from the product registry: tool-driver-cli-spec driver extension codes plus product codes, "
                         "in the base contract-ext format."}
    lines = [f"# {reference['tool']} capability summary", "",
             "Generated from the product registry. Parameters and result shapes come from `reference` at run time; this is not "
             "an authorization policy or verification evidence.", "",
             "| Command | Type | Effects | Maturity | What it does |", "|---|---|---|---|---|"]
    for command in reference["commands"]:
        kind = command["type"] + (", dangerous" if command.get("dangerous") else "")
        description = command["description"].replace("|", "\\|")
        lines.append(f"| `{command['path']}` | {kind} | {', '.join(command['driver']['effects'])} | {command['driver']['maturity']} | {description} |")
    return {
        "product_contract.json": json_bytes(contract),
        "reference.json": json_bytes(reference),
        "contract-ext.json": json_bytes(extension),
        "skill-capabilities.md": ("\n".join(lines) + "\n").encode("utf-8"),
    }


def _manifest(artifacts: dict[str, bytes], registry: dict) -> dict:
    return {"owner": OWNER, "format_version": "2.0", "generator_sha256": fingerprint(read_regular(Path(__file__))),
            "registry_encoding": "canonical_utf8_json", "registry_sha256": fingerprint(json_bytes(registry)),
            "files": {name: fingerprint(payload) for name, payload in sorted(artifacts.items())}}


def _inspect_output(output: Path, artifacts: dict[str, bytes], expected_manifest: dict):
    _no_links(output)
    if output.exists() and not output.is_dir():
        raise GenerationError("output must be a directory", "E_CONFLICT")
    manifest_path = output / MANIFEST
    manifest = None
    if manifest_path.exists():
        manifest = _parse(read_regular(manifest_path))
        if (not isinstance(manifest, dict) or manifest.get("owner") != OWNER or manifest.get("format_version") != "2.0"
                or not isinstance(manifest.get("files"), dict) or not set(manifest["files"]).issubset(ARTIFACT_NAMES)):
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


def generate_registry(registry: dict, output: Path | str, *, check: bool = False, update: bool = False,
                      registry_dir: Path | str | None = None, public_root: Path | str = SPEC_ROOT) -> dict:
    if check and update:
        raise GenerationError("--check and --update are mutually exclusive", "E_USAGE")
    artifacts = build_artifacts(registry, registry_dir=registry_dir, public_root=public_root)
    manifest = _manifest(artifacts, registry)
    output = _absolute(output)
    old_manifest, changes = _inspect_output(output, artifacts, manifest)
    result = {"scope": "product_development_generation", "registry_sha256": manifest["registry_sha256"], "files": sorted(artifacts)}
    if check:
        if changes:
            raise GenerationError("generated artifacts differ from the registry; run the generator with --update", "E_CONFLICT",
                                  errors=sorted(changes))
        return {**result, "check": True, "changed": False}
    if changes and old_manifest and not update:
        raise GenerationError("owned outputs differ; inspect the registry and use explicit --update", "E_CONFLICT", errors=sorted(changes))
    if not changes:
        return {**result, "check": False, "changed": False}
    output.mkdir(parents=True, exist_ok=True)
    _no_links(output)
    lock = output / LOCK
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    staged, published, replaced = [], [], {}
    payloads = {**artifacts, MANIFEST: json_bytes(manifest)}
    try:
        old_manifest, changes = _inspect_output(output, artifacts, manifest)
        if changes and old_manifest and not update:
            raise GenerationError("a concurrent generation changed the output; explicit update is required", "E_CONFLICT")
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
                os.link(temporary, destination)
                temporary.unlink()
            published.append(destination.name)
    except BaseException:
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
                continue
        raise
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
    return {**result, "check": False, "changed": True}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise GenerationError(f"invalid generation arguments: {message}", "E_USAGE")


EXIT = {"E_USAGE": 2, "E_VALIDATION": 2, "E_CONFLICT": 6, "E_CONFIG": 4, "E_IO": 1}


def _emit(started: float, data=None, error: GenerationError | None = None) -> int:
    meta = {"duration_ms": round((time.monotonic() - started) * 1000, 3)}
    if error is None:
        value = {"ok": True, "schema_version": "1.0", "data": data, "meta": meta}
        status = 0
    else:
        details = {"scope": "development_support", "next_action": {
            "E_USAGE": "Run with --registry <file> --output <dir> [--check | --update].",
            "E_VALIDATION": "Fix the registry entries named in details.errors and run the generator again.",
            "E_CONFLICT": "Inspect the output directory; regenerate with --update only if the registry is the intended source.",
            "E_CONFIG": "Restore the pinned specification copy (check_project.py).",
            "E_IO": "Check that the registry and output paths are readable and writable."}[error.code]}
        if error.errors:
            details["errors"] = error.errors
        value = {"ok": False, "schema_version": "1.0", "meta": meta,
                 "error": {"code": error.code, "message": str(error), "retryable": False, "details": details}}
        status = EXIT[error.code]
    sys.stdout.buffer.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return status


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
        registry_path = _absolute(args.registry)
        result = generate_registry(load_registry(registry_path), args.output, check=args.check, update=args.update,
                                   registry_dir=registry_path.parent)
        return _emit(started, result)
    except GenerationError as exc:
        return _emit(started, error=exc)
    except OSError as exc:
        return _emit(started, error=GenerationError(f"input or output failed: {exc}", "E_IO"))
    except (ValueError, KeyError, TypeError, RecursionError) as exc:
        return _emit(started, error=GenerationError(f"registry could not be processed: {exc}"))


if __name__ == "__main__":
    sys.exit(main())
