"""The sample driver tool. It drives no real application: the runtime tests and the
conformance suites run it with SAMPLE_CLI_FAKE_HOST set, so the fake host stands in for the
application. SAMPLE_CLI_VARIANT=host makes it a tool with a host component. Tests switch more
with SAMPLE_CLI_LONG (standard writes run as long jobs), SAMPLE_CLI_DOC_KINDS (every command on
a document works only on that kind), SAMPLE_CLI_LONG_EXPORT=1 (drawing export is long) and
SAMPLE_CLI_PART_FILE=1 (part move may also make a file)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO / "sdk" / "python"))

from _driver import Tool  # noqa: E402

from .adapter import SampleAdapter  # noqa: E402
from .commands import COMMANDS  # noqa: E402


def commands() -> list[dict]:
    """The registrations, with the switches tests set."""
    out = [dict(c) for c in COMMANDS]
    kind = os.environ.get("SAMPLE_CLI_DOC_KINDS")
    for reg in out:
        if kind and ("file" in reg["modes"] or "session" in reg["modes"]):
            reg["doc_kinds"] = [kind]  # the fake host makes its documents of the kind a test sets
        if os.environ.get("SAMPLE_CLI_LONG_EXPORT") == "1" and reg["path"] == "drawing export":
            reg["long"] = True  # a long command that only makes a file
        if os.environ.get("SAMPLE_CLI_PART_FILE") == "1" and reg["path"] == "part move":
            reg["effects"] = ["change", "artifact"]  # a command that makes a file only in some calls
    return out


def build() -> Tool:
    return Tool(
        root=ROOT, adapter=SampleAdapter, commands=commands(), application="FakeApp", versions=">=1.0 <2",
        modes=["file", "session", "device"], host_component=os.environ.get("SAMPLE_CLI_VARIANT") == "host",
        contract=REPO / "contract" / "driver-contract.json",
        # Tests list slow standard writes here to run them as long jobs (DCLI-065).
        long_commands=[c for c in os.environ.get("SAMPLE_CLI_LONG", "").split(",") if c],
    )


def main() -> None:
    build().main()
