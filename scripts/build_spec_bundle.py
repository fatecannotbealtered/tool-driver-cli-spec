#!/usr/bin/env python3
"""Build the specification bundle, or print release notes.

Usage:
    python scripts/build_spec_bundle.py            # dist/tool-driver-cli-spec-<VERSION>.zip and .sha256
    python scripts/build_spec_bundle.py --notes    # the CHANGELOG section of VERSION, for the release
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "tool-driver-cli-spec"
TOP_FILES = ["README.md", "README_zh.md", "CHANGELOG.md", "LICENSE", "NOTICE.md", "VERSION"]
TREES = ["spec", "contract", "sdk", "conformance", "template", "scripts"]
SKIP = {"__pycache__"}
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def bundle_files() -> list[Path]:
    files = [ROOT / name for name in TOP_FILES]
    for tree in TREES:
        files.extend(p for p in (ROOT / tree).rglob("*")
                     if p.is_file() and not SKIP & set(p.relative_to(ROOT).parts) and p.suffix != ".pyc")
    missing = [p for p in files if not p.is_file()]
    if missing:
        raise SystemExit(f"missing files: {[p.relative_to(ROOT).as_posix() for p in missing]}")
    return sorted(files, key=lambda p: p.relative_to(ROOT).as_posix())


def build(out_dir: Path) -> tuple[Path, str]:
    ver = version()
    prefix = f"{NAME}-{ver}/"
    manifest = {"name": NAME, "version": ver, "files": {}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in bundle_files():
            data = path.read_bytes().replace(b"\r\n", b"\n")
            name = path.relative_to(ROOT).as_posix()
            manifest["files"][name] = hashlib.sha256(data).hexdigest()
            info = zipfile.ZipInfo(prefix + name, date_time=FIXED_TIME)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
        info = zipfile.ZipInfo(prefix + "MANIFEST.json", date_time=FIXED_TIME)
        info.external_attr = 0o644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{NAME}-{ver}.zip"
    zip_path.write_bytes(buffer.getvalue())
    digest = hashlib.sha256(buffer.getvalue()).hexdigest()
    (out_dir / f"{NAME}-{ver}.sha256").write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    return zip_path, digest


def notes(ver: str) -> str:
    """The CHANGELOG section for ver, without its heading."""
    lines = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith(f"## [{ver}]"):
            start = i + 1
        elif start is not None and line.startswith("## "):
            return "\n".join(lines[start:i]).strip() + "\n"
    if start is None:
        raise SystemExit(f"CHANGELOG.md has no section for {ver}")
    return "\n".join(lines[start:]).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--notes", action="store_true", help="print the release notes of VERSION and exit")
    parser.add_argument("--out", default=str(ROOT / "dist"), help="output directory (default: dist/)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.notes:
        sys.stdout.write(notes(version()))
        return 0
    path, digest = build(Path(args.out))
    print(f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}  sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
