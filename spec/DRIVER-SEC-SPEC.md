# DRIVER-SEC-SPEC

English | [中文](DRIVER-SEC-SPEC_zh.md)

> Version 1.0.0-rc.1 · Clauses DSEC-001 to DSEC-073

## How to Read

This specification holds the security rules of driver tools. Each rule is a clause with a stable ID, such as `DSEC-014`. Other rules are named by their clause ID only.

- MUST and MUST NOT state a requirement. A tool that breaks one does not conform.
- SHOULD and SHOULD NOT state the expected choice. Depart from it only for a reason you can name.
- MAY states a permission.

Some tables repeat values from the machine contract `contract/driver-contract.json`. A comment line before each such table names the contract entry. When such a table and the contract disagree, the contract wins.

Each clause ends with two lines. `Why:` gives the reason. `Check:` says how conformance is checked: 🤖 means a test or script checks it, 👀 means a person checks it in review.

## Scope

A driver tool is a command-line tool that lets an AI Agent operate a professional desktop application, such as CAD, EDA or simulation software, or a device, such as a machine tool or an instrument. The central idea: a person sets the scope, the Agent does the work, and the tool makes every step correct and honestly reported.

This specification covers what keeps that arrangement safe:

- the risk tiers of commands and tools;
- the authorization scope file, through which a person decides what the Agent may change;
- untrusted content that comes from documents, the application, devices and team knowledge;
- the state directory, where the tool keeps its key, records and locks;
- secrets and outbound network connections;
- installing and running host components;
- physical effects on devices;
- the supply chain from source code to the installed package.

It applies to every driver tool in every mode: file, session and device. The write flow itself (dry run, confirm token, confirm-time review, read-back, receipt) is defined in DCLI-050 to DCLI-067. This specification adds the security rules around it.

## Terms

| Term | Meaning |
|---|---|
| driver tool | A command-line tool that lets an AI Agent operate a desktop application or a device. |
| driver runtime | The shared code that every driver tool copies unchanged. It implements the built-in and standard commands, scope checks, confirmation, operation records, locks and receipts. |
| adapter | The tool author's code that talks to the application, its files or the device. |
| host component | The part of a tool that is installed into the driven application and loaded by it, such as a plugin, an add-in or a script service. |
| effect | What a command changes. Every command declares its effects (DCLI-051). |
| confirmation tier | How a write is confirmed: direct, two-step or dangerous (DCLI-052). |
| risk tier | How far the changes of a command or a tool can reach: `T0`, `T1` or `T2` (DSEC-001). |
| authorization scope, scope file | The grant a person writes in a JSON file: which effects, on which targets, until when. |
| target key | The one way to write down an object, such as `file:///D:/proj/board.kicad_pcb#/footprints/R1` (DCLI-028). |
| dry run | A call with `--dry-run`. It returns a preview and changes nothing. |
| confirm token | The signed, single-use value a dry run returns. The confirming call passes it back (DCLI-055). |
| operation record | The runtime's record of one write: command, target, scope ID, preview, receipt and state (DCLI-059). |
| untrusted content | Text that comes from documents, the application, devices or team knowledge, not from the tool or the person (DSEC-020). |
| state directory | The per-user directory where the runtime keeps its key, records, locks and caches (DSEC-030). |
| secret | A password, an access token or a license key. |
| simulated device | A device that software imitates instead of real hardware. |
| provenance | A signed statement that an npm package was built by the tool's own release workflow. |
| `<tool>` | The tool's command name, such as `kicad-cli`. |
| `<PREFIX>` | The tool's prefix for environment variables: the command name in upper case with `-` replaced by `_`, such as `KICAD_CLI` for `kicad-cli` (DREPO-053). |
| `<state_dir>` | The path of the state directory. |

## Runtime and Tool Responsibilities

