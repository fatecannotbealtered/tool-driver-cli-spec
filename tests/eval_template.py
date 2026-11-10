#!/usr/bin/env python3
"""The repository's evaluation suite (DSKL-041): every scenario, run with the template tool on
the fake host.

    python tests/eval_template.py [--only <id>,<id>] [--keep]
        check every grader with the scripted agents: `right` passes, every `wrong` fails (CI)
    python tests/eval_template.py --agent claude --report <file> [--model <model>] [--only ...]
        run every question with Claude Code; before each release every question must pass

It generates the template tool with every mode, registers one command of each kind the
scenarios need, writes the builtin knowledge one question looks up, fills in the remaining
placeholders, and runs scripts/run_eval.py on conformance/eval/ with --fake-host.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from e2e_template import NO_WINDOW, PKG, REPO, fill, generate  # noqa: E402

COMMANDS = '''"""The domain commands of demo-cli: one of each kind the evaluation scenarios need."""
from __future__ import annotations

from typing import Any

BOARD = "board: origin at the top-left corner, x right, y down"
PART = {"type": "object", "properties": {"id": {"type": "string"}, "value": {"type": "string"},
                                         "x_mm": {"type": "number"}, "y_mm": {"type": "number"}}}


def command(path: str, summary: str, effects: list[str], modes: list[str], flags: list[dict[str, Any]], example: str,
            **extra: Any) -> dict[str, Any]:
    reg: dict[str, Any] = {
        "path": path, "summary": summary, "effects": effects, "modes": modes, "target_kind": extra.pop("target_kind", "part"),
        "flags": flags, "untrusted_fields": extra.pop("untrusted_fields", []),
        "irreversible": extra.pop("irreversible", False), "halt": extra.pop("halt", False),
        "tolerances": extra.pop("tolerances", {}), "default_fields": extra.pop("default_fields", []),
        "related_knowledge": extra.pop("related_knowledge", []), "output_schema": extra.pop("output_schema", PART),
        "examples": [f"demo-cli {example}"], "maturity": "draft", "evidence": [],
    }
    if extra.pop("jobs", False):
        reg["jobs"] = True
    assert not extra, extra
    return reg


ID = {"name": "--id", "type": "string", "summary": "The reference of the part."}
IDS = {"name": "--ids", "type": "list", "summary": "Several parts, separated by commas."}
X = {"name": "--x", "type": "quantity", "quantity": "length", "summary": "X position.", "coordinate_system": BOARD}
Y = {"name": "--y", "type": "quantity", "quantity": "length", "summary": "Y position.", "coordinate_system": BOARD}

COMMANDS = [
    command("part get", "Read one part.", ["observe"], ["file", "session"], [{**ID, "required": True}],
            "part get --doc board.fake --id R1", untrusted_fields=["value"], related_knowledge=["demo-basics"]),
    command("part list", "List the parts of a document.", ["observe"], ["file", "session"],
            [{"name": "--limit", "type": "integer", "summary": "Parts per page."},
             {"name": "--offset", "type": "integer", "summary": "Start position of the page."}],
            "part list --doc board.fake", default_fields=["id", "value"], untrusted_fields=["value"]),
    command("part move", "Move one or more parts.", ["change"], ["file", "session"],
            [ID, IDS, {"name": "--input", "type": "input", "summary": "Each part with its own position."}, X, Y],
            "part move --doc board.fake --id R1 --x 12.5mm --y 30mm", tolerances={"x_mm": 0.001, "y_mm": 0.001},
            related_knowledge=["demo-basics"]),
    command("part delete", "Delete parts; FakeApp cannot undo it.", ["change"], ["session"], [ID, IDS],
            "part delete --doc board.fake --id R9", irreversible=True),
    command("analysis run", "Run the analysis of a document; a long analysis continues as a long job.", ["change"],
            ["session"], [{"name": "--depth", "type": "integer", "summary": "How many passes to run."}],
            "analysis run --doc board.fake --depth 3", target_kind="document",
            jobs=True, output_schema={"type": "object"}),
    command("axis move", "Move a machine axis to a position.", ["physical"], ["device"],
            [{**ID, "required": True, "summary": "The axis."},
             {"name": "--position", "type": "quantity", "quantity": "length", "summary": "The target position.",
              "coordinate_system": "machine: origin at the home position, axes as labelled on the machine"}],
            "axis move --device cnc-01 --id x --position 10mm", target_kind="axis", output_schema={"type": "object"}),
    command("cycle stop", "Stop the running machine cycle.", ["lifecycle"], ["device"], [],
            "cycle stop --device cnc-01", target_kind="device", halt=True, output_schema={"type": "object"}),
]
'''

SAMPLES = {
    "part get": ["--session", "{session}", "--doc", "{doc}", "--id", "R1"],
    "part list": ["--session", "{session}", "--doc", "{doc}"],
    "part move": ["--session", "{session}", "--doc", "{doc}", "--id", "R1", "--x", "12.5mm", "--y", "30mm"],
    "part delete": ["--session", "{session}", "--doc", "{doc}", "--id", "R9"],
    "analysis run": ["--session", "{session}", "--doc", "{doc}", "--depth", "3"],
    "axis move": ["--device", "{device}", "--id", "x", "--position", "10mm"],
    "cycle stop": ["--device", "{device}"],
}

ROWS = ["empty", "invalid_input", "not_found", "ambiguous", "conflict", "no_scope", "busy", "dialog", "disconnect",
        "unsaved", "read_back_mismatch"]

# The builtin knowledge: the grid pitch is a fact only the knowledge base holds (knowledge_lookup).
BASICS = """---
id: demo-basics
title: Part positions in FakeApp snap to the placement grid
kind: guide
applies_to: [part move, part get]
tags: [placement, grid]
---

