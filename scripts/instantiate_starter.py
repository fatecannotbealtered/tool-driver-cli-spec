"""Create a no-clobber native CLI seed from local, explicitly pinned resources."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
SOURCE = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def regular_bytes(path):
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
        raise ValueError("Source must be a regular file without a link: " + str(path))
    if value.st_size > 8 * 1024 * 1024:
        raise ValueError("Source resource exceeds the declared 8 MiB file limit.")
    return path.read_bytes()


def check_output(path):
    path = Path(os.path.abspath(path))
    if os.path.lexists(path):
        raise ValueError("Output already exists; no files were changed.")
    for ancestor in path.parents:
        if ancestor.exists():
            value = ancestor.lstat()
            if not stat.S_ISDIR(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
                raise ValueError("Output cannot traverse a non-directory or linked ancestor.")
    return path.resolve()


def replace_values(value, replacements):
    if isinstance(value, dict):
        return {replace_values(key, replacements): replace_values(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_values(item, replacements) for item in value]
    if isinstance(value, str):
        for original, replacement in replacements.items():
            value = value.replace(original, replacement)
    return value


def source_identity(copied):
    manifest_path = SOURCE / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(regular_bytes(manifest_path).decode("utf-8"))
        declared = {item["path"]: item["sha256"] for item in manifest["components"]}
        for source_path, payload in copied.items():
            if declared.get(source_path) != sha(payload):
                raise ValueError("Copied source does not match its specification manifest: " + source_path)
        commit = manifest["source_commit"]
        dirty = bool(manifest["source_dirty"])
        kind = "local_specification_manifest"
    else:
        flags = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=SOURCE, capture_output=True, text=True, timeout=10, **flags)
        if result.returncode:
            raise ValueError("A local specification manifest or observable source Git commit is required.")
        commit = result.stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=SOURCE, capture_output=True, text=True, timeout=10, **flags)
        if status.returncode:
            raise ValueError("Source working-tree status could not be observed.")
        dirty, kind = bool(status.stdout.strip()), "git_checkout"
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise ValueError("Invalid observed source commit.")
    return {"source_commit": commit, "source_dirty": dirty, "kind": kind,
            "origin_authenticated": False,
            "limitations": ["Local provenance and copy hashes do not authenticate a publisher.",
                            "When source_dirty is true, copied file hashes identify the working bytes; the commit alone cannot reproduce them."]}


def vendor_payloads():
    payloads, sources, origins = {}, {}, {}
    for directory in ("schemas", "scripts", "development"):
        base = SOURCE / directory
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if "__pycache__" in path.parts or not path.is_file() or path.suffix not in {".py", ".json", ".md", ".txt"}:
                continue
            relative = path.relative_to(SOURCE).as_posix()
            content = regular_bytes(path)
            destination = ".agent/vendor/spec/" + relative
            payloads[destination], sources[relative] = content, content
            origins[destination] = relative
    for name in ("VERSION", "STATUS", "requirements-dev.txt"):
        content = regular_bytes(SOURCE / name)
        payloads[".agent/vendor/spec/" + name], sources[name] = content, content
        origins[".agent/vendor/spec/" + name] = name
    base = SOURCE / "packages" / "tool_driver_sdk"
    if (base / "tool_driver_sdk" / "__init__.py").is_file():
        base = base / "tool_driver_sdk"
    if not (base / "__init__.py").is_file():
        raise ValueError("The local SDK package is not present; no output was created.")
    for path in sorted(base.rglob("*")):
        if "__pycache__" in path.parts or not path.is_file() or path.suffix not in {".py", ".md", ".json"}:
            continue
        content = regular_bytes(path)
        relative = path.relative_to(base).as_posix()
        source_path = path.relative_to(SOURCE).as_posix()
        payloads[".agent/vendor/sdk/tool_driver_sdk/" + relative] = content
        origins[".agent/vendor/sdk/tool_driver_sdk/" + relative] = source_path
        sources[source_path] = content
    return payloads, sources, origins


def instantiate(name, output, profile, registry_path=None):
    if len(name) > 64 or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name):
        raise ValueError("Name must be a lowercase product identifier of at most 64 characters.")
    if profile not in {"file", "session", "device"}:
        raise ValueError("Profile must be file, session or device.")
    output = check_output(output)
    template = SOURCE / "starter" / "common"
    replacements = {"{{NAME}}": name, "{{VERSION}}": VERSION, "{{PROFILE}}": profile}
    payloads = {path.name: replace_values(regular_bytes(path).decode("utf-8"), replacements).encode("utf-8")
                for path in sorted(template.iterdir()) if path.is_file()}
    registry = json.loads(regular_bytes(Path(registry_path)).decode("utf-8")) if registry_path else json.loads(payloads["registry.json"])
    previous_name = registry["name"]
    if registry_path:
        registry = replace_values(registry, {"urn:" + previous_name + ":": "urn:" + name + ":"})
    registry.update(name=name, product_version=VERSION, entrypoint=name)
    for command in registry["commands"]:
        command.update(modes=[profile], maturity="draft", evidence_refs=[])
        for environment in command["environments"]:
            environment.update(mode=profile, adapter_version=VERSION)
            environment.setdefault("limitations", []).append("Starter selection is a declared mode, not a native environment verification.")
    from generate_product import build_contract
    contract = build_contract(registry, public_root=SOURCE)
    for endpoint in ("context", "doctor"):
        commands = [command for command in registry["commands"] if command["path"] == endpoint]
        if len(commands) != 1 or commands[0]["phases"] != ["observe"] or commands[0]["effects"] != ["observe"] or commands[0]["parameters"]:
            raise ValueError("The starter requires unambiguous read-only context/doctor declarations without arguments.")
    # These are caller-selected specification code paths, never strings supplied by the registry.
    sys.path.insert(0, str(SOURCE / "packages"))
    from tool_driver_sdk import ContractValidator, ErrorCatalog, StubAdapter, serve_cli
    callbacks_spec = importlib.util.spec_from_file_location("_starter_readonly_callbacks", template / "callbacks.py")
    callbacks = importlib.util.module_from_spec(callbacks_spec)
    callbacks_spec.loader.exec_module(callbacks)
    project = {"name": name, "product_version": VERSION, "profile": profile, "native_status": "not_configured"}
    validator = ContractValidator(SOURCE)
    catalog = ErrorCatalog.from_reference(contract["reference"])
    stub = StubAdapter(validator, catalog)
    for endpoint in ("context", "doctor"):
        result = serve_cli(contract, validator, stub, [endpoint],
                           context_provider=lambda invocation: callbacks.context(registry, project),
                           doctor_provider=lambda invocation: callbacks.doctor(registry, project))
        if not result.envelope["ok"]:
            raise ValueError("Registry result declarations do not match the starter's read-only callback DTOs.")
    payloads["registry.json"] = (json.dumps(registry, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    vendor, sources, origins = vendor_payloads()
    identity = source_identity(sources)
    identity["managed_source_sha256"] = sha(json.dumps({path: sha(content) for path, content in sorted(sources.items())},
                                                     sort_keys=True).encode("utf-8"))
    lock = {"format_version": "1.0", "spec_version": (SOURCE / "VERSION").read_text().strip(),
            "schema_version": "1.0", "source": identity,
            "files": [{"path": path, "source_path": origins[path], "sha256": sha(content)} for path, content in sorted(vendor.items())]}
    payloads.update(vendor)
    payloads[".agent/starter-lock.json"] = (json.dumps(lock, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    payloads[".agent/project.json"] = (json.dumps(project, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    payloads["requirements.txt"] = regular_bytes(SOURCE / "requirements-dev.txt")
    payloads[".gitignore"] = b"__pycache__/\n*.pyc\n.venv/\ndist/\n"
    if len(payloads) > 4096 or sum(map(len, payloads.values())) > 32 * 1024 * 1024:
        raise ValueError("Starter payload exceeds the declared file count or byte limit.")
    output.mkdir(parents=True, exist_ok=False)
    written = []
    try:
        for relative, content in sorted(payloads.items()):
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(content)
            written.append(relative)
    except OSError as error:
        # Preserve actual partial output for inspection; never delete an unverified tree.
        return {"ok": False, "error": "Partial starter creation: " + str(error), "output": str(output),
                "state": "partial", "written_files": written, "native_status": "not_configured"}
    return {"ok": True, "output": str(output), "name": name, "product_version": VERSION,
            "spec_version": lock["spec_version"], "profile": profile, "files": len(written),
            "source": identity, "native_status": "not_configured", "native_verified": False,
            "scope": "local_development_starter_only"}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", choices=["file", "session", "device"], required=True)
    parser.add_argument("--registry", type=Path)
    try:
        args = parser.parse_args(argv)
        result = instantiate(args.name, args.output, args.profile, args.registry)
    except (OSError, ValueError, KeyError, ImportError, subprocess.SubprocessError) as error:
        result = {"ok": False, "error": str(error), "state": "not_created", "native_verified": False}
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
