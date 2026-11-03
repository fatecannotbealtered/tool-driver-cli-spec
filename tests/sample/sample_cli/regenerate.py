"""Write contract/commands.json and the behavior matrices of the sample tool.

    python -m sample_cli.regenerate

The sample tool runs on the fake host alone, so each matrix keeps only its write sample, the
normal row; the other rows say why they do not apply here.
"""
from __future__ import annotations

import json

from . import ROOT, build

SAMPLES = {
    "part move": ["--session", "{session}", "--doc", "{doc}", "--id", "R1", "--x", "12.5mm", "--y", "30mm"],
    "part update": ["--doc", "{doc}", "--id", "R1", "--value", "10k"],
    "part delete": ["--session", "{session}", "--doc", "{doc}", "--id", "R9"],
    "drawing export": ["--session", "{session}", "--doc", "{doc}", "--output", "{dir}/drawing.pdf"],
    "analysis run": ["--session", "{session}", "--doc", "{doc}", "--depth", "3"],
    "axis move": ["--device", "{device}", "--id", "x", "--position", "10mm"],
    "cycle stop": ["--device", "{device}"],
}
ROWS = ["normal", "empty", "invalid_input", "not_found", "ambiguous", "conflict", "no_scope", "busy", "dialog",
        "disconnect", "unsaved", "read_back_mismatch"]
REASON = "The sample tool drives no real application; it keeps only its write sample, for the conformance suites."


def main() -> None:
    tool = build()
    (ROOT / "contract" / "commands.json").write_text(json.dumps(tool.registration(), indent=2) + "\n", encoding="utf-8")
    folder = ROOT / "tests" / "matrix"
    for path, args in SAMPLES.items():
        rows = [{"row": "normal", "applies": True, "arguments": args, "expected": {"exit": 0}}]
        rows += [{"row": row, "applies": False, "reason": REASON} for row in ROWS[1:]]
        text = json.dumps({"command": path, "rows": rows}, indent=2) + "\n"
        (folder / f"{path.replace(' ', '-')}.json").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
