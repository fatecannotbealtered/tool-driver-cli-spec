"""Schema validation against the contract's schemas, with every $ref resolved locally."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRACT = Path(__file__).resolve().parents[2] / "contract"
SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")
UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z$")


@lru_cache(maxsize=1)
def contract() -> dict[str, Any]:
    return json.loads((CONTRACT / "driver-contract.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _registry() -> tuple[Registry, dict[str, dict[str, Any]]]:
    schemas = {}
    registry = Registry()
    for path in sorted((CONTRACT / "schemas").glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas[path.name] = schema
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(schema["$id"], resource).with_resource(path.name, resource)
    return registry, schemas


def errors(instance: Any, schema: str, pointer: str = "") -> list[str]:
    """The validation errors of ``instance`` against a schema, or a part of it like ``/$defs/preview``."""
    registry, schemas = _registry()
    root = schemas[schema]
    target: dict[str, Any] = {"$ref": f"{root['$id']}#{pointer}"} if pointer else root
    validator = Draft202012Validator(target, registry=registry)
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:300]}" for e in validator.iter_errors(instance)]


def naming(value: Any, path: str = "$", data_map: bool = False) -> list[str]:
    """Keys that name fields are snake_case and times end in Z (DCLI-005). The keys of
    ``observed`` are target keys, values in their own right; an ``output_schema``, and the
    ``schema`` of a ``json`` flag, is a JSON Schema in its own vocabulary."""
    problems = []
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}"
            if not data_map and not SNAKE.match(str(key)):
                problems.append(f"{here}: the key is not snake_case")
            if isinstance(key, str) and key.endswith("_at") and item is not None and not (isinstance(item, str) and UTC.match(item)):
                problems.append(f"{here}: a time is UTC ending in Z")
            if key in ("output_schema", "schema") and isinstance(item, dict):
                continue  # a JSON Schema, written in its own vocabulary ($ref, additionalProperties ...)
            problems += naming(item, here, data_map=key in ("observed",) and not data_map)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            problems += naming(item, f"{path}[{i}]")
    return problems