| Topic | The driver runtime provides | The tool author does |
|---|---|---|
| Risk tiers | Derives each command's confirmation tier and risk tier from its effects, and the tool's tier from its commands | Declares every effect of every domain command; shows the tool's tier in the README and SECURITY.md |
| Authorization scope | Finds, reads and validates the scope file; checks every write against it; reports its status in `context` | Explains in SECURITY.md how a person writes a scope for this tool; never writes or ships a scope file |
| Untrusted content | Lists native error messages, dialog text and team knowledge in `meta.untrusted` | Declares which result fields of domain commands hold untrusted content |
| State directory | Creates it with owner-only access; keeps the key, operation records, locks, cache and registrations in it | Points every test at a temporary state directory |
| Secrets and network | Masks declared secrets; honors proxies and verifies TLS for `update` and `doctor` | Declares which parameters are secrets; connects only to the application or device it drives, with proxies honored and TLS verified |
| Host components | `plugin get`, `plugin install` and `plugin remove`; hash and protocol checks; refusing writes on a version mismatch | Builds the host component and its manifest; uses the host libraries for the local connection |
| Physical effects | Puts physical commands in the dangerous tier; checks the scope; turns device states into errors | Makes the adapter read the real device state, including emergency stop, faults and readiness; marks simulated devices |
| Supply chain | `update` checks provenance; Skills are installed and synced from the installed package | Keeps lock files; publishes only from a tag-triggered release workflow with provenance; ships packages without install scripts |

## Risk Tiers

### DSEC-001 Risk tiers

Every command has a risk tier. The tier says how far the command's changes can reach.

<!-- contract:risk_tiers -->
| Tier | Meaning | Effects at this tier |
|---|---|---|
| `T0` | Reads only and changes nothing | `observe` |
| `T1` | Changes the application's running state, objects inside the application, or local files | `session`, `change`, `artifact`, `persist` |
| `T2` | Changes settings or host components, reaches external people or systems, or acts on the physical world | `configure`, `deliver`, `physical` |

Each effect has a minimum risk tier, given in the Risk tier column of DCLI-051. A command's risk tier is the highest of these minimums among the effects it declares. The runtime MUST derive the tier from the declared effects. The tool declares effects, not tiers.

Why: A person can judge any tool at a glance when every command's reach is ranked by the same rule.
Check: 🤖 Runtime unit tests.

### DSEC-002 Tool risk tier

A tool's risk tier is the highest risk tier among all its commands, as listed by `reference`. Built-in commands are declared `observe` (DCLI-030), so `update` and the tool's own state do not raise it. `knowledge create` and `knowledge delete` only change the tool's own registration: they keep their two-step confirmation (DSKL-123) but do not count toward the tool's tier. The tool MUST show its tier in the risk badge of the README (DREPO-020), in the README info card (DREPO-021) and in the Risk Tier section of SECURITY.md (DREPO-013). All three MUST equal the tier derived from `reference`.

Why: The tier tells a person how much care the tool needs before they grant it a scope; a badge that claims less than the commands can do misleads them.
Check: 🤖 `check_project` compares the risk badge with the tier derived from `reference`.

### DSEC-003 No downgrades

The confirmation tier and the risk tier of a command follow from its declared effects by the rules of DCLI-051 and DCLI-052. The runtime computes both. A tool MUST declare every effect a command has, and MUST NOT lower either tier, by a setting, by its own code or by changing the runtime. No clause allows a tool to lower a tier. Where another clause lets a tool depart from a default, `reference` shows the departure (DCLI-031). Only the person's scope file can change confirmation, and only to make it stricter (DSEC-013).

Why: If each tool could relax its own confirmation, the person's assurance would depend on every author's judgment instead of on one rule.
Check: 🤖 Conformance tests G01 and G09 run every two-step and dangerous sample; `check_project` confirms the runtime copy is unchanged (DREPO-034).

## Authorization Scope

### DSEC-010 Scope file location

The runtime reads the scope file from the path in the environment variable `<PREFIX>_SCOPE_FILE`. When the variable is not set, the path is `<state_dir>/scope.json`. The runtime MUST NOT look for a scope anywhere else: not in the working directory, not in the project and not in command-line flags.

Why: One fixed place makes it clear which grant is in force, and keeps a scope from arriving inside a downloaded project.
Check: 🤖 Runtime unit tests.

### DSEC-011 Written only by a person

