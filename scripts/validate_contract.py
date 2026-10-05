"""Validate one JSON document against a public driver contract offline; never execute commands in it."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable

from check_spec import ROOT, load, semantic_errors, validators
from contract_io import InputError, parse_json, read_regular_file

# Base exit codes (ai-native-cli-spec core table) for the codes these tools emit.
EXIT = {"E_USAGE": 2, "E_VALIDATION": 2, "E_INTEGRITY": 1, "E_IO": 1}


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        if message.startswith("unrecognized arguments:"):
            message = "unsupported argument; use --help to inspect accepted options"
        raise UsageError(message)


class UsageError(InputError):
    pass


def read_input(path: str, limit: int) -> bytes:
    if path == "-":
        payload = sys.stdin.buffer.read(limit + 1)
    else:
        return read_regular_file(Path(path), limit)
    if len(payload) > limit:
        raise InputError(f"input exceeds the declared {limit}-byte limit")
    return payload


def instance_schemas() -> list[str]:
    names = []
    for path in sorted((ROOT / "schemas").glob("*.schema.json")):
        name = path.name.removesuffix(".schema.json")
        if name != "common" and not load(path).get("x-development-only"):
            names.append(name)
    return names


def validate_value(kind: str, value) -> list[str]:
    checked = validators()
    name = kind.removesuffix(".schema.json")
    if name == "common":
        raise UsageError("common contains shared definitions; select an instance contract")
    if name + ".schema.json" not in checked:
        raise UsageError("unknown schema; use one of: " + ", ".join(instance_schemas()))
    if load(ROOT / "schemas" / (name + ".schema.json")).get("x-development-only"):
        raise UsageError("development declarations are checked by their development tool, not as a public instance contract")
    errors = [f"{'/'.join(map(str, error.absolute_path)) or '(root)'}: constraint {error.validator} failed"
              for error in checked[name + ".schema.json"].iter_errors(value)]
    if not errors:
        errors.extend(semantic_errors(name, value))
    return errors


def emit(ok: bool, started: float, data: dict | None = None, code: str | None = None, message: str | None = None,
         details: dict | None = None) -> int:
    """Write one base ai-native envelope and return its exit code."""
    meta = {"duration_ms": round((time.monotonic() - started) * 1000, 3)}
    if ok:
        result = {"ok": True, "schema_version": "1.0", "data": data or {}, "meta": meta}
        status = 0
    else:
        code = code or "E_VALIDATION"
        body = {"next_action": "fix the input named in the message and run the check again"}
        body.update(details or {})
        result = {"ok": False, "schema_version": "1.0", "meta": meta,
                  "error": {"code": code, "message": message or "contract validation failed", "retryable": False, "details": body}}
        status = EXIT[code]
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
    return status


def main(argv: list[str] | None = None) -> int:
    started = time.monotonic()
    parser = Parser(description=__doc__)
    parser.add_argument("--schema", required=True, help="Schema basename, such as response, reference, context or receipt.")
    parser.add_argument("--input", required=True, help="JSON file, or - for explicit stdin input.")
    parser.add_argument("--max-bytes", type=int, default=8 * 1024 * 1024)
    try:
        args = parser.parse_args(argv)
        if args.max_bytes <= 0:
            raise UsageError("--max-bytes must be positive")
        errors = validate_value(args.schema, parse_json(read_input(args.input, args.max_bytes)))
        if errors:
            return emit(False, started, code="E_VALIDATION", message="input does not satisfy the declared contract",
                        details={"schema": args.schema, "errors": errors[:30], "error_count": len(errors),
                                 "next_action": "fix the listed fields; the messages name constraints, not your values"})
        return emit(True, started, data={"schema": args.schema, "scope": "structure_and_static_semantics", "passed": True,
                                         "limitations": ["Does not verify real application state, argv parsing, authorization provenance or package origin."]})
    except UsageError as exc:
        return emit(False, started, code="E_USAGE", message=str(exc), details={"problem": "invalid_value"})
    except (InputError, ValueError, KeyError, TypeError, SchemaError, Unresolvable, RecursionError) as exc:
        return emit(False, started, code="E_VALIDATION", message=str(exc), details={"problem": "invalid_value"})
    except OSError as exc:
        return emit(False, started, code="E_IO", message=str(exc), details={"next_action": "check that the input file exists and is readable"})


if __name__ == "__main__":
    sys.exit(main())
