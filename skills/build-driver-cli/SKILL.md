---
name: build-driver-cli
description: >-
  Builds a new driver tool by the tool-driver-cli-spec specification: a command-line tool,
  such as kicad-cli for KiCad, that lets an AI Agent operate a desktop application or a device.
  Guides the eight onboarding steps (capability survey, modes, project from the template,
  domain commands, adapter, conformance suites and behavior matrices, Skills, knowledge and
  evaluation questions, npm release), and reviews an existing driver tool against the
  specification, listing every clause it does not meet.
  按 tool-driver-cli-spec 规范开发新的驱动工具（让 AI Agent 操作桌面软件或设备的命令行工具，比如 KiCad 的 kicad-cli）：
  能力调查、选模式、从模板生成项目、注册领域命令、写适配层、跑一致性测试和行为矩阵、写 Skill、知识和评测题、发布到 npm；
  也按规范审查已有的驱动工具，列出不符合的条款。
  Not for using a driver tool to do work in an application; use that tool's own Skill, such as kicad-cli.
  不负责用驱动工具在软件里干活，那要用该工具自己的 Skill，比如 kicad-cli。
metadata:
  version: 1.1.0
---

# build-driver-cli

A driver tool lets an Agent operate a desktop application or a device. A person sets the scope, the Agent does the work, and the tool makes every step correct and honestly reported. The specification decides everything tools share; you write only the domain commands, the adapter, the Skills, the knowledge entries and the evaluation questions. This Skill walks through the eight onboarding steps of DREPO-062, then reviews the tool.

Judge every choice the specification leaves open by its goals. Fast: few calls, small structured output, long checks as separate commands. Accurate: every change on a named object, read back, and its result shows what it made, such as where a track ended and what it connects to, so the Agent checks it as data and never by recognizing a screenshot (DCLI-068). Steady: changed, saved and verified reported separately, and every error says what was sent and what to do next. Where a goal and a clause seem to disagree, the clause wins: stop and tell the person.

`<tool>` is the command name (`kicad-cli`), `<pkg>` its source package (`kicad_cli`), `<PREFIX>` its environment prefix (`KICAD_CLI`) (DREPO-053).

## Get the release

Use the release whose version is this Skill's `metadata.version`, unless the person names another. In a new empty folder outside any project, with `<version>` filled in:

```bash
curl -fLO https://github.com/fatecannotbealtered/tool-driver-cli-spec/releases/download/v<version>/tool-driver-cli-spec-<version>.zip
curl -fLO https://github.com/fatecannotbealtered/tool-driver-cli-spec/releases/download/v<version>/tool-driver-cli-spec-<version>.sha256
python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" tool-driver-cli-spec-<version>.zip
```

The printed digest must equal the first word of the `.sha256` file. If it does not, stop: delete both files, unpack nothing and tell the person. Otherwise `python -m zipfile -e tool-driver-cli-spec-<version>.zip .` unpacks the release into `tool-driver-cli-spec-<version>/`, called `<spec>` below: the five specifications in `spec/`, the contract, the template, the scripts and worked evaluation questions in `conformance/eval/`.

Create a virtual environment outside the new project with Python 3.12 or later and run `python -m pip install --require-hashes --no-deps -r <spec>/template/requirements-dev.txt`; the scripts need it, and it is also the project's `requirements-dev.txt`. Inside a generated project, `python scripts/spec.py <action>` runs the scripts of the pinned release and checks the SHA-256 of its download itself. Set `TOOL_DRIVER_SPEC=<spec>` to make it use the release you already checked instead of downloading it again: offline, behind a proxy, or before the release is published. Read clauses in the project's `.agent/`; before step 3, in `<spec>/spec/`.

## Rules that hold throughout