Only a person writes the scope file. The runtime MUST only read it; no command creates, changes or deletes it. An Agent MUST NOT create or modify a scope file, and MUST NOT point `<PREFIX>_SCOPE_FILE` at a file it wrote. When a write is refused for lack of scope, the Agent asks the person to widen the scope.

Why: The scope is the person's decision; an Agent that could write it would grant itself permission.
Check: 🤖 Evaluation scenario `out_of_scope_change` (DSKL-040); 👀 review of the runtime and the Skills.

### DSEC-012 Scope fields

The scope file is one JSON object with these fields:

<!-- contract:scope_fields -->
| Field | Required | Value | Meaning |
|---|---|---|---|
| `scope_id` | yes | string | Names this grant. Confirm tokens and operation records carry it (DCLI-055, DCLI-059). |
| `effects` | yes | non-empty list of effect names other than `observe` | The effects that writes may have (DCLI-051). |
| `dangerous` | yes | `true` or `false` | Whether operations of the dangerous tier are allowed (DCLI-052). |
| `targets` | yes | non-empty list of target-key prefixes | The objects that writes may touch (DCLI-028). |
| `expires_at` | yes | UTC time ending in `Z` | When the grant ends. |
| `confirm` | no | `always` | Makes every write two-step (DSEC-013). |

Reads need no scope, so `observe` is not allowed in `effects`. `contract/schemas/scope.schema.json` holds these rules as a schema. The runtime MUST treat a file that breaks them as invalid (DSEC-016): for example a missing required field, an unknown field, `observe` or an unknown name in `effects`, an empty list, or a value of the wrong type.

Example: a person lets the Agent rework the board files under `D:/proj/board/`, saving included, until 9 November 2026 at 18:00 UTC, and wants every write confirmed in two steps.

```json
{
  "scope_id": "board-rework",
  "effects": ["session", "change", "persist"],
  "dangerous": false,
  "targets": ["file:///D:/proj/board/"],
  "expires_at": "2026-11-09T18:00:00Z",
  "confirm": "always"
}
```

Why: A few fixed fields are enough to say what, where and until when, and a person can write them without help.
Check: 🤖 Runtime unit tests; `check_spec` validates the example scope files in `contract/examples/` against `scope.schema.json`.

### DSEC-013 Stricter only

The runtime MUST use the scope file only to make rules stricter. With `"confirm": "always"`, every write is two-step: a command of the direct tier run without flags changes nothing and returns `E_CONFIRMATION_REQUIRED` with a preview and a confirm token, as a two-step command does (DCLI-053). Dangerous commands stay dangerous. No field can lower a confirmation tier, allow a write that the tier rules refuse, or skip the confirm-time review, the read-back or the operation record.

Why: A person who wants to see every step before it happens can ask for it, but nothing in a file can make the tool less careful than the rules.
Check: 🤖 Driver conformance test D17.

### DSEC-014 Matching targets and effects

A scope covers a write only when all of these hold:

1. Every effect the command declares is listed in `effects`.
2. When the operation is in the dangerous tier, `dangerous` is `true`.
3. The target key of every object the write touches matches one of the prefixes in `targets`, by the normalization and prefix rules of DCLI-028.

A command that touches no object with a target key, such as `session open` or the commands in DSEC-017, is covered when items 1 and 2 hold.

In a batch, every object MUST be covered; one object that is not covered blocks the whole batch (DCLI-064). The runtime MUST NOT widen a prefix, guess a target or match by object name.

Why: The three conditions bound the change only together; any one alone leaves a gap, such as the right effect on the wrong file.
Check: 🤖 Runtime unit tests; driver conformance test D14.

### DSEC-015 Refusing writes

The runtime checks the scope before every write: at the dry run, at the confirm (DCLI-056, step 3) and before a direct-tier write runs. When the scope file is missing, invalid or expired, or does not cover the write, the runtime MUST refuse with `E_FORBIDDEN` and dispatch nothing. `details.scope` states the scope status (DSEC-016) and what is missing: an effect, the dangerous permission or a target key. `details.next_action` tells the Agent to ask the person for a wider scope. At the confirm, a scope file that changed since the dry run but still grants the write gives `E_CONFLICT` with `scope_changed` instead (DCLI-056). Reads MUST NOT be refused for lack of scope.

