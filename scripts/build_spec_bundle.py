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

from check_spec import ROOT, main as check_main, semantic_errors, validators


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


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
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    files = [ROOT / p for p in ["README.md", "AGENTS.md", "VERSION", "CHANGELOG.md", "requirements-dev.txt"]]
    for folder, pattern in [("docs", "*.md"), ("schemas", "*.json"), ("examples", "*.json"), ("examples", "*.md"), ("scripts", "*.py")]:
        files.extend((ROOT / folder).rglob(pattern))
    inputs = {}
    components = []
    for file in sorted(set(files)):
        if file.is_symlink():
            raise ValueError(f"symlinks are not specification components: {file}")
        relative = file.relative_to(ROOT).as_posix()
        payload = file.read_bytes()
        inputs[relative] = payload
        role = "schema" if relative.startswith("schemas/") else "example" if relative.startswith("examples/") else "validator" if relative.startswith("scripts/") else "dependency_manifest" if relative == "requirements-dev.txt" else "documentation"
        components.append({"name": relative, "version": version, "path": relative, "sha256": hashlib.sha256(payload).hexdigest(), "role": role})
    manifest = {
        "artifact_kind": "specification", "name": "tool-driver-cli-spec", "version": version,
        "spec_version": version, "status": "draft", "source_commit": source_commit, "source_dirty": False,
        "target": {"os": "any", "arch": "any"}, "components": components,
        "compatibility": {"application": [], "plugin": [], "protocol": [{"identity": "tool-driver-cli-schema", "version_range": "1.0", "validation": "verified", "evidence_refs": ["scripts/check_spec.py"]}], "skill": []},
        "external_requirements": ["Python 3.11+ and requirements-dev.txt are needed only to run local specification checks."],
        "limitations": ["Draft specification bundle; static example validation is not real application or device verification.", "No GitHub Release or SkillHub upload is performed by this builder."],
    }
    validators()["release-manifest.schema.json"].validate(manifest)
    errors = semantic_errors("release-manifest", manifest)
    if errors:
        raise ValueError("; ".join(errors))
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    inputs["manifest.json"] = manifest_bytes
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, payload in sorted(inputs.items()):
            entry = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
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
    return {"ok": True, "artifact_kind": "specification", "version": version, "source_commit": source_commit, "sha256": checksum, "components": len(components), "files": [str(p) for p in outputs], "published": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    with contextlib.redirect_stdout(io.StringIO()) as check_output:
        check_status = check_main()
    if check_status:
        print(check_output.getvalue().strip())
        return 1
    try:
        print(json.dumps(build(args.output.resolve()), ensure_ascii=False))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
