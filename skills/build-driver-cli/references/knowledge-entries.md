# Knowledge entries

Use this file in step 7, when you turn the survey's operating notes, limits and troubleshooting into builtin knowledge.

## Rules

- One entry is one Markdown file in `knowledge/`, named after its `id`, with the front matter of DSKL-120. The body is at most 6000 characters; split a longer entry (DSKL-121).
- Every entry has exactly one kind (DSKL-101). Only `rule` entries carry `severity` and `check`; only `resource` entries carry `location`, `version`, `units` and `license`.
- `id` is lowercase words joined by hyphens, unique across the tool. `tags` are written the same way. `applies_to` names the commands, object types, modes or application versions the entry is for; `knowledge list --applies-to` finds it by them.
- Write only facts you checked: in a manual chapter, a live record or a test you ran.
- Builtin knowledge holds only what the tool author may publish (DSKL-103). Team standards and company resource catalogs stay in the team's Feishu documents, which the user registers as team knowledge.
- At least one `guide` and one `troubleshooting` entry. Every risk and limit in the Risks section of `docs/APPLICATION.md` becomes an entry, or the survey says next to it why it has none (DSKL-126).
- Name each command's related entries in `related_knowledge` of its registration. When the adapter recognizes an error an entry explains, such as a known dialog, it raises `AdapterError(code, message, knowledge=["<id>"])`; a host component puts the IDs in `data.knowledge` of its error. The tool then lists them in `error.details.knowledge` and names `knowledge get` in `next_action` (DSKL-124, DCLI-279).

## guide

```markdown
---
id: kicad-save-leaves-edit-mode
title: Leave the property editor before saving
kind: guide
applies_to: [doc save, footprint update]
tags: [save, editor]
---

While the footprint property editor is open, KiCad ignores a save request.
Close the editor first, then run doc save.
```

## rule

```markdown
---
id: kicad-unique-references
title: Reference designators are unique on a board
kind: rule
applies_to: [footprint create, footprint update]
tags: [annotation]
severity: error
check: run footprint list and compare the id values
---

Two footprints on one board never share a reference designator, such as R1.
```

## resource

```markdown
---
id: kicad-standard-footprint-library
title: The KiCad standard footprint library
kind: resource
applies_to: [footprint create]
tags: [library, footprint]
location: the footprints folder of the KiCad install, such as C:/Program Files/KiCad/10.0/share/kicad/footprints
version: 10.0
units: mm
license: CC-BY-SA 4.0 with the KiCad library exception
---

Use it for standard packages. It fits KiCad 10.0 and later only.
```

## troubleshooting

```markdown
---
id: kicad-plugin-update-dialog
title: What to do when the plugin update dialog appears
kind: troubleshooting
applies_to: [doctor, session list]
tags: [dialog, startup]
---

At start-up KiCad may show "Plugin updates available". It blocks automation.
Commands return E_HUMAN_REQUIRED; ask the person to close the dialog, then run resume.
```

## concept

```markdown
---
id: kicad-symbol-and-footprint
title: How symbols and footprints relate
kind: concept
applies_to: [symbol get, footprint get]
tags: [object-model]
---

A symbol is a part in the schematic; a footprint is the same part on the board.
They share the reference designator, such as R1.
```

## Check

Run `python scripts/spec.py generate`, then `python scripts/spec.py check`. It checks the front matter, the kinds, unique IDs, the index, links inside entries, the body length, the two required kinds and every `related_knowledge` ID (DSKL-127).
