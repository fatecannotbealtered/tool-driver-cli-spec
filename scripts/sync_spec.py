#!/usr/bin/env python3
"""Copy the pinned copies of this specification release into a tool project: sync_spec.

    python scripts/sync_spec.py <project> [--since <version>]

It runs from an unpacked specification release (or a checkout of this repository) and
replaces, as a whole, everything a tool pins (DREPO-030 to DREPO-035): the five
specifications in ``.agent/`` with ``.agent/SPEC_VERSION``, ``contract/driver-contract.json``,
the driver runtime in ``<pkg>/_driver/`` with its ``MANIFEST.json``, the licenses in
``licenses/``, and the scripts in ``scripts/`` that are the same in every tool. Files of an
earlier release that this one no longer has are removed from ``.agent/``, ``licenses/`` and
``<pkg>/_driver/``.

It also lists the other template files that changed since the release the project pinned
before, such as ``docs/E2E.md``: compare the project's copies with them and carry over what
applies. ``--since`` names another release to compare with, so the list can be had again after
the pin moved. That release comes from the download cache of ``scripts/spec.py``; when it is
missing there, it is downloaded first, checked against ``.agent/SPEC_SHA256`` when that pins it,
else against the SHA-256 published with it.

Afterwards run ``python scripts/spec.py generate`` and ``python scripts/spec.py check`` in
the project: the fixed text and the generated content follow the new release.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_project import (BUNDLE, FIXED, JUNK, SHARED_REGION, bundle_version, digest, load_contract,  # noqa: E402
                           pinned_files, read, runtime_manifest, section_body, set_section)

NAME = "tool-driver-cli-spec"


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
    keep = set(wanted) | {".agent/SPEC_VERSION", ".agent/SPEC_SHA256", f"{pkg}/_driver/MANIFEST.json"}
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


def old_template(before: str | None) -> Path | None:
    """template/ of release ``before`` in the download cache of ``scripts/spec.py``."""
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / NAME / str(before) / f"{NAME}-{before}"
    return cache / "template" if before and (cache / "template").is_dir() else None


def download(version: str, pin: str | None) -> None:
    """Put a release into the download cache with the download of ``scripts/spec.py``."""
    loader = importlib.util.spec_from_file_location("spec_download", BUNDLE / "template" / "scripts" / "spec.py")
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    module.download(version, pin)


def fetch_old(project: Path, before: str | None, pinned: bool = True) -> str | None:
    """Download release ``before`` when it is missing from the download cache, before sync
    replaces the SHA-256 the project pinned with it; the reason when that fails. ``pinned``:
    ``before`` is the release the project pinned, so ``.agent/SPEC_SHA256`` checks it."""
    if not before or before == bundle_version() or old_template(before) is not None:
        return None
    pin = project / ".agent" / "SPEC_SHA256"
    try:
        download(before, (pin.read_text(encoding="utf-8").strip() or None) if pinned and pin.is_file() else None)
    except (SystemExit, Exception) as exc:  # the download only serves the listing, never the sync
        return str(exc) or type(exc).__name__
    return None if old_template(before) is not None else f"release {before} holds no template/"


def only_fixed_text(rel: str, old: str, new: str) -> bool:
    """The file differs only in text generate writes from the template: fixed sections and the
    text inside shared regions (DREPO-036). A region the new release adds still counts."""
    def blank(text: str) -> str:
        return SHARED_REGION.sub(lambda m: f"<!-- driver:{m.group(1)}:start --><!-- driver:{m.group(1)}:end -->", text)

    old, new = blank(old), blank(new)
    if old.replace("\r\n", "\n") == new.replace("\r\n", "\n"):
        return True
    english = rel[:-6] + ".md" if rel.endswith("_zh.md") else rel
    if english not in FIXED:
        return False
    project = load_contract()["project"]
    for name in FIXED[english]:
        heading = name if rel == english else project["sections_zh"][english][project["sections"][english].index(name)]
        body = section_body(new, heading)
        if body is not None and section_body(old, heading) is not None:
            old = set_section(old, heading, body)
    return old.replace("\r\n", "\n") == new.replace("\r\n", "\n")


def template_changes(project: Path, before: str | None) -> list[str] | None:
    """The template files, other than pinned copies and fixed text, that differ from release
    ``before``; None when that release is not in the download cache (see ``fetch_old``)."""
    if not before or before == bundle_version():
        return []
    old, new = old_template(before), BUNDLE / "template"
    if old is None:
        return None
    pinned = {source.resolve() for source, _ in pinned_files(package_dir(project))}
    changed = []
    for path in sorted(new.rglob("*")):
        rel = path.relative_to(new).as_posix()
        if not path.is_file() or path.resolve() in pinned or path.name in JUNK or "__pycache__" in path.parts:
            continue
        if not (old / rel).is_file():
            changed.append(rel)
        elif digest(old / rel) != digest(path) and not (path.suffix == ".md" and only_fixed_text(rel, read(old / rel), read(path))):
            changed.append(rel)
    return changed


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # the console code page may lack a character of the output
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", type=Path)
    parser.add_argument("--since", help="the release to list the template changes since; by default the one pinned before")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    pinned_before = project / ".agent" / "SPEC_VERSION"
    pinned = pinned_before.read_text(encoding="utf-8").strip() if pinned_before.is_file() else None
    before = args.since or pinned
    failed = fetch_old(project, before, pinned=before == pinned)
    changed = sync(project)
    for line in changed:
        print(line)
    print(f"Pinned tool-driver-cli-spec {bundle_version()}: {len(changed)} change(s).")
    template = template_changes(project, before)
    if template is None:
        print(f"Release {before} could not be downloaded ({failed}), so the template files that changed since then "
              "are not listed; compare the project's copies with template/ of this release.")
    elif template:
        print(f"The template changed these files since {before}. Compare each in {BUNDLE / 'template'} with the same file "
              f"in {old_template(before)} and carry over to the project's copy what applies:")
        for rel in template:
            print(f"  {rel}")
    elif before == bundle_version():
        print(f"The project pinned {before} already. To list the template files that changed since an earlier release, "
              f"run `python scripts/spec.py sync {before} --since <earlier version>`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