Why: Without a valid grant the tool cannot know that the person agreed, so it changes nothing; reads stay open so the Agent can still look and report.
Check: 🤖 General conformance tests G07 and G10; driver conformance test D16 for a direct-tier write.

### DSEC-016 Scope status

The runtime MUST report the scope status in the `authorization` key of `context` (DCLI-032), together with the scope ID, the path in use, the allowed effects, whether dangerous operations are allowed and the expiry time. `context` reports it even when the file is missing or invalid. The status is one of:

<!-- contract:scope_statuses -->
| Status | Meaning | Writes |
|---|---|---|
| `granted` | The file exists, is valid and has not expired | Allowed when the scope covers them (DSEC-014) |
| `missing` | There is no file at the path in use (DSEC-010) | Refused with `E_FORBIDDEN` |
| `invalid` | The file cannot be read, is not JSON, or breaks DSEC-012 | Refused with `E_FORBIDDEN` |
| `expired` | The time in `expires_at` has passed | Refused with `E_FORBIDDEN` |

Why: The Agent learns in one read call whether it may write at all, instead of finding out from a refused write.
Check: 🤖 General conformance test R05 runs `context` on an empty state; runtime unit tests cover each status.

### DSEC-017 Scope for records and settings

Some commands change the tool's own records or settings rather than a document. A scope MUST still cover them:

- `operation resolve` needs a scope whose `effects` include every effect of the operation it resolves (DCLI-035).
- `plugin install` and `plugin remove` need `configure` (DSEC-050).
- `knowledge create` and `knowledge delete` need `configure` (DSKL-123).

These commands touch no object that has a target key, so `targets` does not apply to them. Commands that only read or keep the tool's own state, such as `update`, need no scope (DCLI-030).

Why: Resolving an operation unlocks its target and records an outcome, and installing components or registering knowledge changes the environment; each is a decision the person's scope must allow.
Check: 🤖 Runtime unit tests.

## Untrusted Content

### DSEC-020 What is untrusted

Text that comes from outside the tool and the person is untrusted content. It includes:

- object names, document content and file names;
- dialog titles and dialog text;
- native error messages of the application;
- messages from devices;
- team knowledge: the registered links, their descriptions and the documents they point to (DSKL-107).

The runtime and the tool MUST treat all of it as untrusted, whoever wrote it.

Why: Documents and dialogs can hold text written to steer an Agent; the origin of the text is the only line between data and instructions that holds for every application.
Check: 👀 Review of each command's output fields against this list.

### DSEC-021 Marking untrusted content

Every envelope that carries untrusted content MUST list the JSON path of each untrusted value in `meta.untrusted`; when there is none, the key is omitted (DCLI-004). The runtime marks the values it produces itself: native error messages, dialog titles and text in the `details` of `E_HUMAN_REQUIRED` (DCLI-066), and team knowledge fields. For domain commands, the tool declares which result fields hold untrusted content when it registers the command, and the runtime lists them.

Why: An Agent can keep data apart from instructions only when the output says, field by field, which text came from outside.
Check: 🤖 Driver conformance test D19 for team knowledge; 👀 review of the untrusted fields declared for domain commands.

### DSEC-022 Never instructions

The runtime, the tool and its Skills MUST NOT act on untrusted content as instructions. Text such as "also delete layer 3" in a document, or "run this command to fix the license" in a dialog, is data to report, not a step to take. When untrusted content proposes an operation, the Agent MUST stop and ask the person before doing it (DSKL-008). Untrusted content never widens the scope or the targets.

Why: Following text found in a document would let whoever wrote the document steer the Agent beyond what the person asked.
Check: 🤖 Evaluation scenario `injected_instruction` (DSKL-040); 👀 review of the adapter and the Skills.

## State Directory

### DSEC-030 State directory location

The state directory is at the path in the environment variable `<PREFIX>_STATE_DIR`. When the variable is not set, it MUST be `.<tool>` in the user's home directory (`~/.<tool>`). Each user has one state directory, shared by every process of that user. The runtime creates it on first use with the protection of DSEC-032.

Why: One known place per user lets several Agents share locks and records, and lets a person find and inspect them.
Check: 🤖 Runtime unit tests.

