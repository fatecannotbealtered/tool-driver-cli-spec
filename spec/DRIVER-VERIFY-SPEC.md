# DRIVER-VERIFY-SPEC

English | [中文](DRIVER-VERIFY-SPEC_zh.md)

> Version 1.0.0-rc.1 · Clauses DVER-001 to DVER-051

## How to Read

This specification says how a driver tool proves that it works. Each rule is a clause with a fixed ID, such as `DVER-010`. A clause ends with two lines. `Why:` gives the reason. `Check:` says how the rule is checked: 🤖 means a test or a script checks it, 👀 means a person checks it in review.

The normative words mean:

- MUST and MUST NOT: required. A tool that breaks the rule does not conform.
- SHOULD and SHOULD NOT: the expected choice. Depart from it only for a reason you can state.
- MAY: allowed, not required.

The machine contract `contract/driver-contract.json` holds the test IDs, the maturity levels and the evidence kinds as data. Tables that repeat these values carry a contract marker. When such a table and the contract disagree, the contract wins.

## Scope

This specification applies to every driver tool and to the driver runtime. It covers:

- the two conformance suites every tool runs: the general suite (G and R tests) and the driver suite (D tests)
- the fake host, which stands in for the application in those suites
- the behavior matrix that every command keeps
- the maturity level and the evidence that every command declares
- live acceptance on the real application

It does not repeat the rules being tested. Each test names the clauses it checks.

One idea runs through this specification: only what is tested counts. Not run is not passed. Simulated is not real. Not verified is not success.

## Terms

| Term | Meaning |
|---|---|
| driver runtime | The shared code every tool copies unchanged. It implements the built-in and standard commands, the write flow and receipts |
| domain command | A command the tool author registers, as opposed to the built-in and standard commands of the runtime |
| write command | A command whose declared effect is anything other than `observe` (DCLI-051) |
| conformance test | One test of the two suites in this specification: general (G00 to G10, R01 to R06) and driver (D01 to D23) |
| write sample | The arguments of one valid call to a write command, used by the general suite |
| fake host | A small program from the tool-driver-cli-spec repository that stands in for the application in tests (DVER-020) |
| behavior matrix | A table per domain or standard command: one row per situation, with expected result, actual result and evidence (DVER-030) |
| maturity | How far a command is proven: `draft`, `experimental`, `verified` or `stable` (DVER-040) |
| evidence | A file that shows a maturity claim is true. An evidence reference points to it (DVER-041) |
| simulated evidence | Results obtained with the fake host |
| live run | Running the tool against the real application, on authorized targets |
| live record | The JSON record of one live run, kept in `docs/evidence/` (DVER-042) |
| eval report | The JSON file `docs/evidence/eval-*.json` that records a run of the tool's evaluation questions with Agents (DSKL-043) |
| live acceptance | Checking the tool on the real application, as described in `docs/E2E.md` |
| authorized target | An application instance, file, folder or device that a person allows live runs to use |

## Runtime and Tool Responsibilities

| Area | The runtime and the tool-driver-cli-spec repository provide | The tool author does |
|---|---|---|
| Conformance suites | Both suites, which run any tool from the command line | Runs both suites in CI on every merge and release, on every shipped platform |
| Write samples | The G tests that use the samples; samples for built-in and standard commands | One valid sample for each domain write command |
| Fake host | The fake host, with the in-process adapter interface and the host protocol | Nothing to write |
| Behavior matrix | The fixed list of rows | One matrix per command, with expected result, actual result and evidence |
| Maturity and evidence | Maturity and evidence shown by `reference`; `check_project` compares levels with evidence | Declares the level and the evidence of each command and keeps the evidence current |
| Live acceptance | The live record schema in the contract | Runs on authorized targets; writes `docs/E2E.md` and the records in `docs/evidence/` |

## General Conformance

### DVER-001 Conformance suites

The driver runtime comes with two conformance suites: the general suite (DVER-003) and the driver suite (DVER-010). Every tool MUST run both suites on every merge and every release, on every platform it ships (DREPO-041). A tool MUST NOT skip, weaken or edit any test, and MUST NOT mark a test as an expected failure. A test that applies (DVER-010) but did not run counts as failed. The suites MUST NOT need the real application, a license or a device: the fake host stands in for them (DVER-020).

