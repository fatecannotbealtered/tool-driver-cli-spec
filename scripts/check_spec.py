"""Validate local schemas, examples, static state relations and document links.

This checker never contacts an application, device or schema server. It does not
establish that any receipt or evidence was produced by a real tool.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urljoin

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from contract_io import InputError, canonical_relative_path, path_identity

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validators():
    schemas = {p.name: load(p) for p in (ROOT / "schemas").glob("*.schema.json")}
    registry = Registry()
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return {
        name: Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        for name, schema in schemas.items()
    }


def schema_nodes(schema, base: str, pointer: str = ""):
    """Visit real subschemas, excluding schema containers and annotation data."""
    if isinstance(schema, bool):
        yield pointer, base, schema
        return
    if not isinstance(schema, dict):
        return
    base = urljoin(base, schema.get("$id", base))
    yield pointer, base, schema
    for key in ["$defs", "definitions", "properties", "patternProperties", "dependentSchemas"]:
        for name, child in schema.get(key, {}).items():
            escaped = name.replace("~", "~0").replace("/", "~1")
            yield from schema_nodes(child, base, f"{pointer}/{key}/{escaped}")
    for key in ["items", "additionalProperties", "unevaluatedProperties", "unevaluatedItems", "contains", "propertyNames", "if", "then", "else", "not", "contentSchema"]:
        if key in schema:
            yield from schema_nodes(schema[key], base, f"{pointer}/{key}")
    for key in ["allOf", "anyOf", "oneOf", "prefixItems"]:
        for index, child in enumerate(schema.get(key, [])):
            yield from schema_nodes(child, base, f"{pointer}/{key}/{index}")


def reference_errors(value: dict) -> list[str]:
    errors = []
    identifiers = [c["id"] for c in value["capabilities"]]
    if len(identifiers) != len(set(identifiers)):
        errors.append("capability IDs must be unique")
    codes = [entry["code"] for entry in value["error_codes"]]
    if len(codes) != len(set(codes)):
        errors.append("error codes must have unique exit mappings")
    schemas = value["schemas"]
    public_schemas = {schema["$id"]: schema for schema in (load(path) for path in (ROOT / "schemas").glob("*.schema.json"))}
    registry = Registry()
    resource_ids = set()
    for identifier, schema in schemas.items():
        try:
            if schema.get("$id") != identifier or schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                errors.append("schema directory identity or dialect mismatch")
                continue
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", identifier) or "#" in identifier:
                errors.append("schema IDs must be absolute resource identities without fragments")
                continue
            Draft202012Validator.check_schema(schema)
            for _, base, node in schema_nodes(schema, identifier):
                if isinstance(node, dict) and "$id" in node:
                    if base in resource_ids:
                        errors.append("schema resource identities must be unique")
                    resource_ids.add(base)
                    if base in public_schemas and node != public_schemas[base]:
                        errors.append(f"public schema identity cannot be redefined: {base}")
            registry = registry.with_resource(identifier, Resource.from_contents(schema))
        except (ValueError, SchemaError) as exc:
            errors.append("invalid discovered JSON Schema definition")
    if errors:
        return errors
    registry = registry.crawl()
    for identifier, schema in schemas.items():
        for _, base, node in schema_nodes(schema, identifier):
            if not isinstance(node, dict):
                continue
            for key in ["$ref", "$dynamicRef"]:
                if key in node:
                    try:
                        registry.resolver(base).lookup(node[key])
                    except Unresolvable:
                        errors.append("schema reference must resolve offline")
    if errors:
        return errors
    for capability in value["capabilities"]:
        if capability["maturity"] in {"verified", "stable"} and not capability["evidence_refs"]:
            errors.append("verified capabilities need scoped evidence")
        if any(code not in codes for code in capability["error_codes"]):
            errors.append("capability errors must have declared exit mappings")
        if any(capability[key] not in schemas for key in ["request_schema", "result_schema"]):
            errors.append("request and result schemas must be in the offline directory")
            continue
        request_id = capability["request_schema"]
        schema_pointers = {pointer for pointer, _, _ in schema_nodes(schemas[request_id], request_id)}
        names = [(p["location"], p["name"]) for p in capability["parameters"]]
        if len(names) != len(set(names)):
            errors.append("parameter names must be unique within each location")
        for parameter in capability["parameters"]:
            if parameter["binding"] not in schema_pointers:
                errors.append("parameter bindings must identify subschemas, not containers or data")
                continue
            try:
                binding = registry.resolver(request_id).lookup("#" + quote(parameter["binding"], safe="/~")).contents
                if not isinstance(binding, (dict, bool)):
                    errors.append("parameter bindings must identify schema definitions")
                else:
                    Draft202012Validator.check_schema(binding)
            except (Unresolvable, SchemaError):
                errors.append("parameter binding must resolve into the request schema")
        request_validator = Draft202012Validator(schemas[request_id], registry=registry, format_checker=FormatChecker())
        command = capability["command"].split()
        for example in capability["examples"]:
            if example["argv"][:len(command)] != command:
                errors.append("example argv must start with the command path, without an executable")
            if example["phase"] not in capability["phases"]:
                errors.append("example phase must be supported by its capability")
            if list(request_validator.iter_errors(example["request"])):
                errors.append("example request must satisfy the declared input schema")
    return errors


def semantic_errors(kind: str, value: dict) -> list[str]:
    errors = []
    if kind == "receipt":
        outcome = value["outcome"]
        verification = outcome["verification"]
        before, after = value["snapshot_before"], value["snapshot_after"]
        if outcome["change"] in {"applied", "partial", "rolled_back"} and value["authorization_scope_id"] is None:
            errors.append("known modifications must retain their applicable authorization reference")
        if outcome["change"] == "unknown" and value["authorization_scope_id"] is None and not value.get("authorization_unavailable_reason"):
            errors.append("unknown authorization must be disclosed without inventing a scope")
        if outcome["execution"] == "not_started" and outcome["change"] != "not_applied":
            errors.append("not_started cannot claim an applied or unknown change")
        if verification["status"] == "passed":
            if not after or verification["snapshot_id"] != after["id"]:
                errors.append("passed readback must identify snapshot_after")
            if any(c["required"] and c["status"] != "passed" for c in verification["checks"]):
                errors.append("all required checks must pass")
            if any(c["required"] for c in verification["not_checked"]):
                errors.append("required checks cannot be omitted from passed verification")
        if verification["status"] == "not_applicable" and (
            any(c["required"] for c in verification["checks"])
            or any(c["required"] for c in verification["not_checked"])
        ):
            errors.append("not_applicable cannot bypass applicable required checks")
        if outcome["change"] == "rolled_back":
            if not before or not after or not verification["evidence_refs"]:
                errors.append("rollback needs preimage, fresh readback and evidence")
        if outcome["change"] == "unknown" and value["recovery"]["action"] == "retry":
            errors.append("unknown changes must be reconciled before retry")
        if outcome["persistence"] == "saved" and not after:
            errors.append("saved state needs a post-operation snapshot")
    elif kind == "response":
        plan = value.get("data", {}).get("plan")
        if plan:
            errors.extend(semantic_errors("plan", plan))
        receipt = value.get("data", {}).get("receipt")
        if receipt:
            errors.extend(semantic_errors("receipt", receipt))
            outcome = receipt["outcome"]
            if value["ok"] and value["phase"] in {"apply", "result"}:
                if outcome["execution"] != "completed":
                    errors.append("successful final application must finish execution")
                if outcome["change"] in {"partial", "unknown", "rolled_back"}:
                    errors.append("partial, unknown or restored final writes are not success")
                if outcome["change"] == "applied" and outcome["verification"]["status"] != "passed":
                    errors.append("successful final application cannot omit required verification")
                elif outcome["verification"]["status"] not in {"passed", "not_applicable"}:
                    required = any(c["required"] for c in outcome["verification"]["checks"] + outcome["verification"]["not_checked"])
                    if required:
                        errors.append("successful no-op cannot omit required verification")
            if outcome["change"] == "unknown" and value.get("error", {}).get("retryable"):
                errors.append("unknown outcomes cannot advertise blind retry")
        for profile in ["operation_status", "workflow", "query_page"]:
            nested = value.get("data", {}).get(profile)
            if nested is not None:
                errors.extend(semantic_errors(profile.replace("_", "-"), nested))
        workflow = value.get("data", {}).get("workflow")
        if workflow and value["ok"] and value["phase"] in {"apply", "result"}:
            if any(step["status"] != "completed" for step in workflow["steps"]):
                errors.append("a final successful workflow must complete every requested step")
    elif kind == "plan":
        preview = value["preview"]
        trial = preview["trial_snapshot"]
        if preview["level"] == "trial_observed":
            if not trial or trial["source"] != "trial" or trial["id"] == value["base_snapshot"]["id"]:
                errors.append("trial_observed needs an independent trial snapshot")
            if "physical" in value["effects"]:
                errors.append("a real physical effect cannot be an isolated observed trial")
    elif kind == "reference":
        errors.extend(reference_errors(value))
    elif kind == "operation-status":
        receipt = value["receipt"]
        if receipt:
            errors.extend(semantic_errors("receipt", receipt))
            if receipt["operation_id"] != value["operation_id"]:
                errors.append("status and receipt operation identities must agree")
            identity_keys = ["mode", "engine_id", "instance_id", "object_id", "locator"]
            if value["target"] is None or any(value["target"][key] != receipt["target"][key] for key in identity_keys):
                errors.append("status and receipt must describe the same target")
            execution = receipt["outcome"]["execution"]
            if value["status"] == "completed" and execution != "completed":
                errors.append("completed status cannot contain unfinished receipt execution")
            if value["status"] == "cancelled" and execution not in {"not_started", "interrupted"}:
                errors.append("cancelled status needs a stopped or never-started execution")
            if value["status"] == "queued" and execution != "not_started":
                errors.append("queued status cannot describe an already-started operation")
        if value["stop_observed"] and value["status"] in {"queued", "running", "cancel_requested"}:
            errors.append("an active task cannot claim an observed stop")
    elif kind == "workflow":
        steps = value["steps"]
        ids = [step["id"] for step in steps]
        if len(ids) != len(set(ids)):
            errors.append("workflow step identities must be unique")
        by_id = {step["id"]: step for step in steps}
        for step in steps:
            if any(dependency not in by_id for dependency in step["depends_on"]):
                errors.append("workflow dependencies must identify existing steps")
            receipt = step["receipt"]
            modifying = any(effect in step["effects"] for effect in ["change", "persist", "deliver", "configure", "physical"])
            executing = step["phase"] not in {"plan", "submit", "status"}
            if receipt:
                errors.extend(semantic_errors("receipt", receipt))
                if receipt["operation_id"] != step["operation_id"]:
                    errors.append("step and receipt operation identities must agree")
                if not set(receipt["effects"]).issubset(set(step["effects"])):
                    errors.append("step effects cannot hide effects reported by its receipt")
                if step["status"] == "completed" and modifying and executing:
                    outcome = receipt["outcome"]
                    if outcome["execution"] != "completed" or outcome["change"] in {"partial", "unknown", "rolled_back"}:
                        errors.append("a completed write step needs a completed successful application")
                    if outcome["change"] == "applied" and outcome["verification"]["status"] != "passed":
                        errors.append("a completed write step needs scoped readback verification")
            if step["status"] == "completed" and modifying and executing:
                if not receipt:
                    errors.append("completed modifying steps cannot substitute output refs for a receipt")
            if step["status"] in {"running", "completed", "failed", "cancelled"}:
                for dependency in step["depends_on"]:
                    parent = by_id.get(dependency)
                    if parent is None:
                        continue
                    if parent["status"] != "completed":
                        errors.append("a dependent step cannot run before its prerequisite completes")
                    if parent["receipt"]:
                        verification = parent["receipt"]["outcome"]["verification"]
                        if any(check["required"] and check["status"] != "passed" for check in verification["checks"]) or any(check["required"] for check in verification["not_checked"]):
                            errors.append("dependent steps cannot bypass required prerequisite checks")
        incoming = {identifier: sum(dependency in by_id for dependency in step["depends_on"]) for identifier, step in by_id.items()}
        downstream = {identifier: [] for identifier in by_id}
        for identifier, step in by_id.items():
            for dependency in step["depends_on"]:
                if dependency in by_id:
                    downstream[dependency].append(identifier)
        ready = [identifier for identifier, count in incoming.items() if count == 0]
        visited = 0
        while ready:
            identifier = ready.pop()
            visited += 1
            for child in downstream[identifier]:
                incoming[child] -= 1
                if incoming[child] == 0:
                    ready.append(child)
        if visited != len(by_id):
            errors.append("workflow dependencies must be acyclic")
        counts = Counter(step["status"] for step in steps)
        if value["summary"]["total"] != len(steps) or any(value["summary"][status] != counts[status] for status in value["summary"] if status != "total"):
            errors.append("workflow summary must exactly count the step results")
    elif kind == "query-page":
        if value["count"] != len(value["items"]):
            errors.append("query count must equal the returned item count")
        if value["limits"]["effective"] is not None and value["count"] > value["limits"]["effective"]:
            errors.append("query items cannot exceed the effective output limit")
    elif kind == "adoption-lock":
        paths = []
        for item in value["files"]:
            try:
                canonical_relative_path(item["path"])
                canonical_relative_path(item["source_path"])
            except InputError:
                errors.append("adoption paths must stay within their declared relative roots")
            paths.append(path_identity(item["path"]))
        if len(paths) != len(set(paths)):
            errors.append("adoption paths must be unique on case-insensitive filesystems")
    elif kind == "release-manifest":
        paths = []
        for component in value["components"]:
            path = component["path"]
            normalized = PurePosixPath(path)
            if path != normalized.as_posix() or any(p in {".", ".."} for p in normalized.parts):
                errors.append("component paths must be canonical relative package paths")
            if path == "manifest.json":
                errors.append("manifest cannot contain its own checksum")
            try:
                canonical_relative_path(path)
            except InputError:
                errors.append("component paths must be safe on the declared target platforms")
            paths.append(path_identity(path))
        if len(paths) != len(set(paths)):
            errors.append("component paths must be unique on case-insensitive targets too")
        if value["source_dirty"]:
            errors.append("release manifests cannot describe uncommitted source")
        if value["artifact_kind"] == "cli_product" and not any(c["role"] == "cli" for c in value["components"]):
            errors.append("a CLI product must identify its CLI component")
    elif kind == "evidence":
        if value["package_sha256"] is None and not value["limitations"]:
            errors.append("development evidence without a package must explain its limit")
        if value["kind"] in {"real_application", "artifact_consumer"}:
            if not value["target"] or not value["snapshot_id"]:
                errors.append("real-result evidence must identify the target and checked snapshot")
    return errors


def document_errors() -> list[str]:
    errors, identifiers = [], set()
    expected = {
        "CORE-SPEC.md": "COR", "DRIVER-SPEC.md": "DRV",
        "DELIVERY-SPEC.md": "DEL", "VERIFICATION-SPEC.md": "VER",
    }
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    status = (ROOT / "STATUS").read_text(encoding="utf-8").strip()
    if status not in {"draft", "experimental", "stable"}:
        errors.append("STATUS must declare a supported publication maturity")
    for path in [ROOT / "README.md", ROOT / "AGENTS.md", *sorted((ROOT / "docs").glob("*.md"))]:
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            target = target.split("#", 1)[0]
            if not (path.parent / target).exists():
                errors.append(f"{path.relative_to(ROOT)}: missing local link {target}")
        if path.name in expected:
            if version not in text:
                errors.append(f"{path.name}: missing current spec version")
            if f"状态：`{status}`" not in text:
                errors.append(f"{path.name}: maturity differs from STATUS")
            found = re.findall(r"^### ([A-Z]{3}-\d{3})\b", text, re.M)
            if not found:
                errors.append(f"{path.name}: no addressable clauses")
            for identifier in found:
                if not identifier.startswith(expected[path.name] + "-") or identifier in identifiers:
                    errors.append(f"{path.name}: invalid or duplicate clause {identifier}")
                identifiers.add(identifier)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for product in ["ai-native-cli-spec", "kicad-cli", "xpedition-cli", "creo-cli"]:
        if product in readme:
            errors.append("README must describe the independent specification")
    return errors


def main() -> int:
    failures = []
    try:
        checked = validators()
        index = load(ROOT / "examples/index.json")
        expected_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        if index["spec_version"] != expected_version:
            failures.append("example index version differs from VERSION")
        seen = set()
        for item in index["examples"]:
            relative = item["path"]
            if relative in seen:
                failures.append(f"duplicate example {relative}")
            seen.add(relative)
            value = load(ROOT / relative)
            validator = checked[item["schema"]]
            schema_errors = list(validator.iter_errors(value))
            semantic = [] if schema_errors else semantic_errors(item["schema"].removesuffix(".schema.json"), value)
            valid = not schema_errors and not semantic
            if valid != item["valid"]:
                reason = [e.message for e in schema_errors] + semantic
                failures.append(f"{relative}: expected valid={item['valid']}, got {valid}: {reason}")
        actual = {p.relative_to(ROOT).as_posix() for d in ["valid", "invalid"] for p in (ROOT / "examples" / d).glob("*.json")}
        if actual != seen:
            failures.append("example index must enumerate every positive and negative fixture")
        failures.extend(document_errors())
    except (ValueError, OSError, KeyError, TypeError) as exc:
        failures.append(str(exc))
    print(json.dumps({"ok": not failures, "scope": "specification_structure_and_static_examples", "errors": failures}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
