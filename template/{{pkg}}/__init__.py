"""{{tool}}: lets an AI Agent operate {{application}} safely from the command line.

The driver runtime in ``_driver/`` does everything every driver tool shares. This package adds
the domain commands (``commands/``) and the adapter that talks to {{application}} (``adapter/``).
"""
from __future__ import annotations

import sys
from pathlib import Path

from ._driver import Tool
from .adapter import Adapter
from .commands import COMMANDS

# package.json, CHANGELOG.md, knowledge/, skills/ and contract/ sit at the project root; in the
# native program they are bundled next to the code.
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))

TOOL = Tool(
    root=ROOT,
    adapter=Adapter,
    commands=COMMANDS,
    application="{{application}}",
    versions="{{versions}}",
    modes={{modes}},
    host_component={{host_component}},
    # Standard writes that take {{application}} more than a minute, such as "doc open" of a large
    # project; the runtime runs them as long jobs (DCLI-065, contract jobs.standard_long).
    long_commands=[],
{{#host_component}}
    # plugin/manifest.json records the host component's files and methods; `python scripts/spec.py
    # generate` writes all of it but `methods` (DCLI-240).
    plugin_manifest=ROOT / "plugin" / "manifest.json",
{{/host_component}}
)


def main() -> None:
    TOOL.main()