Why: The suites check the rules every Agent relies on. A skipped test hides a broken rule behind a green build.
Check: 👀 Review of the CI workflow: both suites run on every shipped platform, and no test is skipped or changed.

### DVER-002 Write samples

The tool MUST supply, in `tests/`, one valid sample for each domain write command. A sample is the arguments of one call that the command accepts and that, run with `--dry-run`, returns a valid preview (G02). The general suite runs the samples in its write tests. Samples for built-in and standard commands come with the suites. A command at maturity `draft` still needs its sample (DVER-040).

Why: The suite cannot guess valid arguments for a domain command. Without a sample, the confirmation tests cannot run on it.
Check: 🤖 General conformance test G00.

### DVER-003 General conformance tests

The general suite MUST contain the tests below, and every tool MUST pass all of them. In the pass conditions, "nothing written" means the documents, files and devices the test uses are unchanged afterwards. The last column names the clauses each test checks.

<!-- contract:conformance_general -->
| ID | What the test does | Pass condition | Checks |
|---|---|---|---|
| `G00` | Looks up the sample of every write command | Every write command has a sample | DVER-002 |
| `G01` | Runs the sample of each two-step command with neither `--dry-run` nor `--confirm` | Exit code 5; `details` hold `preview` and `confirm_token`; nothing written | DCLI-014, DCLI-051, DCLI-053, DSEC-003 |
| `G02` | Runs each sample with `--dry-run` | Exit code 0; the preview is valid; nothing written | DCLI-054 |
| `G03` | Dry-runs a sample, then confirms with one argument changed, one removed or one added | `E_CONFLICT` with `token_mismatch`, naming the argument; nothing written | DCLI-055, DCLI-056 |
| `G04` | Confirms with the same arguments, then confirms again with the same token | The first call succeeds; the second gets `E_CONFLICT` with `token_used`; the change is written once | DCLI-055, DCLI-056 |
| `G05` | Confirms with tampered tokens | Every attempt is refused; nothing written | DCLI-055 |
| `G06` | Runs the sample of a two-step command with `--format text` and no token | Exit code 5; nothing written | DCLI-014, DCLI-053 |
| `G07` | Dry-runs and confirms with no scope file | `E_FORBIDDEN` with `details.scope`; nothing written | DCLI-050, DSEC-015 |
| `G08` | Damages the signing key; separately, makes `operations/` in the state directory unwritable | `E_IO`; nothing written | DCLI-059, DSEC-033 |
| `G09` | Runs each dangerous command without `--dangerous` | Exit code 5; nothing written | DCLI-014, DCLI-051, DCLI-052, DCLI-053, DSEC-003 |
| `G10` | Changes the scope file between the dry run and the confirm | `E_CONFLICT` with `scope_changed`; nothing written | DCLI-056, DSEC-015 |
| `R01` | Validates `reference`, `reference --index` and `reference --command` | Valid structure; the index is at most 8000 characters and one command at most 6000; every example parses | DCLI-030, DCLI-031, DCLI-051, DCLI-201 |
| `R02` | Walks the command tree | Follows DCLI-020 to DCLI-024; every command has a summary, an output schema and examples | DCLI-020, DCLI-021, DCLI-022, DCLI-024, DCLI-031 |
| `R03` | Sends an unknown command, an unknown flag and an extra argument | `E_USAGE` with `problem` and the suggested correct form | DCLI-011, DCLI-012, DCLI-013 |
| `R04` | Validates every envelope the suites see | Matches the contract; keys are snake_case; `*_at` values are UTC; within the size limits | DCLI-001, DCLI-003, DCLI-004, DCLI-005, DCLI-006, DCLI-008, DCLI-010, DCLI-011, DCLI-012, DCLI-013, DCLI-014, DCLI-061 |
| `R05` | Runs `context`, `doctor` and `operation list` on an empty state directory | Valid output; `doctor` lists every fixed check | DCLI-030, DCLI-032, DCLI-033, DCLI-035, DSEC-016, DSKL-125 |
| `R06` | Counts coverage after the tool's own tests | Every domain command and every standard command ran in the tool's own tests | DVER-004 |

Why: These tests cover the write safety and the self-description that all tools share, so an Agent can trust every tool in the same way.
Check: 🤖 General conformance tests G00 to G10 and R01 to R06.

### DVER-004 Every command is exercised

