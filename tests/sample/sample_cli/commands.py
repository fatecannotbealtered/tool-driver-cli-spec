"""The domain commands of the sample tool: one of each kind the runtime handles differently."""
from __future__ import annotations

from typing import Any

BOARD = "board: origin at the top-left corner, x right, y down"
PART = {"type": "object", "properties": {"id": {"type": "string"}, "value": {"type": "string"},
                                         "x_mm": {"type": "number"}, "y_mm": {"type": "number"}}}


def command(path: str, summary: str, effects: list[str], modes: list[str], flags: list[dict[str, Any]],
            examples: list[str], **extra: Any) -> dict[str, Any]:
    writes = effects != ["observe"]
    reg: dict[str, Any] = {
        "path": path, "summary": summary, "effects": effects, "modes": modes, "target_kind": extra.pop("target_kind", "part"),
        "flags": flags, "untrusted_fields": extra.pop("untrusted_fields", []),
        "adapter_capabilities": extra.pop("capabilities", ["read", "preview", "apply", "read_back"] if writes else ["read"]),
        "survey_ids": extra.pop("survey_ids", ["CAP-001"]), "irreversible": extra.pop("irreversible", False),
        "halt": extra.pop("halt", False), "tolerances": extra.pop("tolerances", {}),
        "default_fields": extra.pop("default_fields", []), "related_knowledge": extra.pop("related_knowledge", []),
        "output_schema": extra.pop("output_schema", PART), "examples": [f"sample-cli {e}" for e in examples],
        "maturity": "draft", "evidence": [],
    }
    for name in ("long", "doc_kinds", "verify_after_save", "tier_when"):
        if name in extra:
            reg[name] = extra.pop(name)
    assert not extra, extra
    return reg


ID = {"name": "--id", "type": "string", "summary": "The reference of the part."}
IDS = {"name": "--ids", "type": "list", "summary": "Several parts, separated by commas."}
X = {"name": "--x", "type": "quantity", "quantity": "length", "summary": "X position.", "coordinate_system": BOARD}
Y = {"name": "--y", "type": "quantity", "quantity": "length", "summary": "Y position.", "coordinate_system": BOARD}

COMMANDS = [
    command("part get", "Read one part.", ["observe"], ["file", "session"], [{**ID, "required": True}],
            ["part get --doc board.fake --id R1"], untrusted_fields=["value"]),
    command("part list", "List the parts of a document.", ["observe"], ["file", "session"],
            [{"name": "--limit", "type": "integer"}, {"name": "--offset", "type": "integer"}],
            ["part list --doc board.fake"], default_fields=["id", "value"], untrusted_fields=["value"]),
    command("part move", "Move one or more parts.", ["change"], ["file", "session"],
            [ID, IDS, {"name": "--input", "type": "input", "summary": "Each part with its own position."}, X, Y],
            ["part move --doc board.fake --id R1 --x 12.5mm --y 30mm"], tolerances={"x_mm": 0.001, "y_mm": 0.001}),
    command("part update", "Change the value of a part in a file.", ["change"], ["file"],
            [{**ID, "required": True}, {"name": "--value", "type": "string", "summary": "The new value."}],
            ["part update --doc board.fake --id R1 --value 10k"], untrusted_fields=["value"]),
    command("part delete", "Delete parts; the application cannot undo it.", ["change"], ["session"], [ID, IDS],
            ["part delete --doc board.fake --id R9"], irreversible=True),
    command("drawing export", "Export the drawing as a PDF.", ["artifact"], ["session"],
            [{"name": "--output", "type": "path", "output": True, "required": True, "summary": "The PDF to write."}],
            ["drawing export --doc board.fake --output board.pdf"], target_kind="file",
            output_schema={"type": "object"}),
    command("analysis run", "Run the analysis of a document; long analyses continue as a long job.", ["change"], ["session"],
            [{"name": "--depth", "type": "integer", "summary": "How many passes to run."}],
            ["analysis run --doc board.fake --depth 3"], target_kind="document",
            capabilities=["read", "preview", "apply", "read_back", "job_status", "cancel"], output_schema={"type": "object"}),
    command("axis move", "Move a machine axis to a position.", ["physical"], ["device"],
            [{**ID, "required": True, "summary": "The axis."},
             {"name": "--position", "type": "quantity", "quantity": "length", "summary": "The target position.",
              "coordinate_system": "machine: origin at the home position, axes as labelled on the machine"}],
            ["axis move --device cnc-01 --id x --position 10mm"], target_kind="axis", output_schema={"type": "object"}),
    command("cycle stop", "Stop the running machine cycle.", ["lifecycle"], ["device"], [],
            ["cycle stop --device cnc-01"], target_kind="device", halt=True, output_schema={"type": "object"}),
    command("route run", "Route a net; the runtime runs the work as a long job.", ["change"], ["session"],
            [{"name": "--net", "type": "string", "summary": "The net to route."}],
            ["route run --doc board.fake --net GND"], target_kind="document", output_schema={"type": "object"}, long=True),
    command("net update", "Rename a net; the application shows it only after a save.", ["change"], ["session"],
            [{**ID, "required": True, "summary": "The net."}, {"name": "--name", "type": "string", "summary": "The new name."},
             {"name": "--pins", "type": "json", "summary": "The pins on the net.",
              "schema": {"type": "array", "items": {"type": "object", "properties": {"pin": {"type": "string"}}}}}],
            ["net update --doc board.fake --id N1 --name GND"], target_kind="net", output_schema={"type": "object"},
            verify_after_save=True),
    command("design check", "Check the design rules; the runtime runs the check as a long job.", ["observe"], ["file", "session"],
            [], ["design check --doc board.fake"], target_kind="document", output_schema={"type": "object"}, long=True,
            doc_kinds=["board"]),
]
