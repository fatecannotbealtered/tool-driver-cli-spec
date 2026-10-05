"""Build a no-clobber specification ZIP from a clean, validated checkout."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from jsonschema.exceptions import ValidationError

from check_spec import ROOT, main as check_main, semantic_errors, validators
from bundle_layout import required_payload

HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True, creationflags=HIDDEN).strip()


def git_bytes(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], creationflags=HIDDEN)


def committed_inputs(source_commit: str) -> dict[str, bytes]:
    required = {"README.md", "AGENTS.md", "VERSION", "STATUS", "CHANGELOG.md", "requirements-dev.txt", "requirements-workflow.txt"}
    suffixes = {"docs": {".md"}, "schemas": {".json"}, "examples": {".json", ".md", ".py"}, "scripts": {".py"},
                "tests": {".py", ".json", ".svg"}, "packages": {".py", ".json", ".md"},
                "starter": {".py", ".json", ".md", ".toml", ".yml", ".txt", ""}, "base": {".md", ".json"}, "contract": {".json"}}
    inputs = {}
    for record in git_bytes("ls-tree", "-r", "-z", "--full-tree", source_commit).split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        relative = raw_path.decode("utf-8")
        path = Path(relative)
        if relative not in required and not (len(path.parts) > 1 and path.suffix in suffixes.get(path.parts[0], set())):
            continue
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError(f"only regular committed files are specification components: {relative}")
        inputs[relative] = git_bytes("cat-file", "blob", object_id)
    missing = required_payload() - inputs.keys()
    if missing:
        raise ValueError(f"missing committed specification files: {sorted(missing)}")
    return inputs


def publish_local(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"refusing to replace different output: {path}")
        return
    with path.open("xb") as stream:
        stream.write(data)


def build(output: Path) -> dict:
    if git("status", "--porcelain"):
        raise ValueError("commit the intended draft first; release source must be clean")
    source_commit = git("rev-parse", "HEAD")
    inputs = committed_inputs(source_commit)
    version = inputs["VERSION"].decode("utf-8").strip()
    status = inputs["STATUS"].decode("utf-8").strip()
    components = []
    for relative, payload in sorted(inputs.items()):
        role = ("schema" if relative.startswith("schemas/") else "base" if relative.startswith("base/")
                else "contract" if relative.startswith("contract/")
                else "example" if relative.startswith(("examples/", "starter/"))
                else "validator" if relative.startswith(("packages/", "scripts/", "tests/"))
                else "dependency_manifest" if relative in {"requirements-dev.txt", "requirements-workflow.txt"} else "documentation")
        components.append({"name": relative, "version": version, "path": relative, "sha256": hashlib.sha256(payload).hexdigest(), "role": role})
    base_tag = json.loads(inputs["base/base-lock.json"].decode("utf-8"))["tag"]
    manifest = {
        "artifact_kind": "specification", "name": "tool-driver-cli-spec", "version": version,
        "spec_version": version, "base": {"spec": "ai-native-cli-spec", "version": base_tag},
        "status": status, "source_commit": source_commit, "source_dirty": False,
        "target": {"os": "any", "arch": "any"}, "components": components,
        "compatibility": {"application": [], "plugin": [], "protocol": [{"identity": "tool-driver-cli-schema", "version_range": "2.0", "validation": "verified", "evidence_refs": ["scripts/check_spec.py"]}], "skill": []},
        "external_requirements": ["Python 3.11+ and requirements-dev.txt run local specification checks; requirements-workflow.txt provides optional audit, lint and signing tools."],
        "limitations": ["A stable specification does not certify a particular application or device product.", "No GitHub Release or SkillHub upload is performed by this builder."],
    }
    validators()["release-manifest.schema.json"].validate(manifest)
    errors = semantic_errors("release-manifest", manifest)
    if errors:
        raise ValueError("; ".join(errors))
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    inputs["manifest.json"] = manifest_bytes
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for relative, payload in sorted(inputs.items()):
            entry = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_STORED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, payload)
    archive_bytes = buffer.getvalue()
    checksum = hashlib.sha256(archive_bytes).hexdigest()
    archive_name = f"tool-driver-cli-spec-{version}.zip"
    outputs = {
        output / archive_name: archive_bytes,
        output / f"tool-driver-cli-spec-{version}.manifest.json": manifest_bytes,
        output / f"tool-driver-cli-spec-{version}.sha256": f"{checksum}  {archive_name}\n".encode("ascii"),
    }
    # Refuse every conflicting output before creating any file.
    for path, payload in outputs.items():
        if path.exists() and path.read_bytes() != payload:
            raise ValueError(f"refusing to replace different output: {path}")
    output.mkdir(parents=True, exist_ok=True)
    for path, payload in outputs.items():
        publish_local(path, payload)
    return {"artifact_kind": "specification", "version": version, "source_commit": source_commit, "sha256": checksum, "components": len(components), "files": [str(p) for p in outputs], "published": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    with contextlib.redirect_stdout(io.StringIO()) as check_output:
        check_status = check_main()
    if check_status:
        print(check_output.getvalue().strip())
        return check_status
    try:
        print(json.dumps({"ok": True, "schema_version": "1.0", "data": build(args.output.resolve()), "meta": {"duration_ms": 0}},
                         ensure_ascii=False))
        return 0
    except (OSError, ValueError, ValidationError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "schema_version": "1.0", "meta": {"duration_ms": 0},
                          "error": {"code": "E_VALIDATION", "message": str(exc), "retryable": False,
                                    "details": {"next_action": "Commit the intended changes and fix what the message names, then build again."}}},
                         ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