The tool's own tests MUST run every domain command and every driver standard command the tool offers (DCLI-200) at least once. After they finish, test R06 counts which of these commands ran and fails when one did not. Built-in commands (DCLI-030) contain no tool code; the runtime's unit tests cover them (DVER-022).

Why: A command that no test runs can break in any release without anyone noticing.
Check: 🤖 General conformance test R06.

## Driver Conformance

### DVER-010 Driver conformance tests

The driver suite MUST contain the tests below, and every tool MUST pass every test that applies to it. The contract lists, for each test, when it applies under `conformance.driver[].applies_when`, with values from `conformance.applies_when_values`. A test applies when any of its values holds:

- `always`: for every tool;
- `writes`: the tool has write commands;
- `dangerous`: the tool has a command that runs in the dangerous tier, at least in some cases (DCLI-051);
- `jobs`: the tool has long jobs;
- `session` or `device`: the tool supports that mode;
- `host_component`: the tool has a host component;
- `physical`: the tool has commands with the `physical` effect.

The runtime, not the tool author, decides from the command registration which tests apply. It reports a test that does not apply as not applicable, with its condition. The suite runs the CLI with the fake host in place of the application, so its results are simulated evidence (DVER-021). The last column names the clauses each test checks.

<!-- contract:conformance_driver -->
| ID | Scenario | Expected result | Checks |
|---|---|---|---|
| `D01` | Several instances; the command has no `--session` | `E_AMBIGUOUS` listing the candidates | DCLI-202 |
| `D02` | The instance reconnects or restarts after the dry run | The confirm is refused with `E_CONFLICT` `session_changed` | DCLI-056, DCLI-203 |
| `D03` | The document changes after the dry run | The confirm is refused with `E_CONFLICT` `document_changed` | DCLI-056, DCLI-210 |
| `D04` | The application is busy | `E_BUSY`, retryable, `dispatch_state` is `not_started` | DCLI-057, DCLI-204, DCLI-276 |
| `D05` | A dialog blocks the application | `E_HUMAN_REQUIRED` with a `resume` command | DCLI-066, DCLI-204 |
| `D06` | The connection drops after dispatch | `E_OUTCOME_UNKNOWN`; the target stays locked until `operation resolve` | DCLI-035, DCLI-060, DCLI-063, DCLI-275 |
| `D07` | A change is applied but cannot be read back | `E_VERIFY_INCOMPLETE` | DCLI-057, DCLI-062 |
| `D08` | The read-back differs from the request | `E_VERIFY_FAILED` | DCLI-057, DCLI-062 |
| `D09` | A change in session mode | Persistence is `unchanged` and `dirty` is `true`; after `doc save`, persistence is `saved` | DCLI-058, DCLI-061 |
| `D10` | Closing a document with unsaved changes | Refused; also refused with `--discard` but without `--dangerous` | DCLI-212 |
| `D11` | Cancelling a long job | `cancel_requested` is reported first; `cancelled` only after the application confirms it stopped | DCLI-220, DCLI-221 |
| `D12` | The host component on disk differs from the loaded version | The `plugin` check of `doctor` fails; write commands are refused with `E_HUMAN_REQUIRED`, action `restart_application` | DCLI-240, DSEC-053 |
| `D13` | A physical parameter without a declared unit | Rejected when the command is registered | DCLI-085 |
| `D14` | A physical effect without `--dangerous`, or with a scope that does not allow `physical` | Refused | DSEC-014, DSEC-060 |
| `D15` | A simulated device | Results are marked `simulated` | DCLI-230, DSEC-062 |
| `D16` | A direct change in session mode | Done in one call, with an operation record, read-back and a full receipt; refused like any write when there is no scope | DCLI-050, DCLI-052, DSEC-015 |
| `D17` | The scope sets `confirm` to `always` | A direct-tier command returns a preview and a token and does not run | DCLI-052, DSEC-013 |
| `D18` | A person edits the document in the application before save | The `doc save` preview lists both the tool's changes and the external ones | DCLI-058, DCLI-277 |
| `D19` | Registers a link that is not a Feishu link; then registers a Feishu link and reads it | The first returns `E_VALIDATION` and registers nothing. The second needs two-step confirmation; `knowledge get` returns the link and the reader; the link and the description are listed in `meta.untrusted`. No network request at any point | DSEC-021, DSEC-041, DSEC-042, DSKL-102, DSKL-104, DSKL-105, DSKL-107, DSKL-110, DSKL-122, DSKL-123 |
| `D20` | The host component's protocol major version differs from the CLI's | The handshake fails with `E_PROTOCOL`; no change is sent | DCLI-273, DCLI-280, DSEC-054 |
| `D21` | The host misses 3 heartbeats in a row | The session becomes `lost`; writes in flight are recorded as outcome unknown | DCLI-204, DCLI-278 |
| `D22` | One of two instances does not respond | `session list` returns both within 5 s; the silent one has `state` `busy` | DCLI-205 |
| `D23` | The device is in `emergency_stop` or `fault` when a command acts on it | `E_HUMAN_REQUIRED` with action `confirm_on_device`; `dispatch_state` is `not_started`; nothing is dispatched | DCLI-230, DSEC-061 |

