"""The conformance tests on registrations the sample tool does not have by default: commands
registered with doc_kinds (DCLI-210), a standard doc save listed as long, and a long command
that only makes a file (DCLI-065). Each case switches the sample tool with an environment
variable and edits the registrations the suites read to match."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import Any, Callable
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "conformance"))

from suites import driver, general  # noqa: E402
from suites.harness import Subject  # noqa: E402

TESTS = {**general.TESTS, **driver.TESTS, **general.LAST}


def run(env: dict[str, str], edit: Callable[[dict[str, Any]], None], ids: list[str]) -> None:
    with mock.patch.dict(os.environ, env):
        subject = Subject([sys.executable, "-m", "sample_cli"], REPO / "tests" / "sample")
        edit(subject.registrations)
        for test_id in ids:
            TESTS[test_id](subject)


class SuiteVariants(unittest.TestCase):
    def test_commands_registered_with_doc_kinds(self):
        def kinds(regs: dict[str, Any]) -> None:
            for reg in regs.values():
                if "file" in reg["modes"] or "session" in reg["modes"]:
                    reg["doc_kinds"] = ["part"]
        run({"SAMPLE_CLI_DOC_KINDS": "part"}, kinds, ["G01", "G04", "D03", "D08", "D16", "D26", "R04"])

    def test_a_doc_save_listed_as_long(self):
        run({"SAMPLE_CLI_LONG": "doc save"}, lambda regs: None, ["G04", "D04", "D09"])

    def test_a_long_command_that_only_makes_a_file(self):
        def long_export(regs: dict[str, Any]) -> None:
            regs["drawing export"]["long"] = True
        run({"SAMPLE_CLI_LONG_EXPORT": "1"}, long_export, ["D26"])


if __name__ == "__main__":
    unittest.main()
