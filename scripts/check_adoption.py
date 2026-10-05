"""Check pinned public Schema copies against a supplied specification ZIP offline."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import hashlib
import os
import stat
import time
from pathlib import Path, PurePosixPath

from validate_contract import InputError, Parser, UsageError, emit, parse_json, validate_value
from verify_spec_bundle import IntegrityError, canonical_path, path_identity, read_regular_file, verify_bundle


def file_identity(value: os.stat_result) -> tuple:
    return value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns


def node_identity(value: os.stat_result) -> tuple:
    if stat.S_ISDIR(value.st_mode):
        return value.st_dev, value.st_ino, value.st_mode
    return file_identity(value)


def checked_stat(path: Path) -> os.stat_result:
    try:
        value = path.lstat()
    except FileNotFoundError as exc:
        raise InputError(f"managed path is missing: {path}") from exc
    if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise InputError(f"managed paths cannot traverse symbolic links or reparse points: {path}")
    return value


def managed_bytes(root: Path, relative: str, expected_size: int) -> bytes:
    relative = canonical_path(relative)
    root = Path(os.path.abspath(root))
    lineage = [*reversed(root.parents), root]
    candidate = root
    for part in PurePosixPath(relative).parts:
        candidate = candidate / part
        lineage.append(candidate)
    recorded = [(path, checked_stat(path)) for path in lineage]
    if any(not stat.S_ISDIR(value.st_mode) for _, value in recorded[:-1]):
        raise InputError("all managed path ancestors must be directories")
    target = recorded[-1][1]
    if not stat.S_ISREG(target.st_mode):
        raise InputError(f"managed copy must be a regular file: {relative}")
    if target.st_size != expected_size:
        raise IntegrityError(f"managed Schema copy has drifted in size: {relative}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(candidate, flags), "rb") as stream:
        if file_identity(os.fstat(stream.fileno())) != file_identity(target):
            raise InputError("managed file changed while opening it")
        for path, previous in recorded:
            if node_identity(checked_stat(path)) != node_identity(previous):
                raise InputError("managed path changed while opening it")
        content = stream.read(expected_size + 1)
        if file_identity(os.fstat(stream.fileno())) != file_identity(target):
            raise InputError("managed file changed while reading it")
        for path, previous in recorded:
            if node_identity(checked_stat(path)) != node_identity(previous):
                raise InputError("managed path changed while reading it")
    return content


def check_adoption(lock: dict, root: Path, bundle: Path) -> dict:
    errors = validate_value("adoption-lock", lock)
    if errors:
        raise InputError("invalid adoption lock: " + "; ".join(errors[:10]))
    if lock["source_kind"] != "bundle":
        raise InputError(f"this lock pins a {lock['source_kind'].replace('_', ' ')}, not a specification bundle; "
                         "check it with the project's own check (check_project.py)")
    paths = [canonical_path(item["path"]) for item in lock["files"]]
    identities = [path_identity(path) for path in paths]
    if len(identities) != len(set(identities)):
        raise InputError("adoption lock contains duplicate or colliding managed paths")
    checked = verify_bundle(bundle, expected_sha256=lock["package_sha256"])
    manifest = checked.manifest
    if manifest["spec_version"] != lock["spec_version"] or manifest["source_commit"] != lock["source_commit"]:
        raise IntegrityError("lock version or source commit differs from the verified bundle")
    base_lock = checked.files.get("base/base-lock.json")
    if base_lock is None:
        raise IntegrityError("the verified bundle carries no base lock")
    base = parse_json(base_lock)
    if (base["spec"], base["tag"], base["commit"]) != (lock["base"]["spec"], lock["base"]["tag"], lock["base"]["commit"]):
        raise IntegrityError("lock base pin differs from the base the verified bundle was built on")
    sources = {component["path"]: component for component in manifest["components"]}
    results = []
    for item in lock["files"]:
        source = canonical_path(item["source_path"])
        component = sources.get(source)
        if component is None or component["role"] not in {"schema", "contract", "base", "documentation"}:
            raise InputError(f"public source is unknown or not a public contract component: {source}")
        original = checked.files[source]
        source_hash = hashlib.sha256(original).hexdigest()
        if source_hash != item["sha256"]:
            raise IntegrityError(f"lock hash differs from verified bundle content: {source}")
        copied = managed_bytes(root, item["path"], len(original))
        if copied != original:
            raise IntegrityError(f"managed copy has drifted: {item['path']}")
        results.append({"path": item["path"], "source_path": source, "sha256": source_hash})
    return {
        "scope": "offline_pinned_public_copies", "passed": True,
        "spec_version": lock["spec_version"], "schema_version": lock["schema_version"],
        "base": {"spec": base["spec"], "tag": base["tag"], "commit": base["commit"]},
        "source_commit": lock["source_commit"], "package_sha256": checked.sha256,
        "checked_files": results, "origin_authenticated": False,
        "limitations": ["The lock is assumed to come from a controlled source; this check does not authenticate its author or the publisher.", "Only the listed copies at the checked state are covered; no client CLI or application was executed."],
    }


def main(argv: list[str] | None = None) -> int:
    started = time.monotonic()
    parser = Parser(description=__doc__)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    try:
        args = parser.parse_args(argv)
        lock = parse_json(read_regular_file(args.lock, 1024 * 1024))
        return emit(True, started, data=check_adoption(lock, args.root, args.bundle))
    except IntegrityError as exc:
        return emit(False, started, code="E_INTEGRITY", message=str(exc),
                    details={"next_action": "do not use this package or copy; obtain it again from the trusted release"})
    except UsageError as exc:
        return emit(False, started, code="E_USAGE", message=str(exc), details={"problem": "invalid_value"})
    except (InputError, ValueError, KeyError, TypeError, RecursionError) as exc:
        return emit(False, started, code="E_VALIDATION", message=str(exc), details={"problem": "invalid_value"})
    except OSError as exc:
        return emit(False, started, code="E_IO", message=str(exc),
                    details={"next_action": "check that the named files exist and are readable"})


if __name__ == "__main__":
    sys.exit(main())