Why: These are the failures specific to driving an application: two open projects, an unsaved change taken as done, a dialog that hangs the call, a lost connection after a write.
Check: 🤖 Driver conformance tests D01 to D23.

### DVER-011 Black-box testing

The suites MUST treat the CLI as a black box. They start it from the command line as a separate process, and judge only its exit code, the envelope on stdout and what the fake host received. They MUST NOT import the tool's code or call the runtime's functions directly. Each run MUST use a temporary state directory (DSEC-034). This keeps the suites independent of the implementation language: a runtime written in another language MUST pass the same suites unchanged (DCLI-263).

Why: An Agent sees only the command line. A test that looks inside would pass tools that fail Agents, and would tie the suites to one language.
Check: 👀 Review of the suite code: every test starts the CLI as a process.

## Fake Host

### DVER-020 Fake host

The tool-driver-cli-spec repository provides the fake host: a small program that stands in for the application in tests. It MUST offer both ways a tool reaches an application: the in-process adapter interface (DCLI-260) and the full host protocol (DCLI-270 to DCLI-280). It is the reference implementation of that protocol (DCLI-281). It MUST be able to simulate:

- several instances at once
- documents in memory, with unsaved changes
- dialogs, a busy main thread and disconnects
- a person editing a document in the application
- long jobs
- one simulated device, which can be put in each device state (DCLI-230)

Tests MUST be able to put the fake host into each of these situations and read its state, so they can see whether a change arrived and how often.

Why: The failures that matter most, such as a dialog or a lost connection, are rare and hard to cause on demand in a real application.
Check: 🤖 Driver conformance tests D01 to D23, which need each of these situations.

### DVER-021 Simulated evidence

Results obtained with the fake host prove only the runtime's mechanisms, such as scope checks, confirmation, operation records, locks and receipts. They count as simulated evidence. They MUST NOT be presented as results on the real application. A command or a support matrix entry backed only by simulated evidence MUST NOT be labeled `verified` (DREPO-022, DREPO-023).

Why: The fake host behaves the way this repository wrote it, not the way the application behaves. Mixing the two would claim support that was never shown.
Check: 🤖 `check_project`: nothing is marked `verified` without a `live:` record.

### DVER-022 Fake host in the specification repository's CI

The tool-driver-cli-spec repository MUST run the driver runtime, the project template, both conformance suites and the evaluation scenarios (DSKL-041) with the fake host in CI on Windows, macOS and Linux, on every merge and every release. The runtime's unit tests MUST run in the same CI, on the same three systems. Like the two conformance suites, they are a required check: a failure blocks the merge and the release. They cover the built-in commands (DVER-004) and every rule whose check line cites runtime unit tests.

Why: Every tool copies the runtime unchanged. A fault found here is fixed once instead of in every tool.
Check: 👀 Review of the tool-driver-cli-spec repository's CI workflow.

## Behavior Matrix

### DVER-030 Behavior matrix

Every domain command and every driver standard command the tool offers (DCLI-200) MUST have a behavior matrix in `tests/`. Built-in commands (DCLI-030) need none; the runtime's unit tests cover them (DVER-022). Each row is one situation and records the expected result, the actual result and the evidence (an evidence reference, DVER-041). The matrix MUST have these rows:

