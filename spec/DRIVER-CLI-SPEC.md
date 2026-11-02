# DRIVER-CLI-SPEC

English | [中文](DRIVER-CLI-SPEC_zh.md)

> Version 1.0.0-rc.1 · Clauses DCLI-001 to DCLI-281

## How to Read

This specification sets how a driver tool behaves on the command line: what it prints, how it fails, how its commands are named, how it writes, how it updates itself and how it reaches the application it drives.

The rule words mean:

- MUST and MUST NOT: required. A tool that breaks the rule does not conform.
- SHOULD and SHOULD NOT: the expected behavior. Depart from it only for a reason you can state.
- MAY: allowed, not required.

Each clause has a stable ID such as DCLI-202, a title, the rule, a `Why:` line and a `Check:` line. 🤖 means a test or a script checks the clause; 👀 means a person checks it in review. G00 to G10 and R01 to R06 are general conformance tests; D01 to D23 are driver conformance tests. Other rules are referred to by clause ID only, such as DSEC-015.

A table marked `<!-- contract:NAME -->` repeats values from the machine contract, `contract/driver-contract.json`. When such a table and the contract disagree, the contract wins.

## Scope

This specification applies to driver tools: command-line tools that let AI Agents operate professional desktop applications, such as CAD, EDA and simulation software, and devices, such as machine tools and instruments. The Agent calls the tool. A person decides what the Agent may change, through the scope file.

It covers:

- the output envelope, errors and exit codes;
- command names, flags and target keys;
- built-in commands and driver standard commands;
- the write flow: confirmation tiers, previews, confirm tokens, read-back, receipts and operation records;
- self-update;
- units and coordinates;
- the driver model: modes, sessions, documents, long jobs, devices and host components;
- the adapter interface, the driver runtime and the host protocol.

It does not define what domain commands do, such as how to route a track; it only defines their names and shape. It does not cover tools that call cloud service APIs, multi-step workflow commands, or driving an application on another machine.

## Terms

| Term | Meaning |
|---|---|
| Agent | The AI that calls the tool on a person's behalf |
| driver tool | A command-line tool that lets an Agent operate a desktop application or a device |
| application | The desktop software the tool drives |
| instance, session | An instance is a running copy of the application. A session is the tool's handle on one instance and has a session ID |
| document | A file open in an instance, or, in file mode, a file the tool reads and writes directly |
| driver runtime | The shared code that implements the envelope, the built-in and standard commands, the write flow and self-update; every tool copies it unchanged |
| adapter (layer) | The tool author's code that implements the adapter capabilities (DCLI-260) for one application |
| host component | The part of a tool that is installed into the application and runs inside it, such as a plugin, an add-in or a script service |
| host protocol | The local protocol between the CLI and a host component (DCLI-270 to DCLI-281) |
| fake host | A small program that simulates applications, instances and a device for conformance tests |
| envelope | The one JSON object a command writes to stdout |
| effect | What kind of change a command makes, such as `observe`, `change` or `physical` (DCLI-051) |
| confirmation tier | How a write is confirmed: direct, two-step or dangerous (DCLI-052) |
| risk tier | T0, T1 or T2: how much harm a command can do (DSEC-001) |
| authorization scope, scope file | The effects and targets a person allows, written in the scope file (DSEC-010 to DSEC-017) |
| target key | The one way to write the identity of an object (DCLI-028) |
| dry run, preview | A run with `--dry-run` that changes nothing; it returns a preview of the change |
| confirm token | A signed, single-use token, returned with a preview, that lets the same write run once (DCLI-055) |
| confirm-time review | The checks the runtime repeats just before a write runs (DCLI-056) |
| dispatch | Sending a change to the application or the device |
| read-back | Reading the changed fields again after dispatch, to verify them |
| receipt | The report of a write, split into five outcome dimensions (DCLI-061) |
| operation record | The stored history of one write; its ID starts with `op_` (DCLI-059) |
| outcome unknown | A write that may or may not have taken effect (DCLI-063) |
| long job | Work that takes longer than one call should; the tool returns a job to poll (DCLI-065) |
| state directory | The per-user directory where the tool keeps keys, records, locks and caches (DSEC-030) |
| untrusted content | Text from documents, the application or other sources outside the tool; never treated as instructions (DSEC-020) |
| built-in command, standard command, domain command | Commands the runtime implements for every tool (DCLI-030); commands the runtime implements from adapter capabilities (DCLI-200); commands the tool author writes |
| conformance test | A test from the runtime's suites: general tests G00 to G10 and R01 to R06, driver tests D01 to D23 |
| maturity, evidence | How well a command is proven, and the records that prove it (DVER-040) |
| platform package, launcher, command entry | The npm package that holds the native program for one platform; the starter script in the main npm package; the file npm puts on PATH to start the tool |
| provenance | A signed statement that an npm package was built by the tool's release workflow |

## Runtime and Tool Responsibilities

| Area | The driver runtime provides | The tool author does |
|---|---|---|
| Output and errors | Envelope, error object, exit codes, list paging, size limits, mapping states to error codes | Domain result data; passes the application's own error text as `native_message`; declares which result fields hold untrusted content (DSEC-021) |
| Commands | Argument parsing, global, shared and target flags, target key normalization | Registers domain commands with noun, verb, effects, units, target kind, capability IDs (DREPO-061), maturity and evidence |
| Built-in commands | `reference`, `context`, `doctor`, `changelog`, `operation`, `update`, `--version`, `--help` | Supplies the npm package name and the CHANGELOG |
| Standard commands | `session`, `doc`, `job`, `device`, `knowledge` and `plugin` commands | Implements the adapter capabilities they call (DCLI-260) |
| Writes | Scope check, confirmation tiers, preview and token, confirm-time review, records and locks, receipt and `ok` derivation, batches, long-job polling | Implements `preview`, `apply` and `read_back`; supplies one valid sample per domain write command (DVER-002) |
| Units | Parsing units in parameters and converting them to standard units | Declares the unit of every physical parameter and output field; converts to the application's units inside the adapter |
| Self-update | `update`, update notices, command entries, Skill sync | Nothing beyond the npm package name |
| Host component | The CLI side of the host protocol; host-side libraries where provided | Writes the host component in a language the application supports |
| Tests | General and driver conformance suites, fake host | Behavior matrix and live acceptance on the real application |

## Output

### DCLI-001 One envelope on stdout

With the default `--format json`, a command MUST write exactly one JSON envelope to stdout, followed by one newline, and nothing else. Progress, warnings and diagnostics MUST go to stderr. When stderr is not a terminal, the tool MUST NOT write progress bars, animations or banners. `--quiet` MUST silence all stderr output except errors.

Why: The Agent parses stdout as one JSON document; one stray line breaks the parse and wastes the call.
Check: 🤖 General conformance test R04 validates every envelope the suites see.

### DCLI-002 Output formats

`--format` takes one of these values:

- `json`: the default, and the only format for Agents.
- `text`: for people. It MAY change between versions; Agents and scripts MUST NOT parse it.
- `raw`: only for commands that declare it, such as exporting a log or file content. The bytes MUST be written as they are.

`--json` MUST mean the same as `--format json`. JSON MUST be compact by default; `--pretty` indents it for people. A format the command does not support MUST return `E_USAGE`.

Why: One machine format lets an Agent read every tool the same way; a text form that may change is safe only if nobody parses it.
Check: 🤖 Runtime unit tests.

### DCLI-003 Envelope keys

A success envelope MUST have exactly the keys `ok`, `schema_version`, `data` and `meta`. An error envelope MUST have exactly the keys `ok`, `schema_version`, `error` and `meta`. A failed command MUST NOT return `data`. `schema_version` MUST be the major and minor version of this specification, as a string: `"1.0"` for every 1.0.x version.

A success:

```json
{"ok":true,"schema_version":"1.0","data":{"id":"doc_1","path":"D:/proj/board.kicad_pcb","session":"kicad-1234","revision":7,"dirty":true,"readonly":false,"state":"dirty"},"meta":{"duration_ms":38}}
```

An error:

```json
{"ok":false,"schema_version":"1.0","error":{"code":"E_BUSY","message":"KiCad is running a design rule check; nothing was sent.","retryable":true,"details":{"dispatch_state":"not_started","next_action":"Wait 5 s, then run the same command again.","retry_after_ms":5000}},"meta":{"duration_ms":120}}
```

Why: Fixed keys let the Agent check `ok` first and then read one known place for the result or the error.
Check: 🤖 General conformance test R04.

### DCLI-004 Meta

`meta` MUST hold only these keys:

- `duration_ms`: present in every envelope; the run time in whole milliseconds.
- `notices`: a list of `{type, severity, message}`, where `severity` is `info` or `warning`. The update notice (DCLI-079) is one example. Omitted when empty.
- `untrusted`: a list of JSON paths in the envelope that hold untrusted content (DSEC-021). Omitted when empty.

Why: The Agent finds timing, notices and untrusted markers in the same place in every tool.
Check: 🤖 General conformance test R04.

### DCLI-005 Names and values

- Every key MUST be snake_case, including the keys inside `data` and `details`.
- IDs MUST be strings.
- Times MUST be UTC in ISO 8601 with a `Z` suffix, under keys that end in `_at`. Dates without a time of day MUST be under keys that end in `_on`.
- Enum values MUST be lower snake_case.
- Keys of physical quantities carry a unit suffix, such as `x_mm` or `angle_deg`, as DCLI-081 requires.

Why: With one naming rule the Agent never guesses a key's spelling, a time zone or a unit.
Check: 🤖 General conformance test R04.

### DCLI-006 Lists

A command that returns a list MUST return `items`, `count` (the number of items in this page) and `has_more`. It MUST add `total` when the total is known, and `next_offset` when `has_more` is `true`. When nothing matches, it MUST return an empty `items` with `ok: true`, never `E_NOT_FOUND`.

Why: The Agent pages every list the same way and can tell "nothing matches" from "wrong target".
Check: 🤖 General conformance test R04 checks the list keys; the "empty" row of the behavior matrix (DVER-030) covers the empty case.

### DCLI-007 Default fields

Each list command MUST declare its default fields, chosen for the questions Agents most often ask about that object. `--fields a,b` MUST return only the named fields. `--fields all` MUST return every field.

Why: Short default answers save the Agent's context; `--fields` fetches more only when needed.
Check: 👀 Review of the default fields in `reference`.

### DCLI-008 Response size

