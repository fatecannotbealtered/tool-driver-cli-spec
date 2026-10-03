"""Small protocol types; native facts and authorization remain caller supplied."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Protocol, runtime_checkable


class Phase(StrEnum):
    OBSERVE = "observe"
    PLAN = "plan"
    APPLY = "apply"
    SUBMIT = "submit"
    STATUS = "status"
    RESULT = "result"
    VERIFY = "verify"


class Execution(StrEnum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


class Change(StrEnum):
    NOT_APPLIED = "not_applied"
    APPLIED = "applied"
    PARTIAL = "partial"
    ROLLED_BACK = "rolled_back"
    UNKNOWN = "unknown"


class Persistence(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    UNCHANGED = "unchanged"
    UNSAVED = "unsaved"
    SAVED = "saved"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class VerificationStatus(StrEnum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Invocation:
    capability_id: str
    phase: Phase | str
    request_id: str
    payload: dict[str, Any]
    caller_known_request_id: bool = True

    def __post_init__(self):
        if not isinstance(self.capability_id, str) or not self.capability_id:
            raise ValueError("a capability ID is required")
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValueError("a request ID is required")
        if not isinstance(self.payload, dict) or not isinstance(self.caller_known_request_id, bool):
            raise ValueError("invocation payload and request identity provenance are invalid")
        object.__setattr__(self, "phase", Phase(self.phase))


@dataclass(frozen=True)
class Outcome:
    execution: Execution | str
    change: Change | str
    persistence: Persistence | str
    verification: dict[str, Any]

    def to_dict(self) -> dict:
        return {"execution": Execution(self.execution).value, "change": Change(self.change).value,
                "persistence": Persistence(self.persistence).value, "verification": self.verification}


@runtime_checkable
class Adapter(Protocol):
    def execute(self, invocation: Invocation) -> "CommandResult": ...


Handler = Callable[[Invocation], "CommandResult"]
Provider = Callable[[Invocation], dict[str, Any]]


# Imported only for type checking to avoid a runtime messages/models cycle.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .messages import CommandResult