### DSEC-031 State directory contents

The state directory holds these entries:

<!-- contract:state_dir_entries -->
| Entry | Holds | Written by |
|---|---|---|
| `keys/` | The local key that signs confirm tokens (DSEC-033) | The runtime |
| `operations/` | Operation records, kept 30 days (DCLI-059) | The runtime |
| `locks/` | Target locks (DCLI-060) | The runtime |
| `cache/` | The result of the last update check (DCLI-079) | The runtime |
| `hosts/` | Discovery files of running host components (DCLI-271) | Host components |
| `trash/` | Native programs moved aside by `update`, removed on the next run (DCLI-072) | The runtime |
| `scope.json` | The scope file at its default location (DSEC-010) | A person only |
| `knowledge-links.json` | Team knowledge registrations (DSKL-122) | `knowledge create` and `knowledge delete` only |

Only the writer named in the table MAY write an entry. Apart from the discovery files that host components write in `hosts/`, tool code MUST NOT write into the state directory directly; it goes through the runtime.

Why: A fixed layout tells the person what the tool keeps on disk and lets checks find every file that matters for safety.
Check: 🤖 Runtime unit tests; 👀 review of tool code for direct writes to the state directory.

### DSEC-032 Access protection

Only the current user may read or write the state directory. On macOS and Linux its mode MUST be `0700`. On Windows its ACL MUST grant access to the current user only. The runtime sets this when it creates the directory. `context` MUST report the protection actually in place (DCLI-032): `posix_0700`, `windows_acl` or `none`, never the protection intended.

Why: The directory holds the token key, the default scope file and the record of every change; another user who could write there could forge tokens or widen the scope.
Check: 🤖 Runtime unit tests.

### DSEC-033 Token key

The runtime signs confirm tokens with a local key kept in `keys/` (DCLI-055). The key MUST NOT leave the state directory or appear in any output, log or record. When there is no key, the runtime creates one; tokens signed with an older key then fail as `token_invalid`. A key that cannot be read, is damaged or cannot be created is unusable. While the key is unusable, every write is refused with `E_IO` and nothing is dispatched; reads keep working (DCLI-059).

Why: A forged or replayed token would skip the dry run. Without a usable key the runtime cannot tell a real token from a forged one, so refusing writes is the only safe answer.
Check: 🤖 Conformance test G08.

### DSEC-034 Tests use a temporary state directory

Tests MUST NOT read or write the user's real state directory. Every test run MUST set `<PREFIX>_STATE_DIR` to a new temporary directory, and either set `<PREFIX>_SCOPE_FILE` to a scope file inside that directory or remove the variable from the test environment.

Why: The real directory holds the person's scope, locks and records; a test that touches them could grant permissions, release locks or hide a real operation.
Check: 👀 Review of the test setup.

## Secrets and Network

### DSEC-040 Secrets

Secrets MUST NOT appear in output, logs, operation records, error messages or live records (DVER-042). Wherever an input is echoed, as in the `inputs` of a preview (DCLI-054), a secret MUST be shown as `***`. The tool declares which parameters are secrets when it registers its commands; the runtime masks them.

Why: Output, records and logs are read by Agents and kept on disk; a secret there leaks to every later reader.
Check: 🤖 Runtime unit tests; 👀 review of the parameters declared as secrets.

### DSEC-041 Outbound connections

A tool MUST connect to these addresses only:

- the npm registry, from `update` and `doctor` only (DCLI-079);
- the application services or devices the tool drives, from the commands that drive them.

A tool MUST NOT send telemetry of any kind. The connection to a host component stays on the local machine (DSEC-054).

Why: A person granting a scope must be able to tell where data can go; a tool that reports home could take design data out of the company.
Check: 🤖 Driver conformance test D19 confirms that the knowledge commands send no request; 👀 review of every network call in the runtime and the adapter.

### DSEC-042 Team knowledge is read by the Agent

The Agent reads team knowledge documents itself, with lark-cli (DSKL-110). The tool MUST NOT connect to Feishu and MUST NOT keep a Feishu account or credential. Of team knowledge it stores only the registered links (DSKL-105).