Called with default arguments, a command MUST keep a success envelope within 8000 characters and an error envelope within 2000 characters, counting the whole envelope. Lists stay within the limits by paging (DCLI-006). A command whose result can be too large to fit, such as file content or a long log, MUST offer `--output <path>`: it writes the full result to that file, and the response holds only a summary and the file path.

Why: Every character the tool returns costs the Agent context; a fixed limit keeps each call cheap.
Check: 🤖 General conformance test R04 checks the size limits.

## Errors

### DCLI-010 Error object

`error` MUST have exactly the keys `code`, `message`, `retryable` and `details`.

- `message` is one or two sentences written for the model: what happened and what changed.
- `retryable: true` MUST mean that nothing changed and the same call can be repeated later. A write that is retried MUST start again at its confirmation tier (DCLI-052).

Why: The Agent picks its next step from `code` and `retryable`; the message only adds context.
Check: 🤖 General conformance test R04.

### DCLI-011 Dispatch state and next action

`details` MUST always hold these two fields:

- `dispatch_state`: whether the change request reached the application or the device. `not_started` means it was not sent, `dispatched` means it was sent, `unknown` means the tool cannot tell. A read command MUST always report `not_started`.
- `next_action`: one sentence that tells the Agent what to do next. When an exact command exists, it MUST be in backticks.

Why: After a failure the Agent's first question is whether anything was sent, and the second is what to run next.
Check: 🤖 General conformance tests R03 and R04.

### DCLI-012 Fixed details fields

These codes and cases MUST carry these fields in `details`:

| Code or case | Field | Content |
|---|---|---|
| `E_USAGE` | `problem`, `parameter` | What is wrong, and with which parameter |
| `E_AMBIGUOUS` | `candidates` | The objects or instances that match; the Agent picks one |
| `E_CONFLICT` | `conflict` | Which precondition failed, one of the contract's `conflict_values` (DCLI-056, DCLI-206, DCLI-211, DCLI-212) |
| `E_FORBIDDEN` | `scope` | What the authorization scope is missing (DSEC-015) |
| `E_OUTCOME_UNKNOWN` | `lookup` | The exact command that finds out what happened (DCLI-063) |
| `E_BUSY` | `retry_after_ms` | How long to wait before trying again |
| `E_HUMAN_REQUIRED` | `action`, `resume` | What a person must do, and the command to run afterwards (DCLI-066) |
| `E_CONFIRMATION_REQUIRED` | `preview`, `confirm_token`, `expires_at` | The preview and a token that confirms it (DCLI-053) |
| A write whose receipt gives `ok: false` | `receipt` | The receipt of the write (DCLI-062) |
| A batch that does not fully succeed | `batch` | `{items, summary}` of the batch (DCLI-064) |
| The application reported an error | `native_message` | The application's own error text, listed in `meta.untrusted` |
| A knowledge entry explains the fix | `knowledge` | The IDs of the related knowledge entries (DSKL-124) |

Why: Fixed fields let the Agent act on an error without parsing the message.
Check: 🤖 General conformance test R03 checks `problem` on usage errors; R04 checks every envelope against the contract.

### DCLI-013 Error codes

A tool MUST use only the codes in this table and MUST NOT invent codes. A new code is first added to the contract, then to this table. Each code has a fixed exit code and a fixed `retryable` value.

<!-- contract:error_codes -->
| Code | Exit | Retryable | Meaning |
|---|---|---|---|
| `E_USAGE` | 2 | no | The command line is wrong: unknown command or flag, missing argument, or invalid value |
| `E_VALIDATION` | 2 | no | Well-formed, but the application or the tool rejects the content, such as a coordinate outside the board outline |
| `E_AMBIGUOUS` | 2 | no | A name matches several objects or instances; pick one from `candidates` |
| `E_UNSUPPORTED` | 2 | no | The request is valid, but this application version, mode or adapter cannot do it |
| `E_NOT_FOUND` | 3 | no | The object, document, session, job or operation does not exist |
| `E_AUTH` | 4 | no | Credentials that a networked device or service requires are missing, invalid or expired |
| `E_FORBIDDEN` | 4 | no | The authorization scope does not grant this operation; `scope` says what is missing |
| `E_CONFIG` | 4 | no | Local configuration is missing or invalid |
| `E_BACKEND_UNAVAILABLE` | 4 | no | The application is not installed, not running, not licensed or not reachable; nothing was dispatched |
| `E_CONFIRMATION_REQUIRED` | 5 | no | A dry run and confirmation, or `--dangerous`, is needed; nothing changed |
| `E_CONFLICT` | 6 | no | A precondition failed; `conflict` says which (DCLI-056) |
| `E_OUTCOME_UNKNOWN` | 6 | no | The change may have taken effect; run `lookup` before anything else |
| `E_NETWORK` | 7 | yes | The network is unreachable (self-update, networked devices); nothing was sent |
| `E_BUSY` | 7 | yes | The application's main thread or the target is busy; nothing was dispatched; retry after `retry_after_ms` |
| `E_TIMEOUT` | 8 | yes | A read timed out |
| `E_HUMAN_REQUIRED` | 9 | no | A person must act first (`action`), then the Agent runs `resume` (DCLI-066) |
| `E_PARTIAL` | 1 | no | The change took effect in part; read the receipt or the items, and do not resend the whole request |
| `E_VERIFY_FAILED` | 1 | no | The change took effect, but the read-back does not match the request |
| `E_VERIFY_INCOMPLETE` | 1 | no | The change took effect, but it could not be read back to verify it |
| `E_NATIVE_FAILURE` | 1 | no | The application refused the operation and left no lasting change |
| `E_PROTOCOL` | 1 | no | The CLI and the host component speak different protocol versions, or a reply cannot be parsed |
| `E_INTEGRITY` | 1 | no | The integrity or provenance check of an update package failed; do not retry |
| `E_IO` | 1 | no | A local file or the state directory failed; nothing was dispatched |
| `E_INTERRUPTED` | 130 | yes | Interrupted before any lasting effect |
| `E_UNKNOWN` | 1 | no | Internal error; read `message` and `details` |

Why: A fixed set of codes lets one Agent handle the errors of every tool the same way.
Check: 🤖 General conformance test R03 checks `E_USAGE`; R04 checks every code against the contract.

### DCLI-014 Exit codes

The exit code MUST follow from the error code as DCLI-013 sets it. A success MUST exit with 0.

<!-- contract:exit_codes -->
| Exit | Meaning | Agent's next step |
|---|---|---|
| `0` | Success | Continue |
| `1` | Partial effect, verification failed or incomplete, application error, protocol, integrity, local I/O, internal error | Read `error.details` |
| `2` | Usage, validation, ambiguity, unsupported | Fix the request; do not retry it unchanged |
| `3` | Not found | Find the right target |
| `4` | Credentials, authorization scope, configuration, application unavailable | Fix the environment or the scope, or ask the user |
| `5` | Confirmation required | Check the preview, then confirm with the token, or add `--dangerous` |
| `6` | Conflict or outcome unknown | Read the state again, or look up the operation |
| `7` | Network down or application busy | Wait, then retry |
| `8` | Timeout | Wait, then retry |
| `9` | Human required | Pass `action` on to the user; after they act, run `resume` |
| `130` | Interrupted | Check the state, then retry |

Why: A script or Agent that sees only the exit code still knows which kind of next step applies.
Check: 🤖 General conformance tests G01, G06 and G09 check exit code 5; R04 checks the other codes against the contract.

## Command Shape

### DCLI-020 Noun then verb

A domain command MUST have the form `noun verb`, such as `footprint move`. The command tree SHOULD be flat: `footprint move`, not `board footprint move`.

Why: With one fixed shape the Agent can guess a command from the object and the action.
Check: 🤖 General conformance test R02.

### DCLI-021 Paths and aliases

A command path MUST be either a group or a command, never both. An alias MUST be unique among its siblings; DCLI-024 lists the names an alias may not take.

Why: If one path can mean two things, the same words run different commands.
Check: 🤖 General conformance test R02.

### DCLI-022 Verbs

A domain command MUST take its verb from this table. It MUST NOT use synonyms such as `show`, `inspect`, `info` or `status`. The names and effects of built-in and standard commands follow DCLI-030 and DCLI-200.

<!-- contract:verbs -->
| Verb | Effect | Meaning |
|---|---|---|
| `list` | `observe` | Returns one page of objects; an empty list when nothing matches, never `E_NOT_FOUND` |
| `get` | `observe` | Returns one object; `E_NOT_FOUND` when it does not exist, `E_AMBIGUOUS` when a name matches several |
| `search` | `observe` | Finds objects that match `--query` and returns one page of results |
| `check` | `observe` | Checks rules or consistency, such as a design rule check, and changes nothing |
| `create` | `change` | Creates an object; the result carries the new object's `ref` |
| `update` | `change` | Changes only the given properties and leaves the rest; `E_USAGE` when no property is given |
| `delete` | `change` | Deletes; a missing target gives `E_NOT_FOUND` already at the preview |
| `move` | `change` | Moves or repositions |
| `import` | `change` | Imports an external file into the current document |
| `render` | `artifact` | Produces a picture, a PDF or another preview |
| `export` | `artifact` | Writes the content to a file in another format |
| `run` | — | Starts a long job and returns `job` (DCLI-065); each command declares its own effect |

Why: With a short fixed verb list the Agent never wonders whether to call `show`, `info` or `get`.
Check: 🤖 General conformance test R02.

### DCLI-023 Nouns

A noun MUST be a full English word. The one exception is an abbreviation that is common in the industry or in the application, such as `pcb` or `bom`, which MAY be used. Invented abbreviations such as `sch`, `fab` or `kb` MUST NOT be used. The noun SHOULD be the application's own term, as used in its user interface and manual, because users and Agents use those words.

Why: The Agent maps the user's words to commands; an invented abbreviation breaks that mapping.
Check: 👀 Review of the command tree.

### DCLI-024 Reserved names

These names belong to the built-in and standard commands: `reference`, `context`, `doctor`, `changelog`, `update`, `operation`, `help`, `version`, `session`, `doc`, `job`, `device`, `plugin`, `knowledge`. A domain command MUST NOT use one of them as its noun, and an alias MUST NOT equal one of them.

Why: The built-in and standard commands then sit at the same names in every tool.
Check: 🤖 General conformance test R02.

### DCLI-025 Global flags

These are the only global flags, with the same meaning in every tool. A tool MUST NOT add global flags. A command flag MUST NOT reuse the name of a global flag.

