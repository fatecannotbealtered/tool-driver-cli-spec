"""Offline, read-only verification of the pinned SDK and public specification copies."""
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cli import guard_vendor


def main():
    try:
        lock = guard_vendor()
        value = {"ok": True, "scope": "starter_pinned_vendor_bytes_only", "spec_version": lock["spec_version"],
                 "source_commit": lock["source"]["source_commit"], "source_dirty": lock["source"]["source_dirty"],
                 "checked_files": len(lock["files"]), "origin_authenticated": False,
                 "limitations": ["The local lock must come from a trusted caller. This guard does not authenticate a publisher or validate a native application."]}
    except (OSError, ValueError, KeyError, TypeError) as error:
        value = {"ok": False, "error": str(error), "scope": "starter_pinned_vendor_bytes_only"}
    print(json.dumps(value, ensure_ascii=False))
    return 0 if value["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