- The specification decides. Before each step, read the clauses it names. Where a clause fixes a name, value, text, file or flow, use it exactly; never invent a flag, error code, verb, section, label or step. When a table and `contract/driver-contract.json` disagree, the contract wins.
- Once the project exists, obey its `AGENTS.md`: never edit pinned copies or generated content, never skip or weaken a conformance test. Never reimplement what the driver runtime does (DREPO-032). Fake host results are never evidence (DVER-021); never mark a command above its evidence (DVER-040).
- The real application runs only on targets listed under Authorized Targets in `docs/E2E.md` (DVER-050); when the list is empty, ask the person for a work folder. Add a target only when the person's own message grants it, and tell them the line you added. Inside the listed targets, go ahead without asking: make practice copies, start the instances you test on and close only those, and write your own scope files (DSEC-011).
- Publishing, tagging and pushing need the person's explicit approval. Work on a branch; never commit secrets, license files or project files the person may not share.
- Name other tools, such as lark-cli, and follow their own help; never write their commands into the tool, its Skills or its output (DSKL-110).
- Where the specification leaves a choice to the person, such as the modes or the names, ask; do not choose for them.

## The eight steps

Each step names the clauses to read, what to fill, the check and when it is done. Once the project exists, its `CONTRIBUTING.md` explains every command, the behavior matrices, evidence and evaluation, and its `docs/E2E.md` the live runs; read them there rather than guessing.

### 1 Survey

- Read: DREPO-015, DREPO-060, DREPO-052, DCLI-262, DSKL-126.
- Fill: a draft with the sections and tables of `<spec>/template/docs/APPLICATION.md`, from the application's manuals, API documentation and SDK. Every capability gets a `CAP-nnn` row with its interface and one disposition of `project.capability_dispositions` in `<spec>/contract/driver-contract.json`: `deferred` while it is worth offering but no command offers it yet (step 4 makes it `provided`), `excluded` when it is unsafe or cannot be automated reliably, `unknown` when the documents leave it open. Every risk and limit gets a line under Risks. Nothing is authorized yet: do not drive the application; ask the person what the documents leave open.
- Check: the person reads the draft. After step 3, `python scripts/spec.py check` reports nothing for DREPO-015, DREPO-052 or DREPO-060.
- Done when every section holds facts with their source and every capability has an ID and a disposition.

### 2 Choose modes