Why: Sign-in and permissions for team documents belong to the person's own Feishu tools; a driver tool that held a Feishu account could leak it.
Check: 🤖 Driver conformance test D19.

### DSEC-043 Proxies and TLS

Every network request MUST honor the environment variables `HTTPS_PROXY`, `HTTP_PROXY` and `NO_PROXY`. Every TLS connection MUST verify the server certificate. A tool MUST NOT offer a flag, setting or environment variable that turns certificate checks off.

Why: Tools run in company networks behind proxies; skipping certificate checks would let anyone on the path change an update or a device command.
Check: 👀 Review of the network code in the runtime and the adapter.

## Host Components

### DSEC-050 Installing host components

A host component MUST be installed, upgraded or removed only through `plugin install` and `plugin remove` (DCLI-240). Both are two-step writes with the `configure` effect, so they need a scope that allows `configure` (DSEC-017). `update`, domain commands and the npm installation MUST NOT install or change a host component; when one needs installing again, `update` and `doctor` give the `plugin install` command instead (DCLI-079).

Why: A host component runs inside the person's application with the application's full rights; putting it there changes the environment, which the person must allow and see.
Check: 🤖 Runtime unit tests; 👀 review that `update` and the npm packages install no host component.

### DSEC-051 Checking before install

Before it installs a host component, `plugin install` MUST check:

1. that every file matches the hash recorded in the host component's manifest; on a mismatch it installs nothing and returns `E_INTEGRITY`;
2. that the protocol version in the manifest has the same major version as the CLI's (DCLI-280); otherwise it installs nothing and returns `E_PROTOCOL`.

It installs each version into its own directory, named by the version. An older version stays on disk until no running instance has it loaded.

Why: A changed file or an incompatible protocol inside the application can damage work or open a hole; separate version directories let running instances keep the files they loaded.
Check: 🤖 Runtime unit tests.

### DSEC-052 No restarts

The tool MUST NOT restart, reload or close a person's application instance to upgrade a host component. A running instance keeps the version it loaded until the person restarts or reloads it.

Why: Restarting an instance can lose unsaved work and interrupts the person who is using it.
Check: 👀 Review of `plugin install` in the runtime and of the host component.

### DSEC-053 Version mismatch

`context` and `doctor` MUST report the host component version on disk and the version loaded in each instance. When an instance has loaded a version other than the one on disk:

- the `plugin` check of `doctor` fails;
- every write command to that instance is refused before dispatch, with `dispatch_state` `not_started`, and the error is `E_HUMAN_REQUIRED` with action `restart_application`, asking the person to restart or reload the instance.

Why: A host component that differs from the one the CLI expects can apply changes that the CLI cannot read back or report correctly.
Check: 🤖 Driver conformance test D12.

### DSEC-054 Local connections only

A host component MUST use only the local transport of DCLI-270: a named pipe on Windows or a Unix socket on macOS and Linux, open to the current user only. It MUST NOT open a network port. Every connection starts with the handshake of DCLI-273, so a different protocol major version ends it before any change is sent. Host components SHOULD use the host libraries for all of this (DCLI-281).

Why: A host component can change anything in the application; a port reachable from the network or by another user would let others drive it.
Check: 🤖 Driver conformance test D20 for the handshake; 👀 review of the host component's transport.

## Physical Effects

### DSEC-060 Physical effects are dangerous

Every command with the `physical` effect is in the dangerous tier, whatever else it declares. It MUST be run with `--dry-run` and then `--confirm`, with `--dangerous` on both calls (DCLI-052, DCLI-053). The scope MUST list `physical` in `effects`, set `dangerous` to `true` and cover the device target, such as `device:cnc-01/axis-x` (DSEC-014). When any of these is missing, the runtime refuses and nothing moves.

Why: A machine that moves or a circuit that is powered can hurt people or break equipment, and the action cannot be undone.
Check: 🤖 Driver conformance test D14.

### DSEC-061 Check the device first

Right before it dispatches a physical action, the runtime MUST read the device state from the device through the adapter, never from a cache. When the device is in `emergency_stop` or `fault`, or reports that it is not ready for the action, the command MUST return `E_HUMAN_REQUIRED` with `action` `confirm_on_device` and the `resume` command (DCLI-066), and dispatch nothing. It MUST NOT wait for the device to recover. The states `busy` and `offline` give the errors of DCLI-230.

