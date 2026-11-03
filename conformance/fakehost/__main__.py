"""Run the fake host as its own process.

    python -m fakehost --state-dir DIR [--config FILE] [--commands FILE] [--workdir DIR]

It prints one JSON line, ``{"address": ..., "pid": ..., "workdir": ...}``, then serves until
the control method ``fake.shutdown`` or an interrupt.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .server import FakeHost


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fakehost", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", help="the tool's state directory; discovery files go to hosts/ inside it")
    parser.add_argument("--config", help="a JSON file with the world: application, instances, files, devices, host_component")
    parser.add_argument("--commands", help="the tool's contract/commands.json")
    parser.add_argument("--workdir", help="where document files are kept (default: a new temporary directory)")
    args = parser.parse_args(argv)
    config = _load(args.config)
    commands = _load(args.commands)
    if isinstance(commands, dict):
        commands = commands.get("commands", [])
    host = FakeHost(args.state_dir, config, commands, args.workdir).start()
    print(json.dumps({"address": host.address, "pid": os.getpid(), "workdir": str(host.world.workdir)}), flush=True)
    try:
        while not host.stopped.wait(0.5):
            pass
    except KeyboardInterrupt:
        host.stop()
    return 0


def _load(path: str | None):
    if not path:
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


if __name__ == "__main__":
    sys.exit(main())