<!-- contract:behavior_matrix_rows -->
| Row | Group | Situation |
|---|---|---|
| `normal` Normal | General | A valid call that succeeds |
| `empty` Empty | General | A valid call with nothing to return |
| `invalid_input` Invalid input | General | Arguments that are malformed or out of range |
| `not_found` Not found | General | The named object, document, session or job does not exist |
| `ambiguous` Ambiguous | General | A name matches several objects or instances |
| `conflict` Conflict | General | A precondition fails, such as a locked target or a changed document |
| `no_scope` No scope | General | No scope file, or one that does not cover the call |
| `busy` Busy | Driver | The application's main thread is busy |
| `dialog` Dialog | Driver | A dialog blocks the application |
| `disconnect` Disconnect | Driver | The connection drops during the call |
| `unsaved` Unsaved | Driver | The document has unsaved changes |
| `read_back_mismatch` Read-back mismatch | Driver | The value read back differs from the request |

A row that cannot happen for the command MUST stay in the matrix and say why in the expected column. A row without an actual result and evidence has not been run, and a row that has not been run MUST NOT count as passed.

Why: Agents meet these situations every day. A command whose behavior in them is unknown fails at the worst moment.
Check: 👀 Review: every domain and standard command has a matrix with all twelve rows.

### DVER-031 Adapter behavior on real software

The fake host cannot show how the adapter behaves with the real application: whether it recognizes the application's real dialogs, and whether its read-back returns the values the application really holds. These MUST be checked by running the behavior matrix on the real application (DVER-050). A claim about them MUST cite live evidence. Simulated evidence MUST NOT be used for it.

Why: A fake dialog is whatever the test says it is. Only the real application shows whether the adapter sees its dialogs and reads its values correctly.
Check: 👀 Review: the Dialog and Read-back mismatch rows of every `verified` command cite `live:` evidence.

## Maturity and Evidence

### DVER-040 Maturity levels

Every command MUST declare a maturity level and the evidence references behind it. `reference` shows both (DCLI-031). A level MUST NOT be higher than its evidence supports. Built-in commands take the level the runtime declares, backed by the runtime unit tests (DVER-022). Each level needs the evidence of the level below it plus its own:

<!-- contract:maturity_levels -->
| Level | Meaning | Evidence needed |
|---|---|---|
| `draft` | Declared; the interface may still change | None; a write command still needs its sample (G00) |
| `experimental` | The behavior matrix passes on the fake host | `simulated:` references |
| `verified` | Also run on the real application, with a record | Plus a current `live:` record (DVER-043) |
| `stable` | Also passed evaluation, with no open severe defect | Plus a current `eval:` report (DSKL-043) |

When evidence stops counting, the level MUST drop to the highest level the remaining evidence supports. A severe defect is one that makes a command report success for a wrong result, change something outside its target or scope, or lose the user's data.

Why: Maturity tells an Agent and a person how far to trust a command. A level above its evidence is a false promise.
Check: 🤖 `check_project`: the level of every command in `reference` is backed by the evidence kinds that level needs.

### DVER-041 Evidence references

An evidence reference has the form `<kind>:<path>[#<anchor>]`. The `path` is relative to the root of the tool project and MUST name a file in the repository. The `anchor` is optional and names one part of that file, such as a behavior matrix row in a live record. The `kind` MUST be one of these:

<!-- contract:evidence_kinds -->
| Kind | What it shows | Where the file is |
|---|---|---|
| `simulated` | The command passed its tests with the fake host | A test or a behavior matrix in `tests/` |
| `live` | The command ran on the real application | A live record in `docs/evidence/` (DVER-042) |
| `eval` | Agents completed the evaluation questions with the tool's Skills | An evaluation report `docs/evidence/eval-*.json` for the questions in `tests/eval/` (DSKL-043) |

Example: `live:docs/evidence/2026-11-01-footprint-move.json#normal`.

Why: A reference that names a real file lets a script and a person check each claim instead of trusting it.
Check: 🤖 `check_project`: every reference parses, uses a listed kind and names an existing file.

### DVER-042 Live records

Each live run MUST leave one JSON record in `docs/evidence/` that follows the evidence schema of the contract. The record holds:

- `kind`: always `live`
- `tool`, `tool_version` and `commit`: the tool and the exact build that ran
- `application`: the name and version of the application
- `os`: the operating system
- `recorded_at`: the time of the run, in UTC
- `targets`: the authorized targets the run used (DVER-050)
- `runs`: one entry per command, with the command path, its arguments, the exit code and `result`