Why: A machine that stopped did so for a reason a person must see; the Agent cannot see the machine.
Check: 🤖 Driver conformance test D23; runtime unit tests.

### DSEC-062 Simulated results

When a device is simulated, every result from it MUST say so: the device object has `simulated: true` (DCLI-230), and so does the result of every command run on it. The tool, its Skills and the Agent's report MUST NOT present a simulated result as a real one. Results from a simulated device count only as simulated evidence (DVER-021).

Why: A run on a simulator says nothing about the real machine; reporting it as real would hide the risk.
Check: 🤖 Driver conformance test D15.

## Supply Chain

### DSEC-070 Locked dependencies

The tool MUST pin all its dependencies with lock files kept in the repository, and CI MUST build from those lock files.

Why: Without a lock file, a build can pull in a different, possibly compromised, version of a dependency without anyone noticing.
Check: 👀 Review of the repository and the CI build steps.

### DSEC-071 Releases from CI with provenance

Every npm package of the tool, the main package and every platform package, MUST carry provenance showing that the tool's own release workflow built it. Publishing therefore runs only in the tag-triggered release workflow, never on a personal machine (DREPO-043). After it installs, `update` checks the provenance and reports `verified` or `not_checked` honestly (DCLI-074).

Why: Provenance lets anyone check that an installed package was built from the tagged source, not by whoever held a publish token.
Check: 👀 Review of the release workflow; `update` reports `provenance_status` after every install (DCLI-074).

### DSEC-072 No install scripts

The tool's npm packages, the main package and every platform package, MUST NOT have install scripts (`preinstall`, `install` or `postinstall`) and MUST NOT download anything at install time. Everything the tool needs is inside its packages (DREPO-051).

Why: An install script runs with the user's rights before anyone has looked at the tool, and a download at install time escapes the provenance check.
Check: 🤖 The npm package content check of the merge gate (DREPO-041).

### DSEC-073 Skills come from the installed package

Skills MUST be installed and synced only from the installed npm package (DSKL-031, DCLI-076). The tool MUST NOT fetch Skills from the network.

Why: A Skill steers the Agent; a copy fetched from elsewhere could carry instructions that the tool's authors never wrote and the provenance check never saw.
Check: 👀 Review of the Skill install and sync code in the runtime.

## Checklist

- [ ] DSEC-001 Risk tiers
- [ ] DSEC-002 Tool risk tier
- [ ] DSEC-003 No downgrades
- [ ] DSEC-010 Scope file location
- [ ] DSEC-011 Written only by a person
- [ ] DSEC-012 Scope fields
- [ ] DSEC-013 Stricter only
- [ ] DSEC-014 Matching targets and effects
- [ ] DSEC-015 Refusing writes
- [ ] DSEC-016 Scope status
- [ ] DSEC-017 Scope for records and settings
- [ ] DSEC-020 What is untrusted
- [ ] DSEC-021 Marking untrusted content
- [ ] DSEC-022 Never instructions
- [ ] DSEC-030 State directory location
- [ ] DSEC-031 State directory contents
- [ ] DSEC-032 Access protection
- [ ] DSEC-033 Token key
- [ ] DSEC-034 Tests use a temporary state directory
- [ ] DSEC-040 Secrets
- [ ] DSEC-041 Outbound connections
- [ ] DSEC-042 Team knowledge is read by the Agent
- [ ] DSEC-043 Proxies and TLS
- [ ] DSEC-050 Installing host components
- [ ] DSEC-051 Checking before install
- [ ] DSEC-052 No restarts
- [ ] DSEC-053 Version mismatch
- [ ] DSEC-054 Local connections only
- [ ] DSEC-060 Physical effects are dangerous
- [ ] DSEC-061 Check the device first
- [ ] DSEC-062 Simulated results
- [ ] DSEC-070 Locked dependencies
- [ ] DSEC-071 Releases from CI with provenance
- [ ] DSEC-072 No install scripts
- [ ] DSEC-073 Skills come from the installed package
