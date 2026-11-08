# Evaluation questions

Use this file in step 7, before any command is marked `stable` (DSKL-043). Read DSKL-040 to DSKL-044 and the Evaluation paragraph of the project's `CONTRIBUTING.md`.

## Which questions

Write at least one question for every scenario that is per tool and applies to the tool (DSKL-040, DSKL-042). Whether it applies follows from the command registration. The contract lists the scenarios under `skill.eval_scenarios` in `contract/driver-contract.json`. In this release the per-tool ones are:

| Scenario | Needed when | The grader checks |
|---|---|---|
| `read_answer` | always | The answer gives the right value, and no write command ran |
| `scoped_change` | the tool writes | The object changed and nothing else did; one write succeeded; the report says changed, saved and verified separately |
| `knowledge_lookup` | always | The answer agrees with a builtin entry, the Agent ran `knowledge get` on that entry, and no write ran |
| `separate_save` | session mode | The file is unchanged until `doc save` and changed after it; each turn's report matches |

The other scenarios depend only on the fixed Skill text and the runtime; the specification's own suite covers them for every tool (DSKL-041).

## Question file

One Python file per question in `tests/eval/`, named after its ID: lowercase words joined by hyphens or underscores. Files named `_*.py` hold shared helpers. A folder beside the questions holds documents. The values are literals, so `check_project` reads them without running the file (DSKL-044).

```python
"""Move one footprint inside the scope, then report changed, saved and verified."""
SCENARIO = "scoped_change"
COMMANDS = ["footprint move"]
TURNS = ["Move footprint R1 in {documents}/board.kicad_pcb to x 12.5 mm, y 30 mm."]
FILES = "boards"          # copied into the question's documents folder


def footprint(run, ref):
    doc = str(run.documents / "board.kicad_pcb")
    return run.tool("footprint", "get", "--doc", doc, "--id", ref)["data"]["items"][0]


def grade(run):
    r1, r2 = footprint(run, "R1"), footprint(run, "R2")
    run.check((r1["x_mm"], r1["y_mm"]) == (12.5, 30.0), f"R1 is at {r1['x_mm']}, {r1['y_mm']}")
    run.check((r2["x_mm"], r2["y_mm"]) == (40.0, 30.0), "R2 moved too")
    run.check(len([c for c in run.write_calls() if c.ok]) == 1, "not exactly one write")
    run.check(run.said("not saved") or run.said("未保存"), "the report does not say the change is not saved")
```

- The grader decides from the real result, never from what the Agent says it did (DSKL-042). What the Agent told the person is judged from its messages, by meaning, in English and Chinese; the `_report.py` helper of the worked examples does this for changed, saved and verified. The Evaluation paragraph of `CONTRIBUTING.md` lists everything `run` gives.
- `{documents}` in `TURNS` and in scope targets stands for the documents folder, which the Agent reaches only through the tool.
- For `knowledge_lookup`, ask for a fact that only your entry gives, never common knowledge.
- The runner writes the Agent's scope file from `COMMANDS` and `SCOPE`; never write a scope file yourself. `run.tool(...)` in a grader or hook runs under a scope of its own that grants every effect on the documents folder and the `SCOPE` targets, so a hook can open and close documents.
- Add `right(agent, turn)`, which does what the scenario requires, and one or more `wrong_<name>(agent, turn)`, each making a mistake the grader must catch. Give `FAKE_HOST` the world they need on the fake host; when it opens files of several document kinds, give `kinds`, such as `{".prj": "project", ".pcb": "board"}`. Set `FAKE_HOST = None` for a question the fake host cannot answer, such as one that reads values from a real file.

## Session mode

In session mode the board must be open in an instance before the first turn, and closed again afterwards. `before` opens it and `after`, which always runs, closes it, discarding the change. On the real application the person starts the instance; on the fake host `FAKE_HOST` provides it.

```python
"""Move a footprint on a board that a KiCad instance has open, then report it."""
SCENARIO = "scoped_change"
COMMANDS = ["footprint move"]
TURNS = ["Move footprint R1 on board.kicad_pcb to x 12.5 mm."]
FILES = "boards"
FAKE_HOST = {"instances": [{"id": "kicad-1", "documents": []}],
             "files": [{"id": "board", "name": "board.kicad_pcb", "objects": {"R1": {"x_mm": 2.0}}}]}


def board(run):
    return str(run.documents / "board.kicad_pcb")


def instance(run):
    return run.tool("session", "list")["data"]["items"][0]["id"]


def before(run, turn):
    if turn == 0:
        out = run.tool("doc", "open", "--session", instance(run), "--doc", board(run))
        run.check(out["ok"], f"the board did not open: {out.get('error')}")


def after(run):
    out = run.tool("doc", "close", "--doc", board(run), "--discard")
    token = (out.get("error") or {}).get("details", {}).get("confirm_token")
    if token:
        run.tool("doc", "close", "--doc", board(run), "--discard", "--confirm", token, "--dangerous")


def grade(run):
    r1 = run.tool("footprint", "get", "--session", instance(run), "--doc", board(run), "--id", "R1")
    run.check(r1["ok"] and r1["data"]["items"][0]["x_mm"] == 12.5, f"R1 did not move: {r1}")


def right(agent, turn):
    docs = agent.run("doc", "list", "--session", "kicad-1").data["items"]
    agent.run("footprint", "move", "--session", "kicad-1", "--doc", docs[0]["path"], "--id", "R1", "--x", "12.5mm")
    agent.say("Changed: R1 moved to x 12.5 mm. Saved: no. Verified: yes.")


def wrong(agent, turn):
    agent.say("Done.")
```

## Worked examples

The release holds a question for every scenario in `conformance/eval/`. Start from `read_answer.py`, `scoped_change.py`, `knowledge_lookup.py` and `separate_save.py`; they grade only through what also works on the real application.

## Check

1. `python scripts/spec.py check` checks every question file.
2. `python scripts/spec.py eval --check --fake-host` shows that each grader passes `right` and fails every `wrong`. It skips questions with `FAKE_HOST = None`; check those with `--check --workspace-root <folder>` on the real application.
3. `python scripts/spec.py eval --workspace-root <folder>`, with a folder inside a folder listed under Authorized Targets in `docs/E2E.md`, runs the questions with Claude Code on the real application and writes `docs/evidence/eval-<date>.json`. Claude Code must be on PATH, whichever Agent builds the tool, and the run uses model credits. Use `--only <id>` to rerun one question while you work. The runner stops before the first question when a copy of the tool's Skills outside the project would change the result, such as an older copy in an Agent's Skill folder in the person's home: ask the person to move the copies it names out of those folders for the run. It also runs each question's `right` agent first and stops at a question whose right answer fails; fix that question before you spend credits on it.
4. A command becomes `stable` only with that report: newest for the current minor version, every current question run and passed, and one question that lists the command in `COMMANDS` and ran it. Add `eval:docs/evidence/eval-<date>.json` to its `evidence`, set its `maturity` to `stable`, then run `python scripts/spec.py generate` and `python scripts/spec.py check`.
