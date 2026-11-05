"""The sample driver tool. It drives no real application: the runtime tests and the
conformance suites run it with SAMPLE_CLI_FAKE_HOST set, so the fake host stands in for the
application. SAMPLE_CLI_VARIANT=host makes it a tool with a host component."""
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


def build() -> Tool:
    return Tool(
        root=ROOT, adapter=SampleAdapter, commands=COMMANDS, application="FakeApp", versions=">=1.0 <2",
        modes=["file", "session", "device"], host_component=os.environ.get("SAMPLE_CLI_VARIANT") == "host",
        contract=REPO / "contract" / "driver-contract.json",
        # Tests list slow standard writes here to run them as long jobs (DCLI-065).
        long_commands=[c for c in os.environ.get("SAMPLE_CLI_LONG", "").split(",") if c],
    )


def main() -> None:
    build().main()