<!-- contract:global_flags -->
| Flag | Value | Meaning |
|---|---|---|
| `--format` | `json\|text\|raw` | Output format (DCLI-002) |
| `--json` | — | Same as `--format json` |
| `--pretty` | — | Indent the JSON |
| `--fields` | `<a,b\|all>` | Choose the fields to return (DCLI-007) |
| `--quiet` | — | Silence non-error output on stderr |
| `--dry-run` | — | Preview only; change nothing (DCLI-054) |
| `--confirm` | `<token>` | Run the write with the token from the dry run (DCLI-055) |
| `--dangerous` | — | Required for dangerous writes (DCLI-052) |

Why: The Agent learns these flags once and uses them in every tool.
Check: 🤖 Runtime unit tests (argument parsing).

### DCLI-026 Shared flags

When a command offers one of these functions, it MUST use this flag name and meaning.

<!-- contract:shared_flags -->
| Flag | Value | Meaning |
|---|---|---|
| `--limit` | `<n>` | Items per page. Help states the default and the maximum. Above the maximum the command returns `E_USAGE`; it never lowers the value silently |
| `--offset` | `<n>` | Start position of the page |
| `--query` | `<text>` | What `search` looks for |
| `--sort` | `<field>` | Field that orders a list |
| `--order` | `asc\|desc` | Direction of the order |
| `--state` | `<state>` | Filter by state; `all` means no filter |
| `--ids` | `<a,b,c>` | Act on several objects at once (DCLI-064) |
| `--continue-on-error` | `true\|false` | In a batch, whether to go on after an object fails (DCLI-064) |
| `--wait` | `<duration>` | Wait until the state changes or the time runs out, then return |
| `--output` | `<path>` | Write the result to a local file and return only a summary (DCLI-008) |
| `--input` | `<path\|->` | Read all parameters as one JSON object from a file or from stdin |

A duration MUST be written as `<n>ms`, `<n>s`, `<n>min` or `<n>h`. Physical quantities with units follow DCLI-082.

Why: The same function under the same flag in every tool means the Agent does not have to look it up again.
Check: 👀 Review of each command's flags in `reference`.

### DCLI-027 Target flags

A command on a session, document, device or job MUST select the object with these command-level flags, under the same names in every tool; for example `job get --job 7`. Operation records and knowledge entries are selected with `--id`.

<!-- contract:target_flags -->
| Flag | Object | Meaning |
|---|---|---|
| `--session` `<id>` | session | Selects the instance. It MAY be left out when exactly one instance runs; with several, leaving it out gives `E_AMBIGUOUS` (DCLI-202) |
| `--doc` `<path-or-id>` | document | Selects the document; in file mode it is the file path (DCLI-213) |
| `--device` `<id>` | device | Selects the device |
| `--job` `<id>` | job | Selects the long job |

Why: The Agent addresses the same kind of object the same way in every tool.
Check: 👀 Review of `reference`.

### DCLI-028 Target keys

A target key is the one way to write the identity of an object. Scope files, previews, receipts and operation records MUST use it. A target key is built from what a person can write down in advance, such as a file path or a device ID, because the scope file is written before any session ID exists.

<!-- contract:target_keys -->
| Kind | Format | Example |
|---|---|---|
| `file`: a whole file | `file:///<absolute-path>` | `file:///D:/proj/board.kicad_pcb` |
| `file_object`: an object in a file | `file:///<absolute-path>#<domain-path>` | `file:///D:/proj/board.kicad_pcb#/footprints/R1` |
| `untitled_document`: a new document not yet saved | `session:<session-id>/untitled:<n>` | `session:kicad-1234/untitled:1` |
| `device_part`: a part of a device | `device:<device-id>/<part>` | `device:cnc-01/axis-x` |

Matching MUST be by prefix: `file:///D:/proj/` in a scope file covers every object in every file under that folder. Before comparing, the runtime MUST normalize paths: absolute paths, one separator style, and case-insensitive comparison on Windows. A prefix MUST match only at a boundary, that is, when one of these holds: the key equals the prefix, the prefix ends with `/` or `#`, or the key continues with `/` or `#` right after the prefix. So `file:///D:/proj` covers `file:///D:/proj/board.kicad_pcb` but not `file:///D:/proj2/board.kicad_pcb`.

Why: A scope written before the work starts must still match the objects the Agent touches later.
Check: 🤖 Runtime unit tests (normalization and prefix matching).

## Built-in Commands

### DCLI-030 Built-in commands

The driver runtime implements these commands for every tool. A tool author MUST NOT write them. They MUST all be declared with the effect `observe`: the tool's own state (operation records, token key, update cache) and `update` do not count as effects.

<!-- contract:builtin_commands -->
| Command | Flags | Returns |
|---|---|---|
| `reference` | `--index`, `--command <path>` | The description of every command (DCLI-031) |
| `context` | — | Local state, without going online (DCLI-032) |
| `doctor` | — | Health checks (DCLI-033) |
| `changelog` | `--since <version>` | Release notes from the bundled CHANGELOG (DCLI-034) |
| `operation get` | `--id` | One operation record (DCLI-035) |
| `operation list` | `--state`, `--limit`, `--offset` | Operation records, newest first (DCLI-035) |
| `operation resolve` | `--id`, `--outcome`, `--evidence` | Records the real outcome of an outcome-unknown write (DCLI-035) |
| `update` | `--check`, `--target-version <v>`, `--allow-downgrade` | Self-update (DCLI-070) |

Why: Every tool answers the same questions with the same commands, and no author spends time rebuilding them.
Check: 🤖 General conformance tests R01 and R05.

### DCLI-031 reference

`reference` MUST describe every command: path, summary, flags, output schema, examples, effects, confirmation tier, maturity and evidence, modes, required adapter capabilities, possible error codes and related knowledge entries (DSKL-124). It MUST also return a `driver` block with the supported modes, the application and its supported version range. When a clause lets a tool depart from a default, `reference` MUST show each departure on the command it affects, with the ID of the clause that allows it, in the command's `departures` list.

- `reference --index` MUST return only the index, within 8000 characters.
- `reference --command <path>` MUST return one command, within 6000 characters.

Why: The Agent learns the whole tool, including the tier of each write, from one command and never guesses.
Check: 🤖 General conformance tests R01 and R02; 👀 review that every departure names its clause.

### DCLI-032 context

`context` MUST work offline and read only local state. It returns these keys:

<!-- contract:context_keys -->
| Key | Content |
|---|---|
| `tool` | Tool name |
| `version` | Tool version |
| `spec_version` | The version of this specification the tool follows |
| `state` | The state directory: its path, whether it is usable, and its actual access protection (DSEC-032) |
| `authorization` | The scope status (DSEC-016), scope ID, scope file path, allowed effects, whether dangerous writes are allowed, and the expiry time |
| `application` | The application's install location, version and license status |
| `sessions` | An overview of running instances |
| `components` | The CLI version, the host component version on disk, and the host component version each instance has loaded |
| `knowledge` | The number of builtin knowledge entries, and the team knowledge registrations: `id`, `title`, `kind`, `url` (DSKL-125) |

Why: One offline call shows the Agent where it stands before it touches anything.
Check: 🤖 General conformance test R05.

### DCLI-033 doctor

`doctor` MUST return `checks`, a list of `{check, status, message, fix}`, where `status` is `pass`, `warn` or `fail`. It MUST run these checks:

<!-- contract:doctor_checks -->
| Check | What it checks |
|---|---|
| `state_store` | The state directory is usable and protected (DSEC-032) |
| `authorization` | The status of the scope file (DSEC-016) |
| `version` | The CLI and the installed Skills have the same version (DSKL-031) |
| `update` | Whether a newer version exists (DCLI-079) |
| `application` | The application's install location and version |
| `license` | The application's license status |
| `plugin` | The host component version on disk equals the version each instance has loaded (DSEC-053) |
| `sessions` | The running instances and their states |
| `knowledge` | The knowledge index, entry format and registration file, and lark-cli on PATH when team knowledge is registered (DSKL-125) |

Why: One command finds the common setup problems and says how to fix each one.
Check: 🤖 General conformance test R05 checks that every fixed check is present.

### DCLI-034 changelog

`changelog` MUST read the CHANGELOG bundled with the tool and return `current_version` and `entries`. Each entry is `{version, date, changes}`, and `changes` MUST be grouped as `added`, `changed`, `deprecated`, `removed`, `fixed` and `security`. `changelog --since <version>` MUST return only entries newer than that version.

Why: After an update the Agent can see what changed without going online.
Check: 🤖 Runtime unit tests.

### DCLI-035 Operation commands

- `operation get --id <id>` MUST return one operation record.
- `operation list [--state <state>] [--limit <n>] [--offset <n>]` MUST list operation records, newest first.
- `operation resolve --id <id> --outcome applied|not_applied|partial --evidence <text>` records what really happened to an outcome-unknown write (DCLI-063). It MUST be refused unless the authorization scope covers the effects of that operation (DSEC-017).

Why: The Agent can always look back at what it did and settle a write whose outcome was unknown.
Check: 🤖 General conformance test R05 runs `operation list` on an empty state; driver conformance test D06 resolves an outcome-unknown write.

### DCLI-036 Version and help

Every tool MUST support `--version`, which reports the tool version, and `--help`, which shows usage. The runtime implements both.

Why: `update` relies on `<tool> --version` to confirm what is installed (DCLI-074).
Check: 🤖 Runtime unit tests.

## Writes

### DCLI-050 Write flow

Every write MUST go through these steps in this order, with an operation record kept throughout (DCLI-059):

1. Check the authorization scope (DSEC-014, DSEC-015).
2. Following the confirmation tier, return a dry run and wait for confirmation, or go on directly (DCLI-052).
3. Review the state just before running (DCLI-056).
4. Dispatch the change (DCLI-057).
5. Read back and verify (DCLI-057).
6. Return the receipt (DCLI-061).

Every tier MUST check the scope, keep an operation record, read back and return a receipt. The direct tier skips only the confirmation; it skips no safety check.

Why: One fixed flow makes every write in every tool equally careful and equally well reported.
Check: 🤖 General conformance test G07; driver conformance test D16.

### DCLI-051 Effects

Every command MUST declare its effects. The effect sets the default confirmation tier and the minimum risk tier:

