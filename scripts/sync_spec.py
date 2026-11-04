#!/usr/bin/env python3
"""Copy the pinned copies of this specification release into a tool project: sync_spec.

    python scripts/sync_spec.py <project>

It runs from an unpacked specification release (or a checkout of this repository) and
replaces, as a whole, everything a tool pins (DREPO-030 to DREPO-034): the five
specifications in ``.agent/`` with ``.agent/SPEC_VERSION``, ``contract/driver-contract.json``,
the driver runtime in ``<pkg>/_driver/`` with its ``MANIFEST.json``, and the licenses in
``licenses/``. Files of an earlier release that this one no longer has are removed.

Afterwards run ``python scripts/spec.py generate`` and ``python scripts/spec.py check`` in
the project: the fixed text and the generated content follow the new release.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_project import bundle_version, pinned_files, runtime_manifest  # noqa: E402


def package_dir(project: Path) -> str:
    """``<pkg>``: the command name with ``-`` replaced by ``_`` (DREPO-053)."""
    try:
        bins = json.loads((project / "package.json").read_text(encoding="utf-8")).get("bin")
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot read {project / 'package.json'}: {exc}") from None
    if not isinstance(bins, dict) or len(bins) != 1:
        raise SystemExit("package.json must name exactly one command in `bin`")
    return next(iter(bins)).replace("-", "_")


def sync(project: Path) -> list[str]:
    pkg = package_dir(project)
    release = bundle_version()
    wanted = {dest: source for source, dest in pinned_files(pkg)}
    keep = set(wanted) | {".agent/SPEC_VERSION", f"{pkg}/_driver/MANIFEST.json"}
    changed = []
    for folder in (".agent", "licenses", f"{pkg}/_driver"):
        base = project / folder
        for cache in list(base.rglob("__pycache__")) if base.is_dir() else []:
            shutil.rmtree(cache, ignore_errors=True)
        for path in sorted(base.rglob("*"), reverse=True) if base.is_dir() else []:
            rel = path.relative_to(project).as_posix()
            if path.is_dir():
                if not any(path.iterdir()):
                    path.rmdir()
            elif rel not in keep:
                path.unlink()
                changed.append(f"removed {rel}")
    for dest, source in wanted.items():
        path = project / dest
        data = source.read_bytes().replace(b"\r\n", b"\n")
        if not path.is_file() or path.read_bytes() != data:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            changed.append(f"wrote {dest}")
    extras = {".agent/SPEC_VERSION": release + "\n",
              f"{pkg}/_driver/MANIFEST.json": json.dumps(runtime_manifest(release), indent=2, sort_keys=True) + "\n"}
    for dest, text in extras.items():
        path = project / dest
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            changed.append(f"wrote {dest}")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", type=Path)
    args = parser.parse_args(argv)
    project = args.project.resolve()
    changed = sync(project)
    for line in changed:
        print(line)
    print(f"Pinned tool-driver-cli-spec {bundle_version()}: {len(changed)} change(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