FakeApp keeps every part on its placement grid. The pitch of the placement grid is 0.7366 mm,
and FakeApp rounds a requested position to the nearest grid point. Ask for positions that are
multiples of 0.7366 mm when the exact value matters.
"""

TROUBLESHOOTING = """---
id: demo-troubleshooting
title: The license reminder dialog blocks FakeApp
kind: troubleshooting
applies_to: [context]
tags: [dialog, license]
---

FakeApp shows a license reminder dialog at start and blocks every command until a person
closes it. demo-cli reports it as E_HUMAN_REQUIRED with the dialog title; ask the person to
close the dialog, then run the resume command the error gives.
"""


def register(project: Path) -> None:
    (project / PKG / "commands" / "__init__.py").write_text(COMMANDS, encoding="utf-8", newline="\n")
    for path, sample in SAMPLES.items():
        rows = [{"row": "normal", "applies": True, "arguments": sample, "expected": {"exit": 0}}]
        rows += [{"row": r, "applies": False, "reason": "The demo tool drives no real application."} for r in ROWS]
        matrix = project / "tests" / "matrix" / f"{path.replace(' ', '-')}.json"
        matrix.write_text(json.dumps({"command": path, "rows": rows}, indent=2) + "\n", encoding="utf-8", newline="\n")
    for name in ("docs/APPLICATION.md", "docs/APPLICATION_zh.md"):
        survey = project / name
        text = survey.read_text(encoding="utf-8")
        text = re.sub(r"\| CAP-001 \|[^\n]*", "| CAP-001 | Parts, analysis and axes | The automation API | provided | - |", text)
        survey.write_text(text, encoding="utf-8", newline="\n")
    knowledge = project / "knowledge"
    for old in knowledge.glob("*.md"):
        old.unlink()
    (knowledge / "demo-basics.md").write_text(BASICS, encoding="utf-8", newline="\n")
    (knowledge / "demo-troubleshooting.md").write_text(TROUBLESHOOTING, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", choices=["claude"], help="run the questions with a real Agent")
    parser.add_argument("--model")
    parser.add_argument("--report", help="where the real Agent's report goes; needed with --agent")
    parser.add_argument("--only")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if args.agent and not args.report:
        parser.error("--agent needs --report: the report is published with the release")
    work = Path(tempfile.mkdtemp(prefix="eval-template-")).resolve()
    try:
        print("== generate the template tool", flush=True)
        project = generate(work, "file,session,device", False)
        register(project)
        fill(project)
        cmd = [sys.executable, str(REPO / "scripts" / "run_eval.py"), str(project), "--questions",
               str(REPO / "conformance" / "eval"), "--fake-host"]
        if args.only:
            cmd += ["--only", args.only]
        if args.keep:
            cmd += ["--keep"]
        if args.agent:
            cmd += ["--report", str(Path(args.report).resolve())] + (["--model", args.model] if args.model else [])
        else:
            cmd += ["--check"]
        print(f"== {'evaluate with ' + args.agent if args.agent else 'check the graders'}", flush=True)
        sys.stdout.flush()
        return subprocess.call(cmd, cwd=REPO, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL, stdout=sys.stdout,
                               stderr=sys.stderr)
    finally:
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
