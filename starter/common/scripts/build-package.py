"""Build a candidate archive on the target OS. The adapter and smoke must be implemented by the product."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = "{{NAME}}"
PACKAGE = "{{PACKAGE}}"
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    system = {"Windows": "windows", "Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    arch = {"AMD64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine())
    if not system or not arch:
        raise SystemExit("Unsupported build OS/architecture; declare and test it before adding a package.")
    version = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))["product_version"]
    lock = json.loads((ROOT / ".agent/driver/starter-lock.json").read_text(encoding="utf-8"))
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True,
                            creationflags=HIDDEN).stdout.strip()
    expected = os.environ.get("GITHUB_SHA")
    if expected and expected != commit:
        raise SystemExit("GITHUB_SHA does not match the checked-out source commit.")
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True,
                           creationflags=HIDDEN).stdout.strip()
    if dirty:
        raise SystemExit("Build from a clean committed source tree; uncommitted or untracked files were found.")
    environment = json.loads((ROOT / "release-environment.json").read_text(encoding="utf-8"))
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    suffix = ".zip" if system == "windows" else ".tar.gz"
    archive = dist / f"{NAME}-{version}-{system}-{arch}{suffix}"
    if archive.exists():
        raise SystemExit(f"Candidate already exists; do not overwrite it: {archive}")
    with tempfile.TemporaryDirectory(prefix="driver-package-") as temp:
        temp_path = Path(temp)
        args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--name", NAME,
                "--distpath", str(temp_path / "out"), "--workpath", str(temp_path / "build"),
                "--specpath", str(temp_path), "--paths", str(ROOT), "--paths", str(ROOT / ".agent/vendor/sdk"),
                "--add-data", ".agent/driver:.agent/driver", "--add-data", f"{PACKAGE}/generated:{PACKAGE}/generated",
                "--hidden-import", f"{PACKAGE}.cli", "--hidden-import", f"{PACKAGE}.adapter",
                "--collect-all", "jsonschema", "scripts/bundle-entry.py"]
        subprocess.run(args, cwd=ROOT, check=True, creationflags=HIDDEN)
        stage = temp_path / "stage"
        stage.mkdir()
        binary_name = NAME + (".exe" if system == "windows" else "")
        shutil.copy2(temp_path / "out" / binary_name, stage / binary_name)
        shutil.copytree(ROOT / "skills", stage / "skills")
        # Keep licensing material readable outside the frozen executable.
        shutil.copytree(ROOT / "LICENSES", stage / "LICENSES")
        shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", stage / "THIRD_PARTY_NOTICES.md")
        for source, name in ((ROOT / ".agent/driver/LICENSE", "driver-spec-LICENSE"),
                             (ROOT / ".agent/driver/THIRD_PARTY_NOTICES.md", "driver-spec-NOTICES.md"),
                             (ROOT / ".agent/vendor/sdk/tool_driver_sdk/LICENSE", "driver-sdk-LICENSE")):
            shutil.copy2(source, stage / "LICENSES" / name)
        if (ROOT / "LICENSE").is_file():
            shutil.copy2(ROOT / "LICENSE", stage / "LICENSE")
        components = [{"name": NAME, "version": version, "path": binary_name, "sha256": sha(stage / binary_name), "role": "cli"}]
        for item in sorted((stage / "skills").rglob("*")):
            if item.is_file():
                components.append({"name": item.name, "version": version, "path": item.relative_to(stage).as_posix(),
                                   "sha256": sha(item), "role": "skill"})
        for item in sorted(stage.rglob("*")):
            if item.is_file() and item.name != binary_name and "skills" not in item.relative_to(stage).parts:
                components.append({"name": item.name, "version": version, "path": item.relative_to(stage).as_posix(),
                                   "sha256": sha(item), "role": "documentation"})
        manifest = {"artifact_kind": "cli_product", "name": NAME, "version": version, "spec_version": lock["spec_version"],
                    "base": {"spec": lock["base"]["spec"], "version": lock["base"]["tag"]}, "status": "draft",
                    "source_commit": commit, "source_dirty": False,
                    "target": {"os": system, "arch": arch}, "components": components,
                    "compatibility": environment["compatibility"], "external_requirements": environment["external_requirements"],
                    "limitations": environment["limitations"]}
        sys.path.insert(0, str(ROOT / ".agent/driver/scripts"))
        from validate_contract import validate_value
        problems = validate_value("release-manifest", manifest)
        if problems:
            raise SystemExit("Invalid release manifest: " + "; ".join(problems[:5]))
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if system == "windows":
            with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as bundle:
                for item in sorted(stage.rglob("*")):
                    if item.is_file():
                        bundle.write(item, item.relative_to(stage).as_posix())
        else:
            with tarfile.open(archive, "x:gz") as bundle:
                for item in sorted(stage.iterdir()):
                    bundle.add(item, arcname=item.name)
    print(f"Candidate archive: {archive.name}; sha256={sha(archive)}")


if __name__ == "__main__":
    main()
