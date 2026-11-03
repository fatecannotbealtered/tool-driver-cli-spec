"""The sample adapter. It names the capabilities the sample tool has; without the fake host
each one reports that there is no application to drive."""
from __future__ import annotations

from typing import Any

from _driver import Adapter, AdapterError

CAPABILITIES = [
    "sessions", "open_session", "close_session", "documents", "create_doc", "open_doc", "save_doc", "save_doc_as",
    "close_doc", "undo", "read", "preview", "apply", "read_back", "job_status", "cancel", "devices",
    "plugin_status", "plugin_install", "plugin_remove",
]


class SampleAdapter(Adapter):
    def probe(self, request: dict[str, Any]) -> dict[str, Any]:
        return {"found": False}


def _unavailable(name: str) -> Any:
    def capability(self: SampleAdapter, request: dict[str, Any]) -> dict[str, Any]:
        raise AdapterError("E_BACKEND_UNAVAILABLE", f"The sample tool drives no real application; {name} needs the fake host.")

    capability.__name__ = name
    return capability


for _name in CAPABILITIES:
    setattr(SampleAdapter, _name, _unavailable(_name))
