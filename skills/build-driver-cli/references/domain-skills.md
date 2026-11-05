# Domain Skills and rename stubs

Use this file in step 7, when the entry Skill `skills/<tool>/SKILL.md` would grow past 150 lines, or when you rename or merge a Skill.

## When to split

- Keep one Skill as long as you can (DSKL-020). Move how-to detail into `references/` of the same Skill first (DSKL-003).
- Split only when `SKILL.md` would still pass 150 lines. Split by the tasks users name, such as "draw the schematic" or "lay out the board", never by code modules. When a common task needs two Skills loaded together, merge them (DSKL-021).
- The entry Skill keeps everything shared: the install check, the error sentence, the write recipe, the STOP checkpoints, the driver playbooks, the report and the routing table (DSKL-022). Its fixed text stays exactly as the template wrote it.

## Domain Skill

A domain Skill lives in `skills/<product>-<area>/SKILL.md`. `<product>` is the tool name without `-cli`; `<area>` is a noun of the commands it owns, written in full (DSKL-023, DSKL-027). The directory holds only `SKILL.md` and `references/` (DSKL-032).

```markdown
---
name: kicad-schematic
description: >-
  Draws and edits KiCad schematics with kicad-cli: symbols, wires, labels and
  electrical rule checks. 画原理图、改原理图、连线、做电气规则检查。
  Not for board layout or fabrication files; use kicad-board for those.
  不负责布板和生产文件，这些请用 kicad-board。
metadata:
  version: 1.4.0
  commands: [symbol list, symbol create, wire create, label create, schematic check]
---

# kicad-schematic

Read the entry Skill `kicad-cli` first and follow its write recipe, STOP checkpoints and report. If it is not installed, stop and ask the user to reinstall the Skills of kicad-cli.

## Commands

<!-- driver:command-map:start -->
<!-- driver:command-map:end -->

## Knowledge

- Before drawing, run `kicad-cli knowledge list --applies-to symbol` and read the entries it returns.

## Playbooks

### Add a symbol and wire it

1. ...
```

Rules for the fields and the body (DSKL-002, DSKL-024 to DSKL-026):

- `name` is the directory name. `metadata.version` is the version in `package.json`.
- `metadata.commands` lists the command paths this Skill owns. Every command belongs to exactly one Skill; commands no domain Skill lists belong to the entry Skill. The entry Skill has no such field.
- The description says what the Skill covers, what it does not cover and which Skill covers that, in English and Chinese. No two Skills of the tool compete for the same request.
- The body starts with the instruction to read the entry Skill first, naming it; `check_project` checks that the first line names it (DSKL-024).
- The body holds only its command map, knowledge pointers and domain playbooks. Never repeat the write recipe, the STOP checkpoints, the driver playbooks or the report; never add error or exit code tables (DSKL-005); never copy knowledge content, only say which knowledge to look up (DSKL-100).
- Leave the command map empty between its two marker lines; `python scripts/spec.py generate` writes it (DSKL-006).

Then add a row to the routing table of the entry Skill:

```markdown
| Task | Skill |
|---|---|
| Draw or edit a schematic, check electrical rules | `kicad-schematic` |
| Every other KiCad task | `kicad-cli`, this Skill |
```

## Rename stub

When a Skill is renamed or merged into another, keep its old directory as a stub (DSKL-028). `update` replaces only the Skill directories already installed, so without a stub the old copy keeps teaching. A stub only says which Skill to read instead. It owns no commands: it names the Skill to read in `metadata.replaced_by`, has no `metadata.commands` (DSKL-026), and its command map stays empty (DSKL-006).

```markdown
---
name: kicad-footprint
description: >-
  Renamed: footprint tasks are now in kicad-board; read kicad-board instead.
  已改名：封装相关的任务请改用 kicad-board。
metadata:
  version: 1.5.0
  replaced_by: kicad-board
---

# kicad-footprint

This Skill was merged into `kicad-board`. Read the Skill `kicad-board` and follow it instead of this one.

<!-- driver:command-map:start -->
<!-- driver:command-map:end -->
```

## Check

Run `python scripts/spec.py generate`, then `python scripts/spec.py check`. It checks the directory names, the front matter, the versions, that each command has one owner, the line count, the links to `references/` and that no domain Skill repeats the write recipe or the STOP checkpoints.
