"""Offline, read-only check of the pinned specification and SDK copies; writes one base envelope."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import time
from pathlib import Path
from sync_version import version_drift

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
SPEC = ROOT / ".agent" / "driver"
LOCK = SPEC / "starter-lock.json"
MANAGED = (ROOT / ".agent" / "driver", ROOT / ".agent" / "vendor")
REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def regular(path: Path) -> bytes:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & REPARSE_POINT or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"managed path is not a regular file: {path.relative_to(ROOT).as_posix()}")
    return path.read_bytes()


def lock_problems(lock) -> list[str]:
    """The lock is an adoption lock: validate it with the pinned schema and checker before trusting its hashes."""
    sys.path.insert(0, str(SPEC / "scripts"))
    try:
        from validate_contract import validate_value
    finally:
        sys.path.pop(0)
    return validate_value("adoption-lock", lock)


def check() -> dict:
    lock = json.loads(regular(LOCK).decode("utf-8"))
    problems = lock_problems(lock)
    if problems:
        raise ValueError("starter-lock.json does not satisfy the adoption-lock schema: " + "; ".join(problems[:5]))
    expected = {}
    for item in lock["files"]:
        relative = item["path"]
        if not relative.startswith((".agent/driver/", ".agent/vendor/")) or ".." in relative.split("/") or "\\" in relative:
            raise ValueError(f"lock entry escapes the managed directories: {relative}")
        expected[relative] = item["sha256"]
    actual = set()
    for base in MANAGED:
        for directory, subdirectories, files in os.walk(base, followlinks=False):
            subdirectories[:] = [name for name in subdirectories if name != "__pycache__"]
            for name in files:
                path = Path(directory) / name
                relative = path.relative_to(ROOT).as_posix()
                if relative == ".agent/driver/starter-lock.json" or name.endswith(".pyc"):
                    continue
                actual.add(relative)
    missing, extra = sorted(set(expected) - actual), sorted(actual - set(expected))
    drifted = sorted(relative for relative in set(expected) & actual
                     if hashlib.sha256(regular(ROOT / relative)).hexdigest() != expected[relative])
    source = {"kind": lock["source_kind"], "commit": lock["source_commit"], "dirty": lock["source_dirty"]}
    return {"spec_version": lock["spec_version"], "base": lock["base"], "source": source, "checked_files": len(expected),
            "missing": missing, "unexpected": extra, "drifted": drifted, "version_drift": version_drift(ROOT)}


def main() -> int:
    started = time.monotonic()
    meta = {"duration_ms": 0}
    try:
        result = check()
        failed = result["missing"] or result["unexpected"] or result["drifted"] or result["version_drift"]
        meta["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
        if failed:
            value = {"ok": False, "schema_version": "1.0", "meta": meta,
                     "error": {"code": "E_INTEGRITY", "message": "A pinned copy or derived product version differs from its source.",
                               "retryable": False, "details": {**result, "next_action": "Restore pinned copies; run sync_version.py and regenerate contracts for product version drift."}}}
            code = 1
        else:
            value = {"ok": True, "schema_version": "1.0", "meta": meta,
                     "data": {**result, "scope": "pinned_copies_only", "origin_authenticated": False,
                              "limitations": ["The lock must come from a trusted source; this check does not authenticate the publisher."]}}
            code = 0
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        value = {"ok": False, "schema_version": "1.0", "meta": meta,
                 "error": {"code": "E_CONFIG", "message": f"The pinned copies cannot be checked: {exc}", "retryable": False,
                           "details": {"next_action": "Restore .agent/driver/starter-lock.json and the pinned copies."}}}
        code = 4
    sys.stdout.buffer.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