<!-- contract:effects -->
| Effect | Meaning | Confirmation tier | Risk tier |
|---|---|---|---|
| `observe` | Read only | none | `T0` |
| `session` | Changes the application's running state but no file, such as starting an instance or opening a document | direct | `T1` |
| `change` | Changes objects in the application or in a file | direct in session mode; two-step in file and device mode | `T1` |
| `artifact` | Creates a new local file, such as an export or a save-as | direct; when the target file already exists, treated as `persist` | `T1` |
| `persist` | Overwrites an existing local file, such as a save | two-step | `T1` |
| `configure` | Changes settings, permissions or host components | two-step | `T2` |
| `deliver` | Hands content to people or systems outside, such as submitting to a PLM system or sending mail | dangerous | `T2` |
| `physical` | A physical action, such as moving a machine axis or switching power on | dangerous | `T2` |

- A command that declares several effects MUST take the strictest confirmation tier among them.
- Whatever the effect, these operations MUST be dangerous: an irreversible delete, discarding unsaved changes, and closing an instance the tool did not start.
- `job cancel` declares `change` but MUST be direct in every mode, because it only asks the application to stop a job the tool started (DCLI-221).

Why: The confirmation effort follows the risk: changes held in memory run at once, while writes to disk and to the outside world are confirmed.
Check: 🤖 General conformance test R01 checks that every command declares its effects; G01 and G09 check the tiers that follow from them.

### DCLI-052 Confirmation tiers

| Tier | What falls in it | How to call |
|---|---|---|
| direct | Changes held only in the application's memory, which can be discarded: document changes in session mode; opening instances and documents; creating a new file that overwrites nothing; cancelling a long job the tool started | One call runs it. The Agent MAY add `--dry-run` to see the preview first |
| two-step | Writes to disk and changes to the environment: saving and overwriting files; changes in file and device mode; changing settings; installing host components | `--dry-run` returns the preview and a token; then `--confirm <token>` runs it |
| dangerous | Physical actions; handing content to the outside; irreversible deletes; discarding unsaved changes; closing an instance the tool did not start | Two-step, with `--dangerous` on both calls; the scope MUST allow dangerous operations |

- The tier follows from the rules of DCLI-051 and is decided by the runtime. A tool MUST NOT lower it (DSEC-003).
- `reference` MUST show the tier of every write command, so the Agent never guesses.
- When the scope file sets `confirm: always`, every write MUST be two-step, direct-tier writes included (DSEC-013).

