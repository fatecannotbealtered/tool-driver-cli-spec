# Command registrations and behavior matrices

Use this file in steps 4 and 6: registering a domain command and writing its behavior matrix.

## Registration

Each domain command is one dict in `COMMANDS` of `<pkg>/commands/__init__.py`. The runtime checks every registration when the tool starts and refuses one that breaks a rule, so run `python -m <pkg> reference` after each change. The fields are those of DCLI-029, plus `output_schema`, `examples`, `maturity` and `evidence`, which `reference` shows.

```python
BOARD = "board: origin at the top-left corner, x to the right, y down"

COMMANDS = [
    {
        "path": "footprint move",
        "summary": "Move one footprint to a position on the board.",
        "effects": ["change"],
        "modes": ["session"],
        "target_kind": "footprint",
        "flags": [
            {"name": "--id", "type": "string", "required": True, "summary": "The reference designator, such as R1."},
            {"name": "--x", "type": "quantity", "quantity": "length", "summary": "X position.", "coordinate_system": BOARD},
            {"name": "--y", "type": "quantity", "quantity": "length", "summary": "Y position.", "coordinate_system": BOARD},
        ],
        "untrusted_fields": ["value"],
        "irreversible": False,
        "halt": False,
        "tolerances": {"x_mm": 0.001, "y_mm": 0.001},
        "default_fields": [],
        "related_knowledge": ["kicad-save-leaves-edit-mode"],
        "output_schema": {"type": "object", "properties": {
            "id": {"type": "string"}, "value": {"type": "string"}, "x_mm": {"type": "number"}, "y_mm": {"type": "number"}}},
        "examples": ["kicad-cli footprint move --session kicad-1234 --doc D:/proj/board.kicad_pcb --id R1 --x 12.5mm --y 30mm"],
        "maturity": "draft",
        "evidence": [],
    },
]
```

- `path` is `noun verb`. The verb comes from the fixed list of DCLI-022; the noun is the application's own term, written in full, and never a reserved name (DCLI-023, DCLI-024).
- Do not declare `--session`, `--doc`, `--device` or `--job`; the runtime adds the target flags for each mode (DCLI-027). Other objects are selected with `--id` or `--ids`. A shared function uses the shared flag of DCLI-026. Never add a global flag (DCLI-025).
- Every physical value is a `quantity` flag with its quantity from the units table; the user writes the unit in the value, such as `12.5mm`, and output fields carry the unit in their name, such as `x_mm` (DCLI-080 to DCLI-084).
- Declare every effect (DCLI-051). The runtime derives the confirmation tier; you never set it (DCLI-052). Mark a change the application cannot take back `irreversible`, and a `stop` command `halt` (DSEC-018).
- List in `untrusted_fields` every output field that holds text from the application or its files (DSEC-021). Mark a flag that carries a secret with `secret: true` (DSEC-040).
- Set the disposition of the capabilities the command provides to `provided` in both survey files (DREPO-060).
- Register `jobs: true` only for a write the application itself may run as a long job; the runtime then follows the job with `job_status` (DCLI-065).
- Start every command at `draft` with no evidence; raise it only as DVER-040 allows.

Then run `python scripts/spec.py generate`. It writes `contract/commands.json`, the command maps and a first behavior matrix for each command that has none.

## Behavior matrix

Every domain command, and every standard command whose adapter capabilities the tool implements, has one file `tests/matrix/<noun>-<verb>.json` (DVER-030). The first file `generate` writes already marks each row: rows whose condition does not hold say why, and rows that apply carry the expected exit code and error code and a `{{fill: ...}}` for the arguments. Replace each `{{fill: ...}}` with real arguments.

```json
{"row": "normal", "applies": true,
 "arguments": ["--session", "{session}", "--doc", "{doc}", "--id", "R1", "--x", "12.5mm", "--y", "30mm"],
 "expected": {"exit": 0}}
```

- The `normal` row of a write command is its sample: the general suite runs it against the fake host (DVER-002).
- Name sessions, documents, devices and output folders only with `{session}`, `{doc}`, `{device}` and `{dir}`, a job with `{job}`, and a file the command only reads, such as a design description, with `{inputs}`: put it in `tests/inputs/`.
- A row that applies but cannot happen for this command becomes `"applies": false` with the reason.
- A row that applies but cannot be caused on demand on the real application, such as `disconnect`, may keep its arguments and add `"unrunnable": "<reason>"`. `normal`, `dialog` and `read_back_mismatch` never may.
- A complete example is `contract/examples/valid/behavior-matrix/footprint-move.json` in the release.

## Live runs

Follow the procedure of the project's `docs/E2E.md`. A person lists the targets under Authorized Targets, writes the scope file for them and gives you its path; when the person asks you in their own message to write them, show the content and write it once they agree; set `<PREFIX>_SCOPE_FILE` to it and `<PREFIX>_STATE_DIR` to a separate directory for live runs. With a host component, install it first with that state directory ([host-component.md](host-component.md)). Then, with one `--set` per placeholder the matrix uses:

```bash
python scripts/spec.py matrix --command "footprint move" --set session=<instance> --set doc=<authorized file>
```

- Without `--row` it runs every row that applies, except rows marked `unrunnable`; `--row normal,not_found` runs only the rows named. Each run writes a live record to `docs/evidence/` and fills in each row's actual result and `live:` evidence.
- Run the rows that need no preparation together. Run a row whose situation must be prepared, such as `dialog` (a dialog open in the application), on its own after the person prepares it: the same command with `--row dialog`.
- `dialog` and `read_back_mismatch` are never `unrunnable`; find a way to cause them, with the person's help.
- `--row read_back_mismatch` makes the tool wait before its read-back, up to `--pause` seconds (120 by default), and writes `pause.json` in the tool's state directory. Meanwhile the person changes what was just written in the application, or deletes the file a write made; or pass `--tamper "<command>"`, a command that does it, with `TOOL_DRIVER_PAUSE_FILE` naming `pause.json`. The row expects `E_VERIFY_FAILED`. It is not applicable only when the result cannot be changed from outside, such as a delivery or a physical action.
- A command with `doc_kinds` runs its `normal` row once on a document of each kind, each time with `--kind <kind>`. When the objects the arguments name differ between kinds, such as a feature path in an assembly, add `"kind_arguments": {"<kind>": [...]}` to the `normal` row; `arguments` serve the other kinds.
- Several runs of one matrix may run at once, such as the `busy` row while the `normal` row's job runs; each writes its own record and changes only its own rows.
- The `normal` row of a command with `verify_after_save` is followed by `doc save` on the same document; give `--set session=` and `--set doc=`, and grant `persist` in the scope.
- When every row that applies passed, except rows marked `unrunnable`, set the command's `maturity` to `verified` and add the record to its `evidence`, such as `live:docs/evidence/<file>.json#normal`. Then run `python scripts/spec.py generate` and `python scripts/spec.py check`.
