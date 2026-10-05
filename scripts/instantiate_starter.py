"""Create a new driver CLI project from the starter: templates, pinned specification and SDK copies, generated contract.

The output directory must not exist. Nothing is downloaded, installed, published or started.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
SOURCE = Path(__file__).resolve().parents[1]
TEMPLATE = SOURCE / "starter" / "common"
VERSION = "0.1.0"
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
TEXT_SUFFIXES = {".md", ".json", ".py", ".toml", ".yml", ".txt", ""}
VENDORED_SCRIPTS = ("check_spec.py", "contract_io.py", "validate_contract.py", "generate_product.py", "check_agent_eval.py",
                    "check_product_design.py")


class StarterError(ValueError):
    def __init__(self, message: str, code: str = "E_VALIDATION", next_action: str = "Fix the argument and run again."):
        super().__init__(message)
        self.code, self.next_action = code, next_action


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def regular_bytes(path: Path) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & REPARSE_POINT:
        raise StarterError(f"source must be a regular file without a link: {path}", "E_CONFIG")
    if info.st_size > 8 * 1024 * 1024:
        raise StarterError("source file exceeds the 8 MiB limit", "E_CONFIG")
    return path.read_bytes()


def destination_of(relative: str, name: str, package: str) -> str:
    if relative == "gitignore":
        return ".gitignore"
    for prefix, replacement in (("agent/", ".agent/"), ("github/", ".github/"), ("package/", package + "/"), ("skill/", f"skills/{name}/")):
        if relative.startswith(prefix):
            return replacement + relative[len(prefix):]
    return relative


def source_identity() -> dict:
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=SOURCE, capture_output=True, text=True, timeout=10,
                             creationflags=HIDDEN)
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=SOURCE, capture_output=True, text=True, timeout=10,
                                creationflags=HIDDEN)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=SOURCE, capture_output=True, text=True, timeout=10,
                                creationflags=HIDDEN)
    except (OSError, subprocess.SubprocessError):
        top = commit = status = None
    if (top is None or top.returncode or Path(top.stdout.strip()).resolve() != SOURCE.resolve()
            or commit is None or commit.returncode or status is None or status.returncode
            or not re.fullmatch(r"[0-9a-f]{40}", commit.stdout.strip())):
        return {"source_commit": None, "source_dirty": None, "kind": "unversioned_copy", "origin_authenticated": False,
                "limitations": ["No Git commit was observable; the file hashes below are the only identity of these copies."]}
    return {"source_commit": commit.stdout.strip(), "source_dirty": bool(status.stdout.strip()), "kind": "git_checkout",
            "origin_authenticated": False,
            "limitations": ["Local provenance and copy hashes do not authenticate a publisher.",
                            "When source_dirty is true, the hashes identify the working bytes; the commit alone cannot reproduce them."]}


def vendored() -> dict[str, tuple[str, bytes]]:
    """destination -> (source path, bytes) for every pinned copy."""
    files: dict[str, tuple[str, bytes]] = {}

    def add(source: Path, destination: str):
        files[destination] = (source.relative_to(SOURCE).as_posix(), regular_bytes(source))

    for name in ("VERSION", "STATUS"):
        add(SOURCE / name, f".agent/driver/{name}")
    for folder, pattern in (("base", "**/*"), ("contract", "*.json"), ("docs", "*.md"), ("schemas", "*.schema.json")):
        for path in sorted((SOURCE / folder).glob(pattern)):
            if path.is_file():
                add(path, f".agent/driver/{path.relative_to(SOURCE).as_posix()}")
    for name in VENDORED_SCRIPTS:
        add(SOURCE / "scripts" / name, f".agent/driver/scripts/{name}")
    for path in sorted((SOURCE / "packages" / "tool_driver_sdk").glob("*.py")):
        add(path, f".agent/vendor/sdk/tool_driver_sdk/{path.name}")
    return files


def metadata_text(value: str | None, label: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise StarterError(f"--{label} must be one nonempty line of at most {limit} characters.")
    return value.strip()


def instantiate(name: str, output: Path, profile: str, *, description: str | None = None,
                repo: str | None = None, author: str | None = None) -> dict:
    if len(name) > 64 or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name):
        raise StarterError("--name must be a lowercase kebab-case product name of at most 64 characters.",
                            next_action="Use a name such as sample-driver.")
    if profile not in {"file", "session", "device"}:
        raise StarterError("--profile must be file, session or device.")
    description = metadata_text(description, "description", 512) or f"A driver CLI for AI agents ({profile} mode)."
    author = metadata_text(author, "author", 128)
    repo = metadata_text(repo, "repo", 2048)
    if repo:
        try:
            address = urlsplit(repo)
            if (address.scheme != "https" or not address.hostname or address.username or address.password
                    or address.query or address.fragment or any(char.isspace() for char in repo)):
                raise ValueError
            address.port
        except ValueError as exc:
            raise StarterError("--repo must be an HTTPS repository URL without credentials, query or fragment.") from exc
    output = Path(os.path.abspath(output))
    if os.path.lexists(output):
        raise StarterError("The output already exists; nothing was changed.", "E_CONFLICT", "Choose a new output directory.")
    package = name.replace("-", "_")
    replacements = {"{{NAME}}": name, "{{PACKAGE}}": package, "{{VERSION}}": VERSION, "{{PROFILE}}": profile,
                    "{{DATE}}": datetime.now(timezone.utc).date().isoformat(), "{{ENV_PREFIX}}": name.upper().replace("-", "_"),
                    "{{DESCRIPTION_HTML}}": html.escape(description), "{{DESCRIPTION_JSON}}": json.dumps(description, ensure_ascii=False),
                    "{{AUTHOR_HTML}}": html.escape(author) if author else "Not configured / 待配置",
                    "{{REPOSITORY_HTML}}": f'<a href="{html.escape(repo, quote=True)}">{html.escape(repo)}</a>' if repo else "Not configured / 待配置",
                    "{{AUTHORS_TOML}}": "authors = [{name = " + json.dumps(author, ensure_ascii=False) + "}]" if author else "# Configure authors when the maintainer is known.",
                    "{{REPOSITORY_TOML}}": "[project.urls]\nRepository = " + json.dumps(repo, ensure_ascii=False) if repo else "# Configure [project.urls] when the repository exists."}
    payloads: dict[str, bytes] = {}
    for path in sorted(TEMPLATE.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(TEMPLATE).as_posix()
        content = regular_bytes(path)
        if path.suffix in TEXT_SUFFIXES:
            text = content.decode("utf-8")
            # User metadata is not another template; substitute once without recursive expansion.
            text = re.sub(r"\{\{[A-Z_]+\}\}", lambda match: replacements.get(match.group(), match.group()), text)
            content = text.encode("utf-8")
        payloads[destination_of(relative, name, package)] = content
    copies = vendored()
    base_lock = json.loads(copies[".agent/driver/base/base-lock.json"][1])
    source = source_identity()
    # An adoption lock (adoption-lock schema) for copies taken from a checkout rather than a published bundle.
    lock = {"spec_version": (SOURCE / "VERSION").read_text(encoding="utf-8").strip(), "schema_version": "2.0",
            "source_kind": source["kind"], "source_commit": source["source_commit"], "source_dirty": source["source_dirty"],
            "package_sha256": None,
            "base": {"spec": base_lock["spec"], "tag": base_lock["tag"], "commit": base_lock["commit"]},
            "files": [{"path": destination, "source_path": source_path, "sha256": sha(content)}
                      for destination, (source_path, content) in sorted(copies.items())],
            "limitations": source["limitations"]}
    for destination, (_, content) in copies.items():
        payloads[destination] = content
    payloads[".agent/driver/starter-lock.json"] = (json.dumps(lock, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output.mkdir(parents=True, exist_ok=False)
    written = []
    try:
        for relative, content in sorted(payloads.items()):
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(content)
            written.append(relative)
    except OSError as exc:
        raise StarterError(f"Partial starter creation after {len(written)} files: {exc}", "E_IO",
                           "Inspect the partial output; it was not deleted.") from exc
    sys.path.insert(0, str(SOURCE / "scripts"))
    from generate_product import GenerationError, generate_registry, load_registry
    from validate_contract import validate_value
    problems = validate_value("adoption-lock", lock)
    if problems:
        raise StarterError("The starter lock does not satisfy the adoption-lock schema: " + "; ".join(problems[:5]), "E_CONFIG",
                           "Report this starter defect; the output directory was kept for inspection.")
    try:
        generated = generate_registry(load_registry(output / "registry.json"), output / package / "generated", registry_dir=output)
    except GenerationError as exc:
        raise StarterError(f"The starter registry could not be generated: {exc} {exc.errors[:5]}", "E_CONFIG",
                           "Report this starter defect; the output directory was kept for inspection.") from exc
    smoke = self_check(output, package, name)
    return {"output": str(output), "name": name, "package": package, "profile": profile, "product_version": VERSION,
            "metadata": {"description": description, "repo": repo, "author": author},
            "spec_version": lock["spec_version"], "base": lock["base"], "files": len(written) + len(generated["files"]) + 1,
            "source": {"kind": lock["source_kind"], "commit": lock["source_commit"], "dirty": lock["source_dirty"],
                       "origin_authenticated": False, "limitations": lock["limitations"]},
            "self_check": smoke, "native_status": "not_implemented",
            "next_steps": [f"cd {output}", "python -m pip install -r requirements.txt", "python check_project.py",
                           "python -m unittest discover -s tests -v", f"python -m {package} reference --index",
                           f"implement {package}/adapter.py, then raise each command's maturity only with evidence"]}


def self_check(output: Path, package: str, name: str) -> list[dict]:
    """Run reference, context and doctor in process with the stub adapter and an isolated state directory."""
    sys.path.insert(0, str(SOURCE / "packages"))
    from tool_driver_sdk import ContractValidator, DriverCLI, load_contract
    spec = importlib.util.spec_from_file_location("_starter_adapter", output / package / "adapter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    contract = load_contract(output / package / "generated" / "product_contract.json")
    prefix = name.upper().replace("-", "_")
    results = []
    with tempfile.TemporaryDirectory(prefix="starter-check-") as temporary:
        environ = {prefix + "_STATE_DIR": str(Path(temporary) / "state"), prefix + "_SCOPE_FILE": str(Path(temporary) / "none.json")}
        with DriverCLI(contract, module.Adapter(), validator=ContractValidator(output / ".agent" / "driver"), environ=environ,
                       home=Path(temporary)) as cli:
            for argv in (["reference", "--index"], ["context"], ["doctor"], ["target", "inspect", "--target-id", "t1"]):
                result = cli.run(argv)
                results.append({"argv": argv, "exit_code": result.exit_code, "ok": result.envelope["ok"],
                                "code": None if result.envelope["ok"] else result.envelope["error"]["code"]})
    expected = [True, True, True, False]
    if [item["ok"] for item in results] != expected or results[-1]["code"] != "E_UNSUPPORTED":
        raise StarterError("The generated project did not pass its own self-check.", "E_CONFIG",
                           "Report this starter defect; the output directory was kept for inspection.")
    return results


EXIT = {"E_USAGE": 2, "E_VALIDATION": 2, "E_CONFLICT": 6, "E_CONFIG": 4, "E_IO": 1}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise StarterError(message, "E_USAGE", "Run with --name <name> --profile file|session|device --output <new dir>.")


def main(argv=None) -> int:
    started = time.monotonic()
    parser = Parser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", choices=["file", "session", "device"], required=True)
    parser.add_argument("--description", help="One-line positioning for both READMEs and product metadata.")
    parser.add_argument("--repo", help="HTTPS repository URL; omit until a repository exists.")
    parser.add_argument("--author", help="Maintainer display name; no biography is invented.")
    try:
        args = parser.parse_args(argv)
        value = {"ok": True, "schema_version": "1.0", "data": instantiate(args.name, args.output, args.profile,
                                                                       description=args.description, repo=args.repo, author=args.author)}
        code = 0
    except StarterError as exc:
        value = {"ok": False, "schema_version": "1.0",
                 "error": {"code": exc.code, "message": str(exc), "retryable": False, "details": {"next_action": exc.next_action}}}
        code = EXIT[exc.code]
    except (OSError, KeyError, ImportError) as exc:
        value = {"ok": False, "schema_version": "1.0",
                 "error": {"code": "E_IO", "message": f"The starter could not be created: {exc}", "retryable": False,
                           "details": {"next_action": "Check the source checkout and the output path."}}}
        code = 1
    value["meta"] = {"duration_ms": round((time.monotonic() - started) * 1000, 3)}
    sys.stdout.buffer.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