Example: moving 20 footprints and then saving takes 3 calls with a batch command (one direct batch move, then the save's dry run and confirm), and 22 calls when the footprints are moved one by one.

Why: In session mode a change stays in memory until it is saved, so confirming every small change only costs calls; the save and the outside-world effects are where confirmation protects.
Check: 🤖 General conformance test G09; driver conformance tests D16 and D17.

### DCLI-053 Confirmation required

When a two-step command runs with neither `--dry-run` nor `--confirm`, it MUST change nothing and return `E_CONFIRMATION_REQUIRED` with the preview, the confirm token and `expires_at` in `details`. The Agent checks the preview and confirms with that token; no separate dry run is needed. When a dangerous command runs without `--dangerous`, on either call, it MUST change nothing and return `E_CONFIRMATION_REQUIRED`. `--format text` MUST NOT change any of this.

Why: A forgotten flag costs no extra call and never causes a write.
Check: 🤖 General conformance tests G01, G06 and G09.

### DCLI-054 Dry run and preview

A dry run (`--dry-run`) MUST change nothing and return `data` = `{preview, confirm_token, expires_at, operation_id}`. When the write runs in the direct tier, a dry run MUST return only `{preview}`; under `confirm: always` it is two-step and returns the token too (DSEC-013). The preview holds:

<!-- contract:preview_fields -->
| Field | Content |
|---|---|
| `operation_id` | The ID of the planned operation |
| `command` | The command path |
| `action` | One sentence that says what will be done |
| `target` | `{key, kind, label}`; `key` is the target key (DCLI-028) |
| `effects` | The command's effects |
| `tier` | `direct`, `two_step` or `dangerous` |
| `changes` | One item per change: `{field, before, after, origin}`; `origin` is `tool` or `external` (DCLI-058) |
| `session` | `{id, generation}` |
| `document` | `{id, revision, dirty}` |
| `inputs` | Every input, echoed back; secrets show as `***` and files as `{sha256, bytes}` |
| `can_apply` | Whether the operation can run |
| `blocked_by` | When it cannot run, the reasons |

Why: The Agent and the person see exactly what will change, and on which object, before anything happens.
Check: 🤖 General conformance test G02.

### DCLI-055 Confirm token

The confirm token MUST bind these values. When any of them changes, the token MUST NOT be accepted.

<!-- contract:token_binds -->
| Bound value | Meaning |
|---|---|
| `command` | The command path |
| `inputs` | All inputs, after normalization |
| `target` | The target key |
| `session_id` | The session ID |
| `session_generation` | The session generation (DCLI-203) |
| `document_revision` | The document revision (DCLI-210) |
| `document_dirty` | Whether the document has unsaved changes |
| `plugin_version` | The host component version loaded in the instance |
| `scope_id` | The ID of the scope file |
| `scope_hash` | The hash of the scope file's content |

The token MUST be signed with the local key in the state directory (DSEC-033). It MUST expire after 10 minutes and MUST be usable only once.

Why: A token that binds everything it previewed cannot be spent on a different change.
Check: 🤖 General conformance tests G03, G04 and G05.

### DCLI-056 Confirm-time review

When a command runs with `--confirm`, the runtime MUST run these checks in order and stop at the first failure. A failed check MUST stop the write and return `E_CONFLICT` with `details.conflict` naming the check. When step 3 finds that the scope no longer grants the operation, it MUST return `E_FORBIDDEN` instead.

<!-- contract:confirm_review -->
| Step | Check | Conflict on failure |
|---|---|---|
| `1` | The token is valid, not expired and not used | `token_invalid`, `token_expired`, `token_used` |
| `2` | The command and all inputs match the token; the error names the parameter that differs | `token_mismatch` |
| `3` | The scope file is unchanged and still grants the operation | `scope_changed` |
| `4` | The target is not locked (DCLI-060) | `target_locked` |
| `5` | The session still exists, with the same generation | `session_changed` |
| `6` | The document revision and unsaved state are unchanged | `document_changed` |
| `7` | The host component version is unchanged | `plugin_changed` |
| `8` | The preview, computed again, can still be applied | `blocked` |

A direct-tier command has no token. It MUST run steps 3 to 8 before dispatch.

Why: The world can change between the preview and the confirmation; checking again just before dispatch stops a write that no longer matches what was approved.
Check: 🤖 General conformance tests G03, G04 and G10; driver conformance tests D02 and D03.

### DCLI-057 Execution and read-back

- Before dispatch, the runtime MUST check the state of the session (DCLI-204), the document (DCLI-211) and the device (DCLI-230), and the loaded host component version (DSEC-053). When one of them blocks the write, it MUST return the error those clauses give. When it is certain that nothing was sent, `dispatch_state` MUST be `not_started`.
- The runtime then dispatches the change.
- After dispatch, the runtime MUST read back the fields the change touched, from the running instance, the file or the device, and put them in the receipt's `observed`. Verification MUST be `passed` only when the read-back matches the request. Fields that do not match MUST be listed in `mismatched`.

Why: A change counts as done only when the tool has seen it in place.
Check: 🤖 Driver conformance tests D04, D07 and D08.

### DCLI-058 Save is the commit point

In session mode a change is not a save. After a change in session mode, the receipt's `persistence` MUST be `unchanged` and the document's `dirty` MUST be `true`. Only `doc save` and writes that create a file report `saved`.

A write with the `artifact` effect, such as `doc save-as`, `export` or `render`, creates a file. Its receipt MUST report `change: not_applicable` and `persistence: saved`, and verification MUST read the new file back: it exists, and its size and SHA-256 match what was written.

The preview of `doc save` MUST list every change since the last save: the tool's own changes with `origin: tool`, and changes the tool did not make, such as a person's edits in the application, with `origin: external`. Each CLI call is short-lived and cannot collect events between calls, so the host component, or the adapter when there is none, MUST keep the list of changes since the last save. When the application cannot say what changed, the preview MUST still show one external change, without field details, for each revision the tool did not make.

Why: "Changed but not saved" must never look like "done", and a save must show exactly what goes to disk.
Check: 🤖 Driver conformance tests D09 and D18.

### DCLI-059 Operation records

- Every write MUST get an operation ID that starts with `op_`.
- Its record MUST be kept in the state directory. It holds the command, target, effects, scope ID, preview, receipt, the time of each stage, the state (`planned`, `dispatched`, `completed`, `failed` or `unknown`) and any outcome recorded by `operation resolve`.
- Records MUST be kept for 30 days.
- When operation records cannot be written, or the token key is unusable (DSEC-033), every write MUST be refused with `E_IO`, and nothing is dispatched. Reads MUST still work.

Why: Without a record, nobody can later tell what the Agent did or settle a write whose outcome is unknown.
Check: 🤖 General conformance test G08.

### DCLI-060 Target locks

- Before dispatch, the runtime MUST lock the target. Only one write per target runs at a time. Another write on the same target MUST get `E_CONFLICT` with `target_locked`, and MAY be retried later. The lock is released when the write ends with a known outcome, whether it succeeded or failed.
- Locks MUST live in the state directory and be shared by all processes of the same user, so writes from several Agents to the same target run one at a time.
- The tool does not detect a person working in the application. A person's edit changes the document revision: this gives `document_changed` at confirm time (DCLI-056) and shows up as external changes in the save preview (DCLI-058).
- A target whose write is outcome unknown MUST stay locked until `operation resolve` records the outcome (DCLI-063).

Why: Two writers on one object can overwrite each other; a lock turns that into a clear conflict.
Check: 🤖 Driver conformance test D06; runtime unit tests for two processes writing to one target.

### DCLI-061 Receipt

A write that succeeds MUST return `data` = `{operation_id, receipt, result}`, where `result` is the command's own result. When the receipt gives `ok: false`, the receipt goes in `error.details.receipt` instead (DCLI-062). The receipt holds:

- `operation_id`, `command`, `target`, `effects` and `tier`;
- `outcome`, with the five dimensions below;
- `observed` and `mismatched`: the values read back, and the fields that do not match;
- `session` `{id, generation}` and `document` `{id, revision, dirty}`;
- `failed_stage`: where the write failed or was interrupted: `apply`, `deliver`, `persist` or `verify`;
- `notes`: extra remarks.

<!-- contract:receipt_dimensions -->
| Dimension | Values |
|---|---|
| `execution` | `not_started`, `running`, `completed`, `failed`, `interrupted`, `unknown` |
| `change` | `not_applicable`, `not_applied`, `applied`, `partial`, `rolled_back`, `unknown` |
| `delivery` | `not_applicable`, `not_attempted`, `delivered`, `partial`, `rejected`, `unknown` |
| `persistence` | `not_applicable`, `unchanged`, `saved`, `partial`, `unknown` |
| `verification` | `not_applicable`, `not_run`, `passed`, `failed`, `incomplete` |

The five dimensions MUST be reported separately and MUST NOT be merged into one success flag.

```json
{"ok":true,"schema_version":"1.0","data":{"operation_id":"op_7mq2xk4v","receipt":{"operation_id":"op_7mq2xk4v","command":"footprint move","target":{"key":"file:///D:/proj/board.kicad_pcb#/footprints/R1","kind":"footprint"},"effects":["change"],"tier":"direct","outcome":{"execution":"completed","change":"applied","delivery":"not_applicable","persistence":"unchanged","verification":"passed"},"observed":{"x_mm":12.5,"y_mm":30.0},"mismatched":[],"session":{"id":"kicad-1234","generation":3},"document":{"id":"doc_1","revision":8,"dirty":true}},"result":{"ref":"R1","x_mm":12.5,"y_mm":30.0}},"meta":{"duration_ms":640}}
```

Why: Ran, changed, delivered, saved and verified are different facts, and the Agent must report each one truthfully.
Check: 🤖 General conformance test R04; driver conformance test D09.

### DCLI-062 Deriving ok and the error code

A tool MUST NOT choose `ok` or the error code of a write itself. The runtime MUST derive both from the receipt with this table, using the first rule that matches. When `ok` is `false`, the receipt MUST go in `error.details.receipt`.

<!-- contract:derivation -->
| Rule | The receipt has | ok | Error code |
|---|---|---|---|
| `1` | `unknown` in execution, change, delivery or persistence, or execution `running` | false | `E_OUTCOME_UNKNOWN` |
| `2` | `partial` in change, delivery or persistence | false | `E_PARTIAL` |
| `3` | Execution `failed`, `interrupted` or `not_started`, but a lasting effect exists (change `applied`, delivery `delivered` or persistence `saved`) | false | `E_PARTIAL` |
| `4` | Execution `failed`, `interrupted` or `not_started`, and no lasting effect | false | The code of the cause; by default `E_NATIVE_FAILURE` |
| `5` | Change `rolled_back` | false | The code of the cause; by default `E_VERIFY_FAILED` |
| `6` | Delivery `rejected` | false | The code of the cause; by default `E_FORBIDDEN` |
| `7` | Verification `failed` | false | `E_VERIFY_FAILED` |
| `8` | Verification `incomplete`, or change `applied` with verification `not_run` | false | `E_VERIFY_INCOMPLETE` |
| `9` | Anything else | true | none |

Rule 8 keeps "changed but not verified" from counting as a success.

Why: When the runtime derives `ok` from facts, no tool can report success that it has not seen.
Check: 🤖 Driver conformance tests D07 and D08; runtime unit tests cover every rule.

### DCLI-063 Outcome unknown

- When the connection is lost, the application crashes or a deadline passes after dispatch, and the tool cannot tell whether the change took effect, the command MUST return `E_OUTCOME_UNKNOWN` with `dispatch_state: unknown`.
- `details.lookup` MUST give the exact command that finds out: a read of the target, or `operation get --id <id>`.
- The Agent MUST run that lookup first and MUST NOT resend the write.
- The target stays locked until `operation resolve` records the outcome (DCLI-060); recording it unlocks the target. The original receipt MUST stay unchanged.

Why: Resending a write that already took effect can apply it twice.
Check: 🤖 Driver conformance test D06.

### DCLI-064 Batch operations

- A command that acts on several objects MUST take them in one `--ids` list. The runtime MUST remove duplicates and keep the input order. An empty list MUST return `E_USAGE`.
- One preview MUST list every object, and one token MUST cover the whole batch. When the preview shows that any object cannot run (`can_apply: false`), the whole batch MUST NOT run.
- The result MUST report each object as `{target, operation_id, ok, receipt or error}`, and a skipped object as `{target, ok: false, skipped: true}`, plus a `summary` of `{total, succeeded, failed, unknown, skipped}`. When the batch does not fully succeed, `error.details.batch` holds the same `{items, summary}`.
- The batch succeeds only when every object succeeds. Otherwise the code MUST be `E_OUTCOME_UNKNOWN` when any object is outcome unknown; else `E_PARTIAL` when any object took effect; else the code of the first failed object.
- `--continue-on-error` MUST default to `true`, and to `false` for dangerous commands. When the batch stops, the remaining objects MUST be reported as skipped and counted in `summary.skipped`.
- A tool MUST NOT claim an all-or-nothing result that the application does not provide.
- When the same operation is often needed on several objects, such as moving parts, changing properties or deleting, the tool SHOULD offer a batch form.

Why: One call for many objects saves calls, and a result per object keeps the report honest when some of them fail.
Check: 🤖 Runtime unit tests.

### DCLI-065 Long jobs

A single call SHOULD return within 60 seconds. Work expected to take longer MUST be a long job. Submitting the job is a normal write (DCLI-050). In the result of the submitting call, `data.result.job` MUST be `{id, status, poll}`, where `poll` is the exact command that checks the job, such as `job get --job 7 --wait 60s` (DCLI-220).

Why: A call that hangs for minutes looks to the Agent like a dead tool.
Check: 👀 Review of command durations in the behavior matrix (DVER-030).

### DCLI-066 Human required

When a dialog, a license, a sign-in, a confirmation on the device or anything else needs a person, the command MUST NOT wait or guess. It MUST return `E_HUMAN_REQUIRED` at once, with these fields in `details`:

- `action`: one of the values below;
- `resume`: the exact command to run after the person has acted;
- `dispatch_state`: whether anything was dispatched.

<!-- contract:human_required_actions -->
| Action | The person must |
|---|---|
| `dismiss_dialog` | Deal with a dialog in the application |
| `activate_license` | Deal with the license |
| `sign_in` | Sign in |
| `install_component` | Install a component |
| `confirm_on_device` | Confirm on the device |
| `restart_application` | Restart or reload the application instance, for example to load a new host component (DSEC-053) |
| `other` | Do something else |

The dialog's title and text MUST go in `details` and MUST be listed in `meta.untrusted`.

Why: A modal dialog can block a call forever; returning at once lets the Agent ask the person.
Check: 🤖 Driver conformance test D05.

### DCLI-067 Undo and guarantees

A tool MAY offer `doc undo`, which undoes the tool's most recent change. It MUST NOT offer it when the application has no undo. A tool MUST NOT claim transactions, undo, cancellation or idempotency that the application does not provide.

Why: A promise the application cannot keep is worse than no promise.
Check: 👀 Review against the capability survey (DREPO-060).

## Self-update

### DCLI-070 update is required

Every tool MUST provide `update`. The runtime implements it. The tool only supplies its npm package name and MUST NOT write its own update logic.

Why: Without one shared implementation, tools either skip self-update or each build a different one.
Check: 🤖 `check_project` checks the runtime copy by hash (DREPO-034).

### DCLI-071 Choosing the version

- `update` MUST query the npm registry for versions.
- It MUST validate every version string as semver before using it.
- It MUST refuse a downgrade unless both `--target-version` and `--allow-downgrade` are given.
- `update --check` MUST only query and install nothing.

Why: A malformed version or an unintended downgrade must never reach npm.
Check: 🤖 Runtime unit tests.

### DCLI-072 Moving the running program aside

On Windows a running program cannot be overwritten, but it can be renamed. So on Windows, before running npm, `update` MUST move the native program out of the platform package directory to a place on the same disk, by default `trash/` in the state directory. The next run of `update` MUST delete what it moved there.

Why: Otherwise npm cannot replace the program that is running the update.
Check: 🤖 Runtime unit tests.

### DCLI-073 Running npm safely

`update` MUST build the npm arguments only from the validated package name and version. It MUST NOT run npm through a shell. It MUST run the npm found by absolute path on PATH, never a file of that name in the current directory.

Why: A crafted version string or an npm planted in the working directory must not run code.
Check: 🤖 Runtime unit tests.

### DCLI-074 Checking the result

After installing, `update` MUST run `<tool> --version` and trust the version it reports. The update succeeds only when that version equals the target version. `update` MUST then check the provenance of the installed package. `provenance_status` MUST be `verified` only when that check ran and passed, and `not_checked` when it could not run. A check that ran and failed gives `E_INTEGRITY` (DCLI-078).

Why: npm can report success while the old program is still the one that runs.
Check: 🤖 Runtime unit tests.

### DCLI-075 Direct command entry

On Windows, starting the tool through the npm launcher is much slower than running the native program: more than one second per call. `update` MUST therefore point npm's command entries at the native program in the platform package. On Windows these are the three entry files used by cmd, PowerShell and Git Bash; on other systems it is one symbolic link. The launcher stays as a fallback. The result's `entry` MUST be `direct` when the entry runs the native program and `launcher` when it still goes through the launcher.

Why: An Agent makes many calls; one extra second on each adds up to minutes per task.
Check: 🤖 Runtime unit tests.

### DCLI-076 Skill sync

After installing, `update` MUST sync installed Skills from the new package. It replaces each installed Skill directory with the new copy, MUST leave symbolic links alone, and MUST NOT create a Skill that was not installed.

Why: The CLI and its Skills must stay at the same version (DSKL-030).
Check: 🤖 Runtime unit tests.

### DCLI-077 Running update again

When the tool is already at the target version, `update` MUST return `status: up_to_date` and finish any command entry change and Skill sync that was left undone, so running it again is always safe. After an install, `status` is `updated`. `update --check` installs nothing and returns `available` when a newer version exists, `up_to_date` otherwise. The result's `data` holds:

| Key | Content |
|---|---|
| `status` | `up_to_date`, `updated` or `available` |
| `current_version` | The version installed now |
| `target_version` | The version `update` aims at |
| `previous_version` | The version before this update |
| `update_available` | Whether a newer version than the installed one exists |
| `provenance_status` | `verified` or `not_checked` (DCLI-074) |
| `skill_sync_status` | `synced`, `not_needed`, `failed` or `skipped` |
| `entry` | `direct` or `launcher` (DCLI-075) |

Why: An interrupted update is finished by running the same command again.
Check: 🤖 Runtime unit tests.

### DCLI-078 Update failures

`update` MUST report each failure with this code and leave the tool in this state:

<!-- contract:update_failures -->
| Case | Situation | Code | State afterwards |
|---|---|---|---|
| `registry_unreachable` | The network is down or rate-limited while querying versions | `E_NETWORK` (retryable) | Old version, unchanged |
| `invalid_version_or_unflagged_downgrade` | An invalid version, or a downgrade without both flags | `E_USAGE` | Unchanged |
| `npm_not_found` | No npm on PATH | `E_CONFIG` | Unchanged |
| `running_program_not_movable` | On Windows, the running program cannot be moved aside | `E_IO` | Unchanged |
| `install_failed_or_wrong_version` | npm install fails, or the installed program reports the wrong version; `details` gives the manual install command | `E_IO` | Old version |
| `provenance_check_failed` | The provenance check fails | `E_INTEGRITY` (do not retry) | The installed version, reported as it is |
| `skill_sync_failed` | The tool was updated but the Skill sync failed; `details` gives the command that fixes it | `E_PARTIAL` | New tool, old Skills; run `update` again to finish |

Why: The Agent must know after every failure which version it is running and what to do next.
Check: 🤖 Runtime unit tests.

### DCLI-079 Update notices

- Only `update` and `doctor` contact the npm registry; other commands MUST NOT. `doctor` MUST wait at most 3 seconds for it and ignore a failure.
- The answer MUST be cached in the state directory. Other commands read only the cache and add an `update_available` notice to `meta.notices` at most once every 24 hours.
- The notice's `severity` MUST be `warning` when the new version has security fixes or a new major version, and `info` otherwise.
- `update` updates only the CLI and the Skills. It MUST NOT install host components. When a host component needs reinstalling, the result of `update` and the `doctor` output MUST give the `plugin install` command.

Why: The Agent learns about updates without any command going online, and a host component is never replaced behind the user's back.
Check: 🤖 Runtime unit tests.

## Units

### DCLI-080 Standard units

Every physical quantity MUST use one standard unit, the same in all tools:

<!-- contract:units -->
| Quantity | Unit | Key suffix | Accepted in parameters |
|---|---|---|---|
| `length` | mm | `_mm` | nm, um, mm, cm, m, mil, in |
| `angle` | deg | `_deg` | deg, rad |
| `time` | s | `_s` | ms, s, min, h |
| `temperature` | degC | `_c` | degC, K, degF |
| `mass` | kg | `_kg` | mg, g, kg |
| `force` | N | `_n` | N, kN |
| `pressure` | Pa | `_pa` | Pa, kPa, MPa, bar |
| `speed` | mm/s | `_mm_per_s` | mm/s, mm/min, m/s |
| `angular_speed` | deg/s | `_deg_per_s` | deg/s, rad/s, rpm |
| `frequency` | Hz | `_hz` | Hz, kHz, MHz, GHz |
| `voltage` | V | `_v` | uV, mV, V, kV |
| `current` | A | `_a` | nA, uA, mA, A |
| `resistance` | ohm | `_ohm` | mohm, ohm, kohm, Mohm |
| `capacitance` | F | `_f` | pF, nF, uF, mF, F |
| `inductance` | H | `_h` | nH, uH, mH, H |
| `power` | W | `_w` | mW, W, kW |

Why: When every tool uses the same unit, an Agent can pass values between tools without converting.
Check: 🤖 Runtime unit tests (unit conversion).

### DCLI-081 Unit suffixes in output

An output key for a physical quantity MUST carry the unit suffix from DCLI-080, and its value MUST be a number in the standard unit, such as `x_mm: 12.5`. The timing fields of the envelope and the host protocol (`duration_ms`, `retry_after_ms`, `deadline_ms`) are in milliseconds and are not domain quantities.

Why: The unit is visible in the key, so the Agent cannot misread a value.
Check: 👀 Review of the output schemas in `reference`.

### DCLI-082 Units in parameters

A parameter for a physical quantity MUST accept a value with a unit, such as `--x 100mil` or `--x 2.54mm`; the runtime converts it to the standard unit. A bare number MUST be read in the standard unit. Only the units listed for the quantity in DCLI-080 are accepted; any other unit is an invalid value (`E_USAGE`).

Why: Users and manuals mix units; converting in one place prevents unit mistakes in every tool.
Check: 🤖 Runtime unit tests.

### DCLI-083 Display units

A tool MUST NOT rely on the display units currently set in the application. The adapter MUST convert values whenever it exchanges data with the application.

Why: A user can switch the display from mm to mil at any time; a tool that trusts the display writes wrong values.
Check: 👀 Review of the adapter; the read-back rows of the behavior matrix on the real application (DVER-031).

### DCLI-084 Coordinate systems

For every parameter and output field that holds a coordinate, `reference` MUST state the coordinate system: the origin, the axis directions, and the object the coordinate is relative to.

Why: The same numbers mean different points when the origin or an axis direction differs.
Check: 👀 Review of `reference`.

### DCLI-085 Undeclared units

A physical parameter without a declared unit MUST be rejected when the command is registered.

Why: An undeclared unit is caught before the tool ships, not after a wrong value is written.
Check: 🤖 Driver conformance test D13.

## Modes and Sessions

### DCLI-200 Driver standard commands

The runtime implements these commands from the adapter capabilities (DCLI-260). A tool MUST NOT offer the same function under another name, such as `session inspect`, `model open` or `service install`.

<!-- contract:standard_commands -->
| Command | Effect | Modes | Tier | Description |
|---|---|---|---|---|
| `session list` | `observe` | session | — | Running instances: session ID, application version, state, whether the tool started it, number of open documents |
| `session get` | `observe` | session | — | The full state of one instance, including whether it is busy or shows a dialog |
| `session open` | `session` | session | direct | Starts a new instance and returns its session ID |
| `session close` | `session` | session | direct; dangerous for an instance the tool did not start | Closes an instance; refused when it has unsaved changes |
| `doc list` | `observe` | file, session | — | Documents: path, revision, unsaved changes, read-only |
| `doc get` | `observe` | file, session | — | The state of one document |
| `doc open` | `session` | session | direct | Opens a file in an instance |
| `doc save` | `persist` | session | two-step | Saves to the original path; the preview lists every change since the last save |
| `doc save-as` | `artifact` | session | direct; two-step when the target file exists | Saves as a new file |
| `doc close` | `session` | session | direct; dangerous with `--discard` | Closes; refused with unsaved changes unless `--discard` discards them |
| `doc undo` | `change` | session | direct | Optional, only when the application supports undo: undoes the tool's most recent change |
| `job list` | `observe` | all | — | Long jobs |
| `job get` | `observe` | all | — | The state of one long job; `--wait <duration>` waits until it ends or the time runs out |
| `job cancel` | `change` | all | direct | Asks to cancel a long job the tool started; the result tells "cancel requested" from "confirmed stopped" |
| `device list` | `observe` | device | — | Devices: model, firmware, state, whether simulated |
| `device get` | `observe` | device | — | The state of one device |
| `knowledge list` | `observe` | all | — | Knowledge entries (DSKL-123) |
| `knowledge get` | `observe` | all | — | The body of a builtin entry; the link and reader of a team entry |
| `knowledge search` | `observe` | all | — | Finds knowledge by keyword |
| `knowledge create` | `configure` | all | two-step | Registers the link of a team knowledge document |
| `knowledge delete` | `configure` | all | two-step | Removes a team knowledge registration; the linked document is untouched |
| `plugin get` | `observe` | with a host component | — | The version on disk and the version each instance has loaded |
| `plugin install` | `configure` | with a host component | two-step | Installs or upgrades the host component (DSEC-050) |
| `plugin remove` | `configure` | with a host component | two-step | Removes the host component |

`knowledge create` and `knowledge delete` change only the tool's own registration. They stay two-step but do not count toward the tool's risk tier (DSEC-002).

Why: The same functions under the same names in every tool mean the Agent never relearns sessions, documents or jobs.
Check: 👀 Review of the command tree against this table.

### DCLI-201 Modes

A tool works in one or more of these modes. It MUST declare in `reference` which modes each command supports, and it MUST provide the required commands of every mode it supports.

<!-- contract:modes -->
| Mode | When | Required commands | Read-back from | Saving |
|---|---|---|---|---|
| `file` | Reads and writes files directly, without starting the application | `doc list`, `doc get` | The file, read again | Writing the file is saving |
| `session` | Drives a running instance of the application | Every `session` and `doc` command except the optional `doc undo` | The running instance | Only `doc save` saves |
| `device` | Drives hardware or its controller | `device list`, `device get` | The device or its sensors | Does not apply |

Why: The mode decides where the truth lives and what saving means, so every write knows where to read back.
Check: 🤖 General conformance test R01 checks the mode declarations in `reference`.

### DCLI-202 Selecting a session

When several instances are running and the command has no `--session`, the command MUST return `E_AMBIGUOUS` with the candidates. It MUST NOT pick an instance by window focus or by recent use. With exactly one instance it MAY pick it and MUST name it in the output.

Why: With two projects open, picking by focus changes the wrong project.
Check: 🤖 Driver conformance test D01.

### DCLI-203 Session object

A session MUST have at least these fields; the full definition is in the contract's `objects.schema.json`:

- `id`: the session ID;
- `application`: `{name, version}`;
- `pid`: the process ID;
- `owned`: whether this tool started the instance;
- `generation`: the connection generation. It increases by one when the host component reloads, or when the connection to the instance is re-established after it was lost (DCLI-278). Separate CLI calls to the same running instance see the same generation;
- `state`: see DCLI-204;
- `documents`: the IDs of the open documents;
- `plugin_loaded`: the version of the host component loaded in this instance, or `null` when none is loaded.

Why: `owned` decides whether closing is dangerous, and `generation` lets a token notice a reconnect.
Check: 🤖 Driver conformance test D02.

### DCLI-204 Session states

Commands MUST react to each session state as this table says:

<!-- contract:session_states -->
| State | Meaning | Command reaction |
|---|---|---|
| `starting` | The instance is starting | `E_BUSY`, retryable |
| `ready` | Ready for commands | Runs normally |
| `busy` | The application's main thread is busy | `E_BUSY`, retryable, with a suggested wait; nothing was dispatched |
| `blocked` | A dialog, license window or similar needs a person | `E_HUMAN_REQUIRED` with the dialog title (untrusted) and the resume command |
| `lost` | The process exists but cannot be reached | `E_BACKEND_UNAVAILABLE`; writes already dispatched are recorded as outcome unknown |
| `closed` | The process has ended | The session ID is no longer valid; `E_NOT_FOUND` |

Why: Each state has one fixed reaction, so a busy or blocked application never leaves a call hanging.
Check: 🤖 Driver conformance tests D04, D05 and D21.

### DCLI-205 Session read deadline

`session list`, `session get`, `doc list` and `doc get` MUST return within 5 seconds. When an instance does not answer within 2 seconds, the command MUST stop waiting for it, report its `state` as `busy`, and return the other instances normally.

Why: One hung instance must not hide every other instance from the Agent.
Check: 🤖 Driver conformance test D22.

### DCLI-206 Opening and closing sessions

`session open` MUST start a new instance and return its session ID. `session close` MUST refuse to close an instance that has unsaved changes, with `E_CONFLICT` and `conflict` `unsaved_changes`. Closing an instance the tool did not start (`owned: false`) MUST be dangerous (DCLI-051). When the adapter lacks `open_session` or `close_session`, the matching command returns `E_UNSUPPORTED` (DCLI-260).

Why: Closing loses unsaved work, and an instance the tool did not start may hold a person's work.
Check: 👀 Review of the behavior matrix (DVER-030).

## Documents

### DCLI-210 Document object

A document MUST have at least these fields; the full definition is in the contract's `objects.schema.json`:

- `id`;
- `path`: the file path, or `null` for a new document that has never been saved;
- `session`: the session that holds it, or `null` in file mode;
- `revision`: increases by one with each change;
- `dirty`: whether it has unsaved changes;
- `readonly`;
- `state`: see DCLI-211.

Why: `revision` and `dirty` let a token and the save preview notice any change, including a person's.
Check: 🤖 Driver conformance test D03.

### DCLI-211 Document states

Commands MUST react to each document state as this table says:

<!-- contract:document_states -->
| State | Meaning | Command reaction |
|---|---|---|
| `clean` | Same as on disk | Runs normally |
| `dirty` | Has unsaved changes | Reads and writes run normally; closing or discarding the changes needs extra confirmation (DCLI-212) |
| `readonly` | Read-only | Writes are refused with `E_VALIDATION` |
| `conflict` | The file on disk was changed by someone else after it was opened | Writes and saving are refused with `E_CONFLICT`, conflict `file_changed_on_disk` |
| `missing` | The file no longer exists on disk | Saving to the original path is refused with `E_CONFLICT`, conflict `file_missing` |

Why: A save must never silently overwrite someone else's edits or recreate a file that was moved or deleted.
Check: 🤖 Runtime unit tests.

### DCLI-212 Document commands

The effects and tiers of the document commands are in DCLI-200. In addition:

- `doc close` MUST refuse to close a document with unsaved changes, with `E_CONFLICT` and `conflict` `unsaved_changes`. `doc close --discard` discards them and MUST be dangerous.
- `doc save` writes to the original path, and its preview lists every change since the last save (DCLI-058).
- `doc undo` is optional (DCLI-067).

Why: Unsaved work is lost only when someone has asked for it explicitly and confirmed it as dangerous.
Check: 🤖 Driver conformance test D10.

### DCLI-213 Documents in file mode

In file mode, `--doc` MUST be the file path. Writing the file is saving, and read-back MUST read the file again.

Why: Without an application in between, the file on disk is the only truth.
Check: 👀 Review of the adapter.

## Long Jobs

### DCLI-220 Job object and commands

A job MUST have at least these fields: `id`, `operation_id`, `status`, `cancel_requested` and `started_at`. When the application reports progress, the job MUST also have `progress` `{done, total, unit}`; `total` is `null` when unknown. `status` is one of `planned`, `running`, `succeeded`, `failed`, `partial`, `unknown` and `cancelled`.

`job list` lists the long jobs. `job get --job <id> --wait <duration>` MUST return when the job ends or the time runs out, whichever comes first. `--wait` MUST NOT exceed 60 s (DCLI-065); a longer value returns `E_USAGE`. The Agent MAY call it again and again.

Why: The Agent waits for long work in short, bounded calls instead of one call that hangs.
Check: 🤖 Driver conformance test D11.

### DCLI-221 Cancelling a job

`job cancel` acts only on long jobs the tool started. It MUST first report `cancel_requested: true`. The status MUST become `cancelled` only after the application confirms that the job stopped. When the application cannot cancel, `job cancel` MUST return `E_UNSUPPORTED`.

Why: Reporting "cancelled" before the application stops would let the Agent start new work while the old job still runs.
Check: 🤖 Driver conformance test D11.

## Devices

### DCLI-230 Device object and states

A device MUST have at least these fields: `id`, `model`, `firmware`, `state` and `simulated` (whether it is a simulated device). Before acting, the tool reads the device state (DSEC-061), and commands MUST react as this table says:

<!-- contract:device_states -->
| State | Meaning | Command reaction |
|---|---|---|
| `ready` | Ready to act | Runs normally |
| `busy` | The device is busy | `E_BUSY`, retryable |
| `fault` | The device reports a fault | `E_HUMAN_REQUIRED` with action `confirm_on_device` |
| `emergency_stop` | The emergency stop is engaged | `E_HUMAN_REQUIRED` with action `confirm_on_device` |
| `offline` | The device cannot be reached | `E_BACKEND_UNAVAILABLE` |

Results from a simulated device are marked `simulated` and are never presented as real (DSEC-062).

Why: A machine in fault or emergency stop needs a person on site before anything moves.
Check: 🤖 Driver conformance tests D15 and D23; runtime unit tests with the fake host's simulated device in each state.

## Host Components

### DCLI-240 Host component commands

When a tool has a host component, it MUST offer `plugin get`, `plugin install` and `plugin remove` (DCLI-200). `plugin get` returns the host component object: `name`, `version_on_disk`, `protocol_version`, `install_path` and `loaded` (the version each instance has loaded). Installing and upgrading MUST follow DSEC-050 to DSEC-053.

Why: One install path, with its checks, keeps code that runs inside the application under control.
Check: 🤖 Driver conformance test D12.

## Adapter and Runtime

### DCLI-260 Adapter capabilities

Besides the domain commands, the tool author writes only the adapter capabilities in this table; the runtime does everything else (DCLI-261). When a capability is missing, the runtime MUST return `E_UNSUPPORTED` for the commands that need it, with no tool code.

<!-- contract:adapter_capabilities -->
| Capability | File | Session | Device | Description |
|---|---|---|---|---|
| `probe` | required | required | required | Finds the application's install location, version and license |
| `sessions` | — | required | — | Lists instances and their states |
| `open_session` | — | optional | — | Starts an instance |
| `close_session` | — | optional | — | Closes an instance |
| `documents` | required | required | — | Lists documents and their states |
| `open_doc` | — | required | — | Opens a document |
| `save_doc` | — | required | — | Saves a document |
| `close_doc` | — | required | — | Closes a document |
| `undo` | — | optional | — | Undoes the tool's most recent change, when the application supports undo |
| `read` | required | required | required | Runs a read-only command |
| `preview` | with writes | with writes | with writes | Builds the preview |
| `apply` | with writes | with writes | with writes | Applies the change |
| `read_back` | with writes | with writes | with writes | Reads back the changed fields |
| `job_status` | with long jobs | with long jobs | with long jobs | Reports the state of a long job |
| `cancel` | with long jobs | with long jobs | with long jobs | Cancels a long job |
| `devices` | — | — | required | Lists devices and their states |
| `plugin_status` | with a host component | with a host component | with a host component | Reports the host component versions |
| `plugin_install` | with a host component | with a host component | with a host component | Installs the host component |

A capability marked required for a mode MUST be implemented by every tool that supports that mode. "With writes" means required when the tool has write commands; "with long jobs" and "with a host component" work the same way. An optional capability MAY be left out. A dash means the mode does not use the capability.

Why: The author writes only what is specific to the application; everything shared comes from the runtime.
Check: 🤖 Runtime unit tests.

### DCLI-261 Runtime responsibilities

The driver runtime is responsible for:

- argument parsing, unit conversion and validation, and target key normalization;
- the envelope, the error object and output size control;
- all built-in and standard commands;
- the scope check, confirmation tiers, previews and tokens, and the confirm-time review;
- operation records and locks, receipt derivation, and mapping states to error codes;
- batch operations and long-job polling;
- self-update and update notices.

A tool MUST NOT reimplement any of these. A tool MUST copy the runtime into its project unchanged (DREPO-032).

Why: Shared rules implemented once behave the same in every tool.
Check: 🤖 `check_project` checks the runtime copy by hash (DREPO-034).

### DCLI-262 Where adapter code runs

The code for each adapter capability MUST run where the application's interface can be called, as this table says:

| The application's interface | Where the code runs | Language |
|---|---|---|
| Callable from the CLI: a Python API, COM, the application's own command line, file formats | In the adapter, inside the CLI process | The runtime's language |
| Callable only inside the application's process: a plugin SDK (.NET, Java, C++) or the application's own script language; or calls that must run on the application's main thread | In a host component inside the application's process, talking to the CLI over the host protocol | A language the application supports |

- A tool MAY mix both, for example reading files in the adapter and changing the model through the host component.
- This specification provides the driver runtime in Python. Python reaches COM, most applications' Python interfaces and common file formats; every other interface connects through the host protocol, so one runtime covers every application.

Why: The interface the application offers decides where code can run; one rule saves each author from deciding again.
Check: 👀 Review against the capability survey (DREPO-015).

### DCLI-263 Black-box conformance

Conformance tests MUST treat the CLI as a black box: they call it from the command line, with the fake host, and check the results, whatever the implementation language. A runtime in another language MUST pass the same suites.

Why: Tests that do not depend on the language prove the same behavior for every runtime.
Check: 👀 Review of the conformance suites (DVER-011).

## Host Protocol

### DCLI-270 Local transport

The CLI and the host component MUST connect only on the local machine: through a named pipe on Windows and a Unix socket on macOS and Linux. The host component MUST NOT open network ports and MUST accept connections only from the current user (DSEC-054).

Why: The host component can change the user's designs, so nobody else on the network or on the machine may reach it.
Check: 👀 Review of the host component.

### DCLI-271 Discovery files

When the host component starts, it MUST write a discovery file under `hosts/` in the state directory with `address`, `pid`, `application`, `protocol_version`, `plugin_version` and `started_at`. It MUST delete the file on exit. `session list` MUST read these files and check that each process is still alive.

Why: A crashed host leaves its file behind; checking the process keeps dead instances out of the list.
Check: 🤖 Runtime unit tests.

### DCLI-272 Framing

Messages MUST be JSON-RPC 2.0. Each message MUST be the header line `Content-Length: <bytes>`, then an empty line, then the JSON body encoded in UTF-8. The header line and the empty line each end with CRLF (`\r\n`). `<bytes>` is the length of the body in bytes.

Why: A length header lets each side read whole messages from a stream without guessing where one ends.
Check: 🤖 Runtime unit tests.

### DCLI-273 Handshake

After connecting, the CLI MUST first send `hello` with `protocol_version` and `cli_version`. The host MUST reply with `protocol_version`, `plugin_version`, `application` (name and version), `session` `{id, generation}` and `methods`, the methods it supports. When the major protocol versions differ, the CLI MUST return `E_PROTOCOL` and MUST NOT send any change.

Why: A CLI and a host that disagree on the protocol must stop before they misunderstand a write.
Check: 🤖 Driver conformance test D20.

### DCLI-274 Methods and deadlines

The host methods MUST be the ones in this table. Apart from `hello` and `ping`, each method has the same name and meaning as the adapter capability in DCLI-260. The capability `plugin_install` has no host method: `plugin install` runs in the CLI process, with the checks of DSEC-051. Every request MUST carry `deadline_ms`: how long, in milliseconds, the CLI waits for the reply (DCLI-275).

<!-- contract:host_methods -->
| Method | Write | Meaning |
|---|---|---|
| `hello` | no | Handshake (DCLI-273) |
| `ping` | no | Heartbeat (DCLI-278) |
| `probe` | no | Reports the application's install location, version and license |
| `sessions` | no | Lists instances and their states |
| `open_session` | yes | Starts an instance |
| `close_session` | yes | Closes an instance |
| `documents` | no | Lists documents and their states |
| `open_doc` | yes | Opens a document |
| `save_doc` | yes | Saves a document |
| `close_doc` | yes | Closes a document |
| `undo` | yes | Undoes the tool's most recent change |
| `read` | no | Runs a read |
| `preview` | no | Builds the preview |
| `apply` | yes | Applies the change |
| `read_back` | no | Reads back the changed fields |
| `job_status` | no | Reports the state of a long job |
| `cancel` | yes | Cancels a long job |
| `devices` | no | Lists devices and their states |
| `plugin_status` | no | Reports the host component versions |

Why: One method set for every tool lets the runtime and the fake host speak to any host component.
Check: 🤖 Runtime unit tests.

### DCLI-275 Dispatch state in replies

A reply to a write method (marked in DCLI-274) MUST carry `dispatch_state`. When the host fails before the change starts, it MUST reply `not_started`. When the CLI gets no reply within the deadline, it MUST record the write as outcome unknown (DCLI-063).

Why: Only the host knows whether the change began; the CLI must not guess on its behalf.
Check: 🤖 Driver conformance test D06.

### DCLI-276 Main thread

The host component MUST call the application's interface on the application's main thread. When the main thread is busy, it MUST reply `E_BUSY` at once instead of queuing the request on the connection.

Why: A queued request may run much later, after the Agent has already moved on.
Check: 🤖 Driver conformance test D04.

### DCLI-277 Events

The host MAY push these notifications:

<!-- contract:host_events -->
| Event | Meaning |
|---|---|
| `dialog_opened` | A dialog opened in the application |
| `busy` | The main thread became busy |
| `document_changed` | Someone other than the tool, such as a person, changed a document |
| `session_closing` | The instance is closing |

The host component MUST add each `document_changed` to its list of external changes since the last save, which the save preview reads (DCLI-058).

Why: The save preview can show a person's edits only if the CLI hears about them.
Check: 🤖 Driver conformance test D18.

### DCLI-278 Heartbeat

While connected, the CLI MUST send `ping` every 5 seconds. After 3 missed replies in a row, the session state MUST become `lost`, and writes in flight MUST be recorded as outcome unknown.

Why: A host that stopped answering must not look alive, and its unfinished writes must not look done.
Check: 🤖 Driver conformance test D21.

### DCLI-279 Host errors

The host MUST return only these error codes:

<!-- contract:host_error_codes -->
| Code | When |
|---|---|
| `E_BUSY` | The main thread is busy (DCLI-276) |
| `E_NATIVE_FAILURE` | The application refused the operation and left no lasting change |
| `E_HUMAN_REQUIRED` | A dialog or similar needs a person |
| `E_NOT_FOUND` | The object or document does not exist |
| `E_VALIDATION` | The application rejected the content |
| `E_UNSUPPORTED` | The application cannot do this |

An error MUST be sent as a JSON-RPC error with code `-32000`. Its `data` MUST hold `code` and `dispatch_state`, and `native_message` when the application gave an error text. It SHOULD hold `retry_after_ms` with `E_BUSY` and `action` with `E_HUMAN_REQUIRED`. The CLI adds the other `details` fields of DCLI-012, such as `next_action` and `resume`. `native_message` is the application's own text and MUST be treated as untrusted content (DSEC-020).

Why: A small, fixed set of host errors maps cleanly onto the error codes the Agent already knows.
Check: 🤖 Runtime unit tests.

### DCLI-280 Protocol version

The protocol version MUST follow SemVer and MUST be recorded both in the contract and in the host component's manifest. This specification defines protocol version 1.0.0.

Why: Both sides can compare versions before they exchange a single write.
Check: 🤖 Driver conformance test D20.

### DCLI-281 Host libraries

This specification provides the protocol schema in the contract, a reference implementation in the fake host, and small host-side libraries for some host languages. A host component SHOULD use the library for its language, when one exists, instead of writing its own connection, framing, handshake and heartbeat.

Why: Connection, framing, handshake and heartbeat are easy to get subtly wrong and are the same for every host.
Check: 👀 Review of the host component.

## Checklist

- [ ] DCLI-001 One envelope on stdout
- [ ] DCLI-002 Output formats
- [ ] DCLI-003 Envelope keys
- [ ] DCLI-004 Meta
- [ ] DCLI-005 Names and values
- [ ] DCLI-006 Lists
- [ ] DCLI-007 Default fields
- [ ] DCLI-008 Response size
- [ ] DCLI-010 Error object
- [ ] DCLI-011 Dispatch state and next action
- [ ] DCLI-012 Fixed details fields
- [ ] DCLI-013 Error codes
- [ ] DCLI-014 Exit codes
- [ ] DCLI-020 Noun then verb
- [ ] DCLI-021 Paths and aliases
- [ ] DCLI-022 Verbs
- [ ] DCLI-023 Nouns
- [ ] DCLI-024 Reserved names
- [ ] DCLI-025 Global flags
- [ ] DCLI-026 Shared flags
- [ ] DCLI-027 Target flags
- [ ] DCLI-028 Target keys
- [ ] DCLI-030 Built-in commands
- [ ] DCLI-031 reference
- [ ] DCLI-032 context
- [ ] DCLI-033 doctor
- [ ] DCLI-034 changelog
- [ ] DCLI-035 Operation commands
- [ ] DCLI-036 Version and help
- [ ] DCLI-050 Write flow
- [ ] DCLI-051 Effects
- [ ] DCLI-052 Confirmation tiers
- [ ] DCLI-053 Confirmation required
- [ ] DCLI-054 Dry run and preview
- [ ] DCLI-055 Confirm token
- [ ] DCLI-056 Confirm-time review
- [ ] DCLI-057 Execution and read-back
- [ ] DCLI-058 Save is the commit point
- [ ] DCLI-059 Operation records
- [ ] DCLI-060 Target locks
- [ ] DCLI-061 Receipt
- [ ] DCLI-062 Deriving ok and the error code
- [ ] DCLI-063 Outcome unknown
- [ ] DCLI-064 Batch operations
- [ ] DCLI-065 Long jobs
- [ ] DCLI-066 Human required
- [ ] DCLI-067 Undo and guarantees
- [ ] DCLI-070 update is required
- [ ] DCLI-071 Choosing the version
- [ ] DCLI-072 Moving the running program aside
- [ ] DCLI-073 Running npm safely
- [ ] DCLI-074 Checking the result
- [ ] DCLI-075 Direct command entry
- [ ] DCLI-076 Skill sync
- [ ] DCLI-077 Running update again
- [ ] DCLI-078 Update failures
- [ ] DCLI-079 Update notices
- [ ] DCLI-080 Standard units
- [ ] DCLI-081 Unit suffixes in output
- [ ] DCLI-082 Units in parameters
- [ ] DCLI-083 Display units
- [ ] DCLI-084 Coordinate systems
- [ ] DCLI-085 Undeclared units
- [ ] DCLI-200 Driver standard commands
- [ ] DCLI-201 Modes
- [ ] DCLI-202 Selecting a session
- [ ] DCLI-203 Session object
- [ ] DCLI-204 Session states
- [ ] DCLI-205 Session read deadline
- [ ] DCLI-206 Opening and closing sessions
- [ ] DCLI-210 Document object
- [ ] DCLI-211 Document states
- [ ] DCLI-212 Document commands
- [ ] DCLI-213 Documents in file mode
- [ ] DCLI-220 Job object and commands
- [ ] DCLI-221 Cancelling a job
- [ ] DCLI-230 Device object and states
- [ ] DCLI-240 Host component commands
- [ ] DCLI-260 Adapter capabilities
- [ ] DCLI-261 Runtime responsibilities
- [ ] DCLI-262 Where adapter code runs
- [ ] DCLI-263 Black-box conformance
- [ ] DCLI-270 Local transport
- [ ] DCLI-271 Discovery files
- [ ] DCLI-272 Framing
- [ ] DCLI-273 Handshake
- [ ] DCLI-274 Methods and deadlines
- [ ] DCLI-275 Dispatch state in replies
- [ ] DCLI-276 Main thread
- [ ] DCLI-277 Events
- [ ] DCLI-278 Heartbeat
- [ ] DCLI-279 Host errors
- [ ] DCLI-280 Protocol version
- [ ] DCLI-281 Host libraries
