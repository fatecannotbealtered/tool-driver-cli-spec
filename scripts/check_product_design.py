"""Check a development design record and its local evidence; never dispatch an adapter.

This proves record consistency and artifact hashes, not application completeness,
evidence authenticity, interface reachability or the quality of a command tree.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import stat
import sys
import time
from pathlib import Path

from check_spec import instance_errors, verification_helpers
from contract_io import InputError, canonical_relative_path, parse_json, read_regular_file

LIMIT = 8 * 1024 * 1024
LIMITATIONS = [
    "Checks declared scope, cross-references, local bytes and recorded run bindings only.",
    "Does not authenticate evidence, survey the application, execute adapters or establish command-tree quality.",
    "Declared-command FCC and scoped application capability coverage are separate denominators.",
    "Excluded/deferred capabilities and blocked/unknown/not_run results are not verified coverage.",
]


def artifact_bytes(root: Path, relative: str) -> bytes:
    """No network, external paths, links, devices or unbounded reads."""
    canonical_relative_path(relative)
    root = Path(os.path.abspath(root))
    path = root / relative
    for parent in [path, *path.parents]:
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise InputError("linked evidence paths are not permitted")
    return read_regular_file(path, LIMIT)


def observed_quantity(payload: bytes, pointer: str):
    value = parse_json(payload)
    if pointer and not pointer.startswith("/"):
        raise InputError("measurement pointer must be an RFC 6901 JSON Pointer")
    for part in pointer.split("/")[1:] if pointer else []:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not part.isdigit() or str(int(part)) != part:
                raise InputError("measurement array index must be canonical")
            value = value[int(part)]
        else:
            value = value[part]
    return value


def ran_command(invocations: list[str], tool: str, path: str) -> bool:
    expected = [tool, *path.split()]
    for invocation in invocations:
        try:
            words = shlex.split(invocation)
        except ValueError:
            continue
        if words[:len(expected)] == expected:
            return True
    return False


def check_design(registry: dict, *, registry_dir: Path | None = None, require: bool = False) -> dict:
    record = registry.get("design")
    report = {"scope": "product_development_design_consistency", "recorded": record is not None,
              "origin_authenticated": False, "record": record, "coverage": None, "checked_artifacts": [],
              "limitations": LIMITATIONS.copy(), "errors": []}
    errors = report["errors"]
    if record is None:
        if require:
            errors.append("design record is required by this development gate")
        return report
    errors.extend(instance_errors("product-design", record))
    if errors:
        return report

    def indexed(items, label, key="id"):
        values = {item[key]: item for item in items}
        if len(values) != len(items):
            errors.append(f"duplicate {label} identifiers")
        return values

    capabilities = indexed(record["capabilities"], "capability")
    evidence = indexed(record["evidence"], "evidence")
    tasks = indexed(record["tasks"], "task")
    mappings = indexed(record["commands"], "command", "path")
    tests = indexed(record["tests"], "test")
    commands = {item["path"]: item for item in registry["commands"]}
    inventory = set(record["scope"]["inventory_ids"])
    denominator = set(record["coverage"]["denominator_ids"])
    if inventory != set(capabilities) or denominator != inventory:
        errors.append("scope inventory and coverage denominator must enumerate exactly the declared capabilities")
    if set(mappings) != set(commands):
        errors.append("design commands must account for every registry command, without extra paths")

    def refs(values, available, label):
        missing = sorted(set(values) - set(available))
        if missing:
            errors.append(f"dangling {label} references: {missing}")

    refs(record["application"]["evidence_refs"], evidence, "application evidence")
    refs(record["scope"]["inventory_evidence_refs"], evidence, "inventory evidence")
    runs, payloads = {}, {}
    for identity, item in evidence.items():
        try:
            if registry_dir is None:
                raise InputError("evidence needs an explicit registry directory")
            payload = artifact_bytes(registry_dir, item["path"])
            digest = hashlib.sha256(payload).hexdigest()
            if digest != item["sha256"]:
                raise InputError("evidence hash does not match the recorded bytes")
            payloads[identity] = payload
            report["checked_artifacts"].append({"id": identity, "path": item["path"], "sha256": digest})
            if item["kind"] == "real_run":
                raw = parse_json(payload)
                problems = instance_errors("evidence", raw)
                if problems:
                    raise InputError("real run must satisfy the pinned evidence contract: " + "; ".join(problems[:3]))
                binding = item.get("binding")
                if not binding or raw["kind"] not in {"real_application", "artifact_consumer"}:
                    raise InputError("real run needs a binding and real_application/artifact_consumer evidence; fixtures do not qualify")
                if raw["evidence_id"] != binding["run_id"] or raw["source_commit"] != binding["source_commit"]:
                    raise InputError("run ID/source commit differ from the evidence bytes")
                app = record["application"]
                if raw["target"]["mode"] != app["environment"]["mode"]:
                    raise InputError("run target mode differs from the scoped application mode")
                if binding["application_version"] != app["version"]:
                    raise InputError("run application version differs from the surveyed application")
                if any(raw["environment"][key] != binding[key] or binding[key] != app["environment"][key]
                       for key in ("platform", "arch")):
                    raise InputError("run environment differs from the evidence or scoped application environment")
                if not any(c["name"] == app["name"] and c["version"] == app["version"]
                           and c["role"] in {"application", "device"} and c["identity_status"] == "observed"
                           for c in raw["environment"]["components"]):
                    raise InputError("real run lacks observed application/version identity")
                if not raw["checks"] or not any(c["required"] for c in raw["checks"]):
                    raise InputError("real run needs actual required readback checks")
                runs[identity] = raw
            elif "binding" in item:
                raise InputError("only real_run evidence may declare a run binding")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"evidence {identity}: {exc}")

    for identity, raw in list(runs.items()):
        try:
            ref = evidence[identity]["readback_ref"]
            if evidence.get(ref, {}).get("kind") != "readback" or ref not in payloads:
                raise InputError("real run needs a hashed readback profile artifact")
            profile = parse_json(payloads[ref])
            problems = instance_errors("verification-result", profile)
            if problems:
                raise InputError("readback profile is invalid: " + "; ".join(problems[:3]))
            result = verification_helpers().evaluate(profile, target=raw["target"],
                                                     snapshot=profile["snapshot"], bind=True)
            if profile["snapshot"]["id"] != raw["snapshot_id"] or result["status"] != "passed":
                raise InputError("expected/observed readback does not pass for the recorded target/snapshot")
            for observation in profile["observations"]:
                source_ref = observation["source"]["evidence_ref"]
                if evidence.get(source_ref, {}).get("kind") != "observation" or source_ref not in payloads:
                    raise InputError("readback needs hashed observation artifacts; a success declaration is insufficient")
                pointer = evidence[source_ref]["measurements"].get(observation["requirement_id"])
                if pointer is None:
                    raise InputError("observation artifact must identify the measured quantity for this requirement")
                measured = observed_quantity(payloads[source_ref], pointer)
                if json.dumps(measured, sort_keys=True) != json.dumps(observation["observed"], sort_keys=True):
                    raise InputError("profile observed value differs from the actual observation artifact")
            raw["design_checked_readback_ids"] = {r["id"] for r in profile["requirements"]}
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            runs.pop(identity)
            errors.append(f"evidence {identity}: {exc}")

    for cap in capabilities.values():
        refs(cap["evidence_refs"], evidence, "capability evidence")
        if cap["application_support"] != "unknown" and not any(
                evidence.get(e, {}).get("kind") in {"document", "real_run"} for e in cap["evidence_refs"]):
            errors.append(f"capability {cap['id']}: known application support needs survey evidence")
        if cap["application_support"] != "unknown" and not record["scope"]["inventory_evidence_refs"]:
            errors.append(f"capability {cap['id']}: known survey needs inventory source evidence")
        mapped = [m for m in mappings.values() if cap["id"] in m["capability_ids"]]
        exposed = bool(mapped)
        if exposed != (cap["cli_exposure"] == "exposed") or exposed != (cap["disposition"] == "exposed"):
            errors.append(f"capability {cap['id']}: disposition/CLI exposure disagree with command mappings")
        linked = {t for m in mapped for t in m["task_ids"] if cap["id"] in tasks.get(t, {}).get("capability_ids", [])}
        if cap["adapter"] == "implemented" and not any(tasks[t]["adapter_entries"] for t in linked):
            errors.append(f"capability {cap['id']}: implemented needs a recorded implementation entry")
        if cap["application_support"] == "unsupported" and cap["testing"] == "verified":
            errors.append(f"capability {cap['id']}: unsupported application capability cannot be verified")
        if cap["testing"] == "verified":
            if (cap["application_support"] != "supported" or cap["automation"] != "reachable"
                    or cap["adapter"] != "implemented" or not exposed
                    or not any(tasks.get(t, {}).get("status") == "supported" for t in linked)):
                errors.append(f"capability {cap['id']}: verified needs support, reachability, implementation, exposure and a supported task")

    for mapping in mappings.values():
        refs(mapping["capability_ids"], capabilities, "command capability")
        refs(mapping["task_ids"], tasks, "command task")
        if mapping["role"] == "domain" and (not mapping["capability_ids"] or not mapping["task_ids"]):
            errors.append(f"command {mapping['path']}: a domain command needs capability and task mappings")
        if not set(mapping["capability_ids"]).issubset({c for t in mapping["task_ids"] for c in tasks.get(t, {}).get("capability_ids", [])}):
            errors.append(f"command {mapping['path']}: mapped tasks omit a declared capability")
        if mapping["role"] == "tool_management" and mapping["capability_ids"]:
            errors.append(f"command {mapping['path']}: tool management must explain its role separately from application coverage")
        for tid in mapping["task_ids"]:
            task = tasks.get(tid)
            if task and (mapping["path"] not in task["command_paths"]
                         or not set(mapping["capability_ids"]).intersection(task["capability_ids"])):
                errors.append(f"command {mapping['path']}: task {tid} does not close the capability/task/command mapping")
        command = commands.get(mapping["path"])
        if command and command["driver"]["maturity"] in {"verified", "stable"} and mapping["role"] == "domain":
            if not any(tasks.get(t, {}).get("status") == "supported" for t in mapping["task_ids"]):
                errors.append(f"command {mapping['path']}: mature domain declaration needs a supported task")

    for test in tests.values():
        refs([test["task_id"]], tasks, "test task")
        refs([test["command_path"]], commands, "test command")
        if test["evidence_ref"] is not None:
            refs([test["evidence_ref"]], evidence, "test evidence")
        raw = runs.get(test["evidence_ref"])
        command = commands.get(test["command_path"])
        task = tasks.get(test["task_id"])
        if task and test["id"] not in task["test_ids"]:
            errors.append(f"test {test['id']}: task does not refer back to the test")
        if test["status"] == "passed":
            checks = {c["id"]: c for c in raw["checks"]} if raw else {}
            if (not raw or not command or not ran_command(raw["commands"], registry["name"], test["command_path"])
                    or command["driver"]["capability_id"] not in raw["capabilities"]
                    or not set(test["check_ids"]).issubset(raw["design_checked_readback_ids"])
                    or not test["check_ids"] or any(i not in checks or checks[i]["status"] != "passed" for i in test["check_ids"])
                    or any(c["required"] and c["status"] != "passed" for c in checks.values())):
                errors.append(f"test {test['id']}: passed needs matching real run, command, capability and passed required checks")

    for task in tasks.values():
        tid = task["id"]
        refs(task["capability_ids"], capabilities, "task capability")
        refs(task["command_paths"], commands, "task command")
        refs(task["test_ids"], tests, "task test")
        readback_ids = {c["id"] for c in task["readback"]}
        if len(readback_ids) != len(task["readback"]):
            errors.append(f"task {tid}: duplicate readback criterion IDs")
        if not set(task["capability_ids"]).issubset({c for p in task["command_paths"] for c in mappings.get(p, {}).get("capability_ids", [])}):
            errors.append(f"task {tid}: mapped commands omit a task capability")
        for path in task["command_paths"]:
            mapping = mappings.get(path)
            if mapping and (tid not in mapping["task_ids"] or not set(task["capability_ids"]).intersection(mapping["capability_ids"])):
                errors.append(f"task {tid}: command {path} does not map back to the task/capability")
        for parameter in task["critical_parameters"]:
            command = commands.get(parameter["command_path"])
            if (parameter["command_path"] not in task["command_paths"] or not command
                    or parameter["name"] not in {p["name"] for p in command["params"]}):
                errors.append(f"task {tid}: critical parameter does not exist on its mapped command")
        for entry in task["adapter_entries"]:
            if entry["command_path"] not in task["command_paths"] or evidence.get(entry["artifact_ref"], {}).get("kind") != "implementation":
                errors.append(f"task {tid}: adapter entry needs a mapped command and hashed implementation artifact")
        for test_id in task["test_ids"]:
            test = tests.get(test_id)
            if test and (test["task_id"] != tid or test["command_path"] not in task["command_paths"]
                         or not set(test["check_ids"]).issubset(readback_ids)):
                errors.append(f"task {tid}: test {test_id} does not map to its command/readback criteria")
        if task["status"] == "supported":
            caps = [capabilities.get(c, {}) for c in task["capability_ids"]]
            if not caps or any(c.get("application_support") != "supported" or c.get("automation") != "reachable"
                               or c.get("adapter") != "implemented" or c.get("cli_exposure") != "exposed" for c in caps):
                errors.append(f"task {tid}: supported needs reachable implemented application capabilities")
            paths = set(task["command_paths"])
            if not paths or paths != {e["command_path"] for e in task["adapter_entries"]} or not readback_ids:
                errors.append(f"task {tid}: supported needs real adapter entries and readback criteria for its commands")
            app = record["application"]
            for path in paths & set(commands):
                if not any(e["application"] == app["name"] and e["application_version"] == app["version"]
                           and e["mode"] == app["environment"]["mode"]
                           and all(e[k] in {"any", app["environment"][k]} for k in ("platform", "arch"))
                           for e in commands[path]["driver"]["environments"]):
                    errors.append(f"task {tid}: command {path} does not declare the tested application environment")
            required = {(path, p["name"]) for path in paths if path in commands for p in commands[path]["params"] if p["required"]}
            if not required.issubset({(p["command_path"], p["name"]) for p in task["critical_parameters"]}):
                errors.append(f"task {tid}: supported task omits required critical parameters")
            passed = [tests[t] for t in task["test_ids"] if t in tests and tests[t]["status"] == "passed"]
            if paths != {t["command_path"] for t in passed} or not readback_ids.issubset({c for t in passed for c in t["check_ids"]}):
                errors.append(f"task {tid}: supported task lacks actual passing command/readback tests")

    report["coverage"] = {
        "scope": record["scope"]["description"], "denominator_ids": sorted(denominator), "denominator": len(denominator),
        "exposed": sum(c["disposition"] == "exposed" for c in capabilities.values()),
        "verified": sum(c["testing"] == "verified" for c in capabilities.values()),
        "dispositions": {s: sum(c["disposition"] == s for c in capabilities.values()) for s in ("exposed", "deferred", "excluded", "unknown")},
        "supported_tasks": sum(t["status"] == "supported" for t in tasks.values()),
        "declared_command_fcc": "not_evaluated_by_this_checker",
    }
    return report


def main(argv=None):
    # Reuse the generator's bounded input and full registry/reference validation.
    from generate_product import GenerationError, Parser, build_contract, load_registry
    started = time.monotonic()
    parser = Parser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--require-design", action="store_true")
    try:
        args = parser.parse_args(argv)
        path = Path(os.path.abspath(args.registry))
        registry = load_registry(path)
        build_contract(registry, registry_dir=path.parent)
        report = check_design(registry, registry_dir=path.parent, require=args.require_design)
        if report["errors"]:
            raise GenerationError("development design is inconsistent", errors=report["errors"])
        value = {"ok": True, "schema_version": "1.0", "data": report,
                 "meta": {"duration_ms": round((time.monotonic() - started) * 1000, 3)}}
        code = 0
    except (GenerationError, OSError, ValueError) as exc:
        value = {"ok": False, "schema_version": "1.0", "error": {
            "code": getattr(exc, "code", "E_VALIDATION"), "message": str(exc), "retryable": False,
            "details": {"scope": "product_development_design_consistency", "errors": getattr(exc, "errors", []),
                        "next_action": "Correct scope, mappings and actual evidence; do not replace unknown with success."}},
                 "meta": {"duration_ms": round((time.monotonic() - started) * 1000, 3)}}
        code = 2
    sys.stdout.buffer.write((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))
    return code


if __name__ == "__main__":
    sys.exit(main())