`result` is `pass` when the command behaved as expected, and `fail` otherwise. When an entry names a behavior matrix row in `matrix_row`, the expected result is the one in that row. An entry MAY add the printed envelope (`envelope`), its SHA-256 (`envelope_sha256`) and notes. Arguments that carry secrets MUST appear as `***` (DSEC-040).

```json
{
  "kind": "live",
  "tool": "kicad-cli",
  "tool_version": "1.4.2",
  "commit": "3f9c2ab",
  "application": {"name": "KiCad", "version": "10.0.1"},
  "os": "Windows 11 24H2 x64",
  "recorded_at": "2026-11-01T09:30:00Z",
  "targets": ["file:///D:/e2e/demo-board/"],
  "runs": [
    {
      "command": "footprint move",
      "arguments": ["--session", "kicad-1234", "--doc", "D:/e2e/demo-board/board.kicad_pcb", "--ref", "R1", "--x", "12.5mm", "--y", "30mm"],
      "exit": 0,
      "result": "pass",
      "matrix_row": "normal",
      "envelope_sha256": "090b93f6516be82d6d224af36e040f4997faff07f3cda65b9c973520bd833fc3"
    },
    {
      "command": "footprint move",
      "arguments": ["--session", "kicad-1234", "--doc", "D:/e2e/demo-board/board.kicad_pcb", "--ref", "R2", "--x", "15mm", "--y", "30mm"],
      "exit": 7,
      "result": "pass",
      "matrix_row": "busy",
      "notes": "Started during a design rule check; E_BUSY with dispatch_state not_started."
    }
  ]
}
```

Why: A record with versions, arguments and results lets anyone see what was run and run it again. A summary written from memory proves nothing.
Check: 🤖 `check_project` validates every record in `docs/evidence/` against the evidence schema.

### DVER-043 Current evidence

A live record counts as evidence only while its `tool_version` has the same major and minor version as the tool. An eval report counts by the same rule, using the tool version it names. Evidence from another major or minor version MUST NOT support a maturity level. For tool version 1.4.2, a record from 1.4.0 counts and a record from 1.3.9 does not. After a new minor or major version, a command stays `verified` only with a new live record, and `stable` only with a new live record and a new eval report (DVER-040).

Why: A minor version can change behavior. Evidence from an older version says little about the current one.
Check: 🤖 `check_project` compares the tool version in each record and report with the version in `package.json`.

## Live Acceptance

### DVER-050 Authorized targets only

Live runs MUST use only the application instances, files, folders and devices that a person has authorized and listed under Authorized Targets in `docs/E2E.md`. Only a person adds a target to that list. Live runs MUST NOT touch any other project, instance or device. The scope file for a live run SHOULD grant only these targets (DSEC-012), so the runtime refuses any write outside them.

Why: A live run makes real changes. On an unauthorized project or a production machine, a test can do real damage.
Check: 👀 Review: every entry in the `targets` of every record in `docs/evidence/` is listed under Authorized Targets.

### DVER-051 Acceptance document

Every tool MUST describe its live acceptance in `docs/E2E.md` and `docs/E2E_zh.md`, with the sections DREPO-017 sets, in that order. The document names the authorized targets (DVER-050), says how to run the behavior matrices on the real application (DVER-031), indexes the live records (DVER-042) and gives the result of the latest live run.

Why: A reviewer, or the next maintainer, needs one place that says what was run, where and when.
Check: 🤖 `check_project` checks that both files exist and that their sections are complete and in order.

## Checklist

- [ ] DVER-001 Conformance suites
- [ ] DVER-002 Write samples
- [ ] DVER-003 General conformance tests
- [ ] DVER-004 Every command is exercised
- [ ] DVER-010 Driver conformance tests
- [ ] DVER-011 Black-box testing
- [ ] DVER-020 Fake host
- [ ] DVER-021 Simulated evidence
- [ ] DVER-022 Fake host in the specification repository's CI
- [ ] DVER-030 Behavior matrix
- [ ] DVER-031 Adapter behavior on real software
- [ ] DVER-040 Maturity levels
- [ ] DVER-041 Evidence references
- [ ] DVER-042 Live records
- [ ] DVER-043 Current evidence
- [ ] DVER-050 Authorized targets only
- [ ] DVER-051 Acceptance document
