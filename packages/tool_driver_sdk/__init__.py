"""Thin tool-driver runtime; callers still implement native state and authorization."""

from .messages import CommandResult, ErrorCatalog, ErrorSpec, HelpResult, failure, make_receipt, success, validate_result
from .models import Adapter, Change, Execution, Invocation, Outcome, Persistence, Phase, VerificationStatus
from .runtime import EndpointDispatcher, StubAdapter, serve_cli
from .validation import ContractError, ContractValidationError, ContractValidator, clone_json, json_bytes, parse_json

__all__ = [
    "Adapter", "Change", "CommandResult", "ContractError", "ContractValidationError", "ContractValidator",
    "EndpointDispatcher", "ErrorCatalog", "ErrorSpec", "Execution", "HelpResult", "Invocation", "Outcome",
    "Persistence", "Phase", "StubAdapter", "VerificationStatus", "clone_json", "failure", "json_bytes",
    "make_receipt", "parse_json", "serve_cli", "success", "validate_result",
]
