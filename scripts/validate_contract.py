"""Validate one JSON contract offline; never execute commands contained in it."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable

from check_spec import ROOT, load, semantic_errors, validators
from contract_io import InputError, parse_json, read_regular_file


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        if message.startswith("unrecognized arguments:"):
            message = "unsupported argument; use --help to inspect accepted options"
        raise InputError(message)


def read_input(path: str, limit: int) -> bytes:
    if path == "-":
        payload = sys.stdin.buffer.read(limit + 1)
    else:
        return read_regular_file(Path(path), limit)
    if len(payload) > limit:
        raise InputError(f"input exceeds the declared {limit}-byte limit")
    return payload


def validate_value(kind: str, value) -> list[str]:
    checked = validators()
    name = kind if kind.endswith(".schema.json") else kind + ".schema.json"
    if name not in checked:
        raise InputError("unknown schema; use a schema basename from the specification")
    if name == "common.schema.json":
        raise InputError("common contains shared definitions; select an instance contract")
    if load(ROOT / "schemas" / name).get("x-development-only"):
        raise InputError("development declarations are checked by their development tool, not as a public instance contract")
    errors = [f"constraint {error.validator} failed at depth {len(error.absolute_path)}" for error in checked[name].iter_errors(value)]
    if not errors:
        errors.extend(semantic_errors(name.removesuffix(".schema.json"), value))
    return errors


def emit(ok: bool, started: float, data: dict | None = None, code: str | None = None, message: str | None = None, details: dict | None = None) -> None:
    result = {
        "ok": ok, "schema_version": "1.0", "request_id": str(uuid.uuid4()), "phase": "verify",
        "meta": {"duration_ms": round((time.monotonic() - started) * 1000, 3)},
    }
    if data is not None:
        result["data"] = data
    if not ok:
        result["error"] = {"code": code or "E_VALIDATION", "message": message or "contract validation failed", "retryable": False, "details": details or {}}
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    started = time.monotonic()
    parser = Parser(description=__doc__)
    parser.add_argument("--schema", required=True, help="Schema basename, such as response or reference.")
    parser.add_argument("--input", required=True, help="JSON file, or - for explicit stdin input.")
    parser.add_argument("--max-bytes", type=int, default=8 * 1024 * 1024)
    try:
        args = parser.parse_args(argv)
        if args.max_bytes <= 0:
            raise InputError("--max-bytes must be positive")
        errors = validate_value(args.schema, parse_json(read_input(args.input, args.max_bytes)))
        if errors:
            emit(False, started, code="E_VALIDATION", message="input does not satisfy the declared contract", details={"schema": args.schema, "errors": errors[:30], "error_count": len(errors)})
            return 2
        emit(True, started, data={"schema": args.schema, "scope": "structure_and_static_semantics", "passed": True, "limitations": ["Does not verify real application state, argv parsing, authorization provenance or package origin."]})
        return 0
    except (InputError, ValueError, KeyError, TypeError, SchemaError, Unresolvable, RecursionError) as exc:
        emit(False, started, code="E_VALIDATION", message=str(exc))
        return 2
    except OSError as exc:
        emit(False, started, code="E_IO", message=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
