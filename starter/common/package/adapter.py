"""The native side of {{NAME}}. Replace the refusals with real calls, one command at a time.

Rules the SDK cannot enforce for you:
- run() and plan() never change the target; plan() returns the target, its baseline snapshot and the changes it expects.
- apply() re-checks the baseline (or implement revision(target)), dispatches, reads the result back and returns
  receipt fields that report what was observed. Never report saved, delivered or verified without observing it.
- Raise DriverError with the real dispatch_state: not_started, dispatched or unknown.
- Text that came from the target or the application belongs in fields listed in _untrusted.
"""

from __future__ import annotations

from tool_driver_sdk import DriverError

NOT_IMPLEMENTED = "The native adapter is not implemented yet; nothing was sent to the application."


class Adapter:
    def environment(self) -> dict:
        return {
            "components": [{"name": "native application", "role": "application", "version": None, "build_id": None,
                            "location": "unknown", "identity_status": "unavailable", "reason": "The adapter is not implemented."}],
            "connection": {"status": "not_connected", "instance_id": None, "generation": None, "ownership": None,
                           "reason": "The adapter is not implemented."},
        }

    def doctor_checks(self) -> list[dict]:
        return [{"check": "native_backend", "status": "fail", "fix": "Implement {{PACKAGE}}/adapter.py for the {{PROFILE}} mode.",
                 "message": "no native adapter yet"}]

    def run(self, call):
        raise DriverError("E_UNSUPPORTED", NOT_IMPLEMENTED,
                          details={"next_action": "This build cannot observe targets yet; tell the user the adapter is missing."})

    def plan(self, call):
        raise DriverError("E_UNSUPPORTED", NOT_IMPLEMENTED,
                          details={"next_action": "This build cannot plan changes yet; tell the user the adapter is missing."})

    def apply(self, call, plan):
        raise DriverError("E_UNSUPPORTED", NOT_IMPLEMENTED, dispatch_state="not_started",
                          details={"next_action": "Nothing was sent; this build cannot apply changes yet."})