- Read: DCLI-201, DCLI-260, DCLI-262, DREPO-052.
- Fill: a proposal with reasons: the modes (`file`, `session`, `device`, combinable), whether a host component is needed (an interface that works only inside the application's process or on its main thread), and the platforms the application runs on.
- Check: the person decides and confirms.
- Done when you have the values of `--modes`, `--host-component` and `--platforms` for step 3.

### 3 Generate the project

- Read: DREPO-001 to DREPO-004, DREPO-019, DREPO-030 to DREPO-035, DREPO-053.
- Fill: the person decides `--tool`, `--package` (under an npm scope they own), `--repo` and `--author`. Run `python <spec>/scripts/instantiate.py <new project folder> --tool <tool> --package <package> --application <name> --versions "<range>" --modes <modes>`, adding `--host-component`, `--platforms`, `--repo` and `--author`. In the project, run `git init`, commit the generated files and continue on a branch. Move the survey into `docs/APPLICATION.md` and `docs/APPLICATION_zh.md`. Fill each `{{fill: ...}}` text when its step comes; each says what to write.
- Check: `python scripts/spec.py check --json`.
- Done when it lists only DREPO-019 placeholders and the DCLI-029 note that no domain command is registered.

### 4 Register commands

- Read: DCLI-020 to DCLI-029, DCLI-051, DCLI-052, DCLI-064, DCLI-065, DCLI-068, DCLI-080 to DCLI-084, DCLI-212, DSEC-018, DSEC-021. How-to: [references/commands-and-matrices.md](references/commands-and-matrices.md).
- Fill: one registration per command in `<pkg>/commands/__init__.py`; set the capabilities it offers to `provided` in both survey files. Mark work that can take longer than a call `long`, and list in `long_commands` (in `<pkg>/__init__.py`) the standard writes the application takes over a minute for, such as `doc open` of a large project (DCLI-065); when the application has several kinds of document, list them in `doc_kinds` in `<pkg>/__init__.py` and on each command the kinds it works on, set `verify_after_save` when the application shows a change correctly only after a save, use a `json` flag for a structured value such as a pad table, and give each write an output schema that shows what the change made (DCLI-068). New documents come from `doc create`, never a domain command. Then run `python scripts/spec.py generate`.
- Check: `python -m <pkg> reference` starts and lists each command, and `reference --command <path>` shows its tier; `python scripts/spec.py check` reports nothing but DREPO-019 placeholders. The person reviews the command list: the names, and the effects and `irreversible` marks, which set the confirmation tiers.
- Done when every `provided` capability has its command, every command offers a surveyed capability, and the person agreed to the list.

### 5 Implement the adapter

- Read: DCLI-028, DCLI-057, DCLI-063, DCLI-066, DCLI-203 to DCLI-205, DCLI-240, DCLI-260 to DCLI-262, DCLI-275; in session mode without a host component, also DCLI-277.
- Fill: in `<pkg>/adapter/__init__.py`, one method per capability the chosen modes require, plus the optional ones your workflows need: in session mode, `open_doc` and `close_doc`, which live runs and the evaluation use. Each takes the request of `<spec>/contract/schemas/adapter.schema.json` and returns its reply. `read`, `preview`, `apply` and `read_back` receive `{command, inputs, ...}`, with values already in standard units such as `x_mm`, and dispatch on `command`. A failure raises `AdapterError(code, message, dispatch_state=...)` with a code of DCLI-279, such as `E_AMBIGUOUS` with `candidates` for two parts with one reference; an error the adapter recognizes names its knowledge entries with `knowledge=[...]` (revisit after step 7 writes them). The preview lists the direct effects it can foresee, and names in `tier_raises` the registered conditions that hold, including `target_exists` when an `artifact` command would overwrite a file that no `output` flag names. `self.store` keeps state between calls. Report facts only; the runtime judges success. When the application writes a file under another name than the call gave, such as `part.prt.1` for `part.prt`, list it in `files` with `requested_path` set to the path the call gave. `sessions` looks for the application's dialogs on every call, also while the application answers. A dialog your own running work answers itself, such as an export's options dialog, leaves the session `busy`: mark such work in `self.store` with its process ID and the dialog titles it expects, and ignore a mark whose process has ended; any other dialog is `blocked`. In the CLI's process, `sessions` and `documents` keep the limits of DCLI-205 themselves: ask each instance in its own thread and stop waiting for it after 2 seconds; `sessions` returns within 2.5 seconds in all. With a host component, see [references/host-component.md](references/host-component.md).
- Check: on the machine with the application, the `application` check of `python -m <pkg> doctor` passes, so `probe` finds it; `python -m ruff check .` and `python -m unittest discover -s tests` pass, with unit tests for the adapter.
- Done when every capability the DCLI-260 table requires for the modes is implemented and `probe` finds the application.

### 6 Test

- Read: DVER-001, DVER-002, DVER-030, DVER-031, DVER-040 to DVER-043, DVER-050, DSEC-034. How-to: [references/commands-and-matrices.md](references/commands-and-matrices.md).
- Fill: every file in `tests/matrix/`, one per domain command and per standard command whose adapter capabilities the tool implements (`generate` writes the first version; other standard commands need none); the tool's own tests in `tests/`.
- Check: `python scripts/spec.py suites`. Then the live runs of `docs/E2E.md`, on the targets listed under Authorized Targets; the runner writes the scope file of each run. With a host component, first run `plugin install` with the live-run state directory, under a scope file of your own (see host-component.md). Run `python scripts/spec.py matrix --command "<path>" --set doc=<file>`, one `--set` per placeholder. A row that needs a prepared situation, such as `dialog`, runs alone with `--row dialog` once it is prepared, by you in an instance you started or by the person; `dialog` and `read_back_mismatch` are never `unrunnable`. `--row read_back_mismatch` makes the tool wait before its read-back while the person, or a script given with `--tamper`, changes the result. A command with `doc_kinds` runs its `normal` row once per kind, with `--kind`. Commit the live records. A run counts until the command's registration or the adapter's code changes; after such a change, `python scripts/spec.py check` names the rows to run again.
- Done when both suites pass, every matrix row that applies has passed live or is marked `unrunnable` with a reason, and each command's `maturity` matches its evidence.

### 7 Write Skills and knowledge

- Read: DSKL-001 to DSKL-011, DSKL-020 to DSKL-028, DSKL-100, DSKL-101, DSKL-120, DSKL-124, DSKL-126, DSKL-040 to DSKL-044.
- Fill: the `{{fill: ...}}` texts and the routing table of `skills/<tool>/SKILL.md`; playbooks for multi-step domain tasks go in a `## Playbooks` section of the entry Skill while it is the only Skill, and flows that cross domain Skills stay there after a split. Skills check changes with results and read commands, never with screenshots (DSKL-011). Never change the write recipe, the STOP checkpoints, the driver playbooks or the report. Split into domain Skills only past 150 lines: [references/domain-skills.md](references/domain-skills.md). Turn the survey's operating notes, limits and troubleshooting into `knowledge/` entries, then point the matching adapter errors at them: [references/knowledge-entries.md](references/knowledge-entries.md). Before marking a command `stable`, write `tests/eval/` questions: [references/evaluation.md](references/evaluation.md).
- Check: `python scripts/spec.py generate`, `python scripts/spec.py check`, `python scripts/spec.py eval --check --fake-host`; on the real application, `python scripts/spec.py eval --workspace-root <folder>` in a folder the person authorized. That run needs Claude Code on PATH, whichever Agent builds the tool, and uses model credits. The person reviews the Skills.
- Done when the check passes, the person agreed to the Skills, and every `stable` command has a current, passing evaluation report.

### 8 Publish

- Read: DREPO-040 to DREPO-043, DREPO-050 to DREPO-054, DSEC-070 to DSEC-073.
- Fill: the platform packages in `package.json`, one per system and CPU the survey allows; the new version in `package.json`, its platform packages, `pyproject.toml` and every Skill's `metadata.version`; the `CHANGELOG.md` section `[X.Y.Z] - YYYY-MM-DD`.
- Check: the four commands of rule 5 in the project's `AGENTS.md`, then `python scripts/build.py`, `python scripts/pack.py` and `python scripts/smoke.py` (`--fake-host` without the application). The release workflow runs platform delivery on every platform package.
- Release: after the person approves the merge, the person pushes the tag, or you do after their explicit approval: `git tag -a vX.Y.Z -m "vX.Y.Z"`, then `git push origin vX.Y.Z`. The first release publishes with the `NPM_TOKEN` secret the person adds to the repository; trusted publishing is set up after it. Only the release workflow publishes.
- Done when the release workflow has published every package with provenance.

## Review a tool

Run it before you ask for the release in step 8, and whenever you are asked to review a driver tool. Change nothing while you review.

1. In the project, run `python scripts/spec.py check` and `python scripts/spec.py suites`. Each check problem names its clause. Each failed test names its ID; the Checks column of DVER-003 and DVER-010 gives its clauses.
2. List the clauses that a person checks. Their Check line contains 👀; where it also has 🤖, review only the part after 👀:

   ```bash
   python -X utf8 -c "import pathlib; [print(b.split()[0], '|', l) for f in sorted(pathlib.Path('.agent').glob('DRIVER-*-SPEC.md')) for b in f.read_text(encoding='utf-8').split('\n### ')[1:] for l in b.splitlines() if l.startswith('Check:') and '👀' in l]"
   ```

3. For each of them, read the clause in `.agent/` and compare it with the project: the files, the registrations, the Skills, the workflows and the output of `python -m <pkg> reference --all --output <file>`.
4. Report one table with every clause from steps 1 and 3. Name a clause you cannot judge, such as one that needs the real application, with the reason. Clauses about the specification repository or the runtime itself, such as DVER-011, DVER-022 and DSKL-041, are `n/a`, with the reason.

| Clause | Conforms | Evidence | Fix |
|---|---|---|---|
| DSKL-021 | no | `skills/kicad-io/` is cut by code module | Split by the tasks users name, such as `kicad-schematic` |
| DREPO-050 | yes | README installs only with npm | - |

## Move to a new specification release

Run `python scripts/spec.py sync <version>`; it replaces every pinned copy, writes the generated content and lists the other template files that changed since the release pinned before: compare the project's copies with them and carry over what applies. Then read the CHANGELOG of the new release, run `python scripts/spec.py check` and `python scripts/spec.py suites`, and fix what they report.
