"""Native CLI entry: controlled local imports, pinned vendor guard, SDK dispatch."""
from pathlib import Path
import hashlib
import json
import os
import re
import stat
import sys
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent


def guard_vendor():
    lock = json.loads((ROOT / ".agent" / "starter-lock.json").read_text(encoding="utf-8"))
    if not isinstance(lock, dict) or not isinstance(lock.get("files"), list) or not lock["files"]:
        raise ValueError("A nonempty trusted vendor inventory is required.")
    expected = {}
    for item in lock["files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"].startswith(".agent/vendor/"):
            raise ValueError("Managed vendor inventory entries are invalid.")
        if not isinstance(item.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("Managed vendor inventory hashes are invalid.")
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts or "\\" in item["path"]:
            raise ValueError("Invalid managed vendor path.")
        if item["path"] in expected:
            raise ValueError("Duplicate managed vendor path.")
        expected[item["path"]] = item["sha256"]
        candidate = ROOT
        for part in relative.parts:
            candidate = candidate / part
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                raise ValueError("Managed vendor links are not accepted.")
        if not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Managed vendor content has drifted.")
    actual = set()
    for directory, subdirectories, filenames in os.walk(ROOT / ".agent" / "vendor", followlinks=False):
        for name in [*subdirectories, *filenames]:
            path = Path(directory) / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                raise ValueError("Managed vendor links are not accepted.")
            if name in filenames:
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError("Managed vendor objects must be regular files.")
                actual.add(path.relative_to(ROOT).as_posix())
    if actual != set(expected):
        raise ValueError("Managed vendor inventory has drifted.")
    required = {".agent/vendor/spec/schemas/response.schema.json", ".agent/vendor/spec/schemas/common.schema.json",
                ".agent/vendor/spec/scripts/check_spec.py", ".agent/vendor/sdk/tool_driver_sdk/__init__.py"}
    if not required <= set(expected):
        raise ValueError("The required vendor contract and runtime inventory is missing.")
    return lock


def main(argv=None):
    try:
        guard_vendor()
        sys.path[:0] = [str(ROOT / ".agent" / "vendor" / "sdk"),
                       str(ROOT / ".agent" / "vendor" / "spec" / "scripts"), str(ROOT)]
        from generate_product import build_contract
        from tool_driver_sdk import ContractValidator, ErrorCatalog, serve_cli
        from callbacks import adapter, context, doctor
        registry = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
        project = json.loads((ROOT / ".agent" / "project.json").read_text(encoding="utf-8"))
        vendor_root = ROOT / ".agent" / "vendor" / "spec"
        contract = build_contract(registry, public_root=vendor_root)
        validator = ContractValidator(vendor_root)
        catalog = ErrorCatalog.from_reference(contract["reference"])
        native_adapter = adapter(validator, catalog)
    except (OSError, ValueError, KeyError, ImportError, TypeError, SyntaxError) as error:
        # SDK cannot be loaded safely after a failed bootstrap. No adapter was invoked.
        result = {"ok": False, "schema_version": "1.0", "request_id": "bootstrap-" + uuid.uuid4().hex,
                  "phase": "observe", "error": {"code": "E_CONFIG", "message": "Starter bootstrap could not validate its local dependencies or declarations.",
                  "retryable": False, "details": {"dispatch_state": "not_started", "cause_type": type(error).__name__,
                  "next_action": "Check the trusted vendor lock and declared local dependencies."}},
                  "meta": {"duration_ms": 0}}
        try:
            sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
        except (OSError, ValueError):
            try:
                sys.stderr.write("Output channel failed; no complete result was delivered.\n")
            except (OSError, ValueError):
                pass
            return 1
        return 5
    # Dispatch and output delivery are beyond bootstrap. A lost reply cannot mean not_started.
    result = serve_cli(contract, validator, native_adapter,
                       sys.argv[1:] if argv is None else argv,
                       context_provider=lambda invocation: context(registry, project),
                       doctor_provider=lambda invocation: doctor(registry, project))
    try:
        result.write_to(sys.stdout.buffer)
    except (OSError, ValueError):
        # stdout may already contain a prefix. Do not append a second JSON or disclose its data.
        try:
            sys.stderr.write("Output channel failed; delivery is unconfirmed. Query any dispatched request before retrying.\n")
        except (OSError, ValueError):
            pass
        return 1
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
