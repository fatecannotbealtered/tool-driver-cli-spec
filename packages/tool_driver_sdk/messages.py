"""Explicit factories for messages: no native state or authorization is inferred."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Outcome, Phase
from .validation import ContractError, ContractValidator, clone_json, json_bytes, parse_json


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    exit_code: int
    description: str


class ErrorCatalog:
    def __init__(self, entries):
        self._codes = {}
        for entry in entries:
            spec = entry if isinstance(entry, ErrorSpec) else ErrorSpec(**entry)
            if not isinstance(spec.code, str) or not re.fullmatch(r"E_[A-Z0-9_]+", spec.code) or spec.code in self._codes:
                raise ContractError("error codes must be valid and unique")
            if type(spec.exit_code) is not int or not 1 <= spec.exit_code <= 255 or not isinstance(spec.description, str) or not spec.description:
                raise ContractError("error exit mappings and descriptions must be explicit")
            self._codes[spec.code] = spec
        if not self._codes:
            raise ContractError("an error catalog is required")

    @classmethod
    def from_reference(cls, reference):
        return cls(reference["error_codes"])

    def exit_for(self, code: str) -> int:
        if code not in self._codes:
            raise ContractError("error code is not declared in the catalog")
        return self._codes[code].exit_code


@dataclass(frozen=True)
class CommandResult:
    """Canonical bytes are authoritative, so later dictionary mutations cannot alter output."""
    _payload: bytes
    exit_code: int

    def __post_init__(self):
        if not isinstance(self._payload, bytes) or type(self.exit_code) is not int or not 0 <= self.exit_code <= 255:
            raise ContractError("result bytes and process status must be explicit")

    @property
    def envelope(self):
        return parse_json(self._payload)

    def to_bytes(self) -> bytes:
        return self._payload

    def write_to(self, stream) -> None:
        stream.write(self._payload)


@dataclass(frozen=True)
class HelpResult:
    text: str
    exit_code: int = 0

    def to_bytes(self):
        return self.text.encode("utf-8")

    def write_to(self, stream):
        stream.write(self.to_bytes())


def _envelope(validator, phase, request_id, duration_ms):
    if not isinstance(request_id, str) or not request_id:
        raise ContractError("a known request ID must be supplied")
    return {"schema_version": validator.schema_version, "phase": Phase(phase).value,
            "request_id": request_id, "meta": {"duration_ms": duration_ms}}


def success(validator: ContractValidator, *, phase, request_id, data, duration_ms=0) -> CommandResult:
    value = _envelope(validator, phase, request_id, duration_ms)
    value.update(ok=True, data=clone_json(data))
    checked = validator.validate("response", value)
    return CommandResult(json_bytes(checked), 0)


def failure(validator: ContractValidator, *, phase, request_id, catalog: ErrorCatalog,
            code, message, retryable, details, data=None, duration_ms=0) -> CommandResult:
    if not isinstance(retryable, bool):
        raise ContractError("retryability must be explicitly supplied from the operation context")
    value = _envelope(validator, phase, request_id, duration_ms)
    value.update(ok=False, error={"code": code, "message": message, "retryable": retryable, "details": clone_json(details)})
    if data is not None:
        value["data"] = clone_json(data)
    checked = validator.validate("response", value)
    return CommandResult(json_bytes(checked), catalog.exit_for(code))


def make_receipt(validator: ContractValidator, *, operation_id, target, authorization_scope_id,
                 effects, snapshot_before, snapshot_after, outcome, changed_items, artifacts, recovery,
                 authorization_unavailable_reason=None, extensions=None) -> dict:
    value = {"operation_id": operation_id, "target": target, "authorization_scope_id": authorization_scope_id,
             "effects": effects, "snapshot_before": snapshot_before, "snapshot_after": snapshot_after,
             "outcome": outcome.to_dict() if isinstance(outcome, Outcome) else outcome,
             "changed_items": changed_items, "artifacts": artifacts, "recovery": recovery}
    if authorization_unavailable_reason is not None:
        value["authorization_unavailable_reason"] = authorization_unavailable_reason
    if extensions is not None:
        value["extensions"] = extensions
    return validator.validate("receipt", value)


def validate_result(validator, result, catalog, invocation=None):
    if not isinstance(result, CommandResult):
        raise ContractError("an explicit CommandResult is required")
    value = validator.validate("response", result.envelope)
    expected = 0 if value["ok"] else catalog.exit_for(value["error"]["code"])
    if result.exit_code != expected:
        raise ContractError("exit status differs from the declared message/error catalog")
    if invocation and (value["request_id"] != invocation.request_id or value["phase"] != invocation.phase):
        raise ContractError("returned request ID or phase differs from the invocation")
    return result
