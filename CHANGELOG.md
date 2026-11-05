# Changelog

All notable changes to tool-driver-cli-spec are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.1] - 2026-11-05

Changes from reworking three tools onto 1.0.0. Every change serves the same goals: fast, accurate and steady, and the Agent knows the result of a change from the structured return.

### Added

- DCLI-068: the result of a write shows what the change made, such as a track's end points, net and connections, with only the direct effects and nothing that takes long to compute. DSKL-011: Skills check results as data, never by recognizing a screenshot.
- Long jobs the runtime runs itself (DCLI-065): a command registered `long: true` returns a job at once and runs its work in a worker of the same tool. A long read, such as a design rule check of a large board, needs no scope and returns its result through `job get`. Driver conformance test D26 checks it.
- Document kinds (DCLI-029, DCLI-210): a command lists the kinds of document it works on in `doc_kinds`. It refuses a document of another kind, and its normal row must pass on every kind (DVER-030, DVER-040). `run_matrix --kind` records the kind of each run.
- Verification after the save (DCLI-057): a command registered `verify_after_save` reports verification `deferred` in session mode, and the next `doc save` verifies it.
- `doc create --path` and `--template`, in file mode too (DCLI-212).
- The flag type `json` for structured values such as pad tables, and batch items of a `create` command without `id` (DCLI-029, DCLI-064).
- Conditions a command registers in `tier_when`, which the adapter's preview raises with `tier_raises` (DCLI-052).
- The adapter may answer `E_AMBIGUOUS`, `E_CONFLICT`, `E_BACKEND_UNAVAILABLE` and `E_TIMEOUT` (DCLI-279). The host protocol is now version 1.1.0.

### Changed

- The `read_back_mismatch` row is caused from outside: `run_matrix --row read_back_mismatch` makes the tool wait before its read-back, and a person or `--tamper` changes the result meanwhile (DVER-030).
- A file-mode write is refused while an instance has the file open only when it changes or saves the file; an export goes ahead, with a notice (DCLI-201).
- `dirty` may be `null` when the application cannot tell, and then counts as possibly unsaved (DCLI-210).
- The adapter and the host component mix capability by capability (DCLI-262).
- A write that makes files and changes a document verifies both (DCLI-057).
- `plugin/source/` is not installed. A vendor-built binary may be committed, with how it was built (DCLI-240).
- Clarified: hyphenated nouns (DCLI-023); what is irreversible, in file mode too (DCLI-051); the reference index (DCLI-031); flows that cross Skills belong in the entry Skill (DSKL-021); rename stubs do not apply to a rebuild from scratch (DSKL-028); instances the tool started itself (DSEC-052); `provided` counts standard commands (DREPO-060); where the schemas come from (DVER).

### Fixed

- `instantiate` no longer leaves `__pycache__` in the new project.

## [1.0.0] - 2026-11-04

### Added

- Five specifications, each in English and Chinese: DRIVER-CLI-SPEC, DRIVER-SEC-SPEC, DRIVER-SKILL-SPEC, DRIVER-VERIFY-SPEC and DRIVER-REPO-SPEC.
- The machine contract `contract/driver-contract.json`, twenty-one JSON Schemas (including the adapter payloads, behavior matrices, evaluation reports and command registrations), and valid and invalid examples for each schema.
- `scripts/check_spec.py`, which checks clause format, numbering, language pairs, cross-references, contract tables, schema enums, the clauses each conformance test checks, schemas and examples.
- `scripts/build_spec_bundle.py`, which builds the release ZIP with a manifest and prints release notes from this file.
- The fake host `conformance/fakehost/`, which stands in for the application in tests and is the reference implementation of the host protocol: a named pipe on Windows and a Unix socket elsewhere, Content-Length framing, the handshake, discovery files, a generic answer to domain commands and injectable faults.
- The Python driver runtime `sdk/python/_driver/`: the envelope, errors and limits, argument and unit parsing, command registration checks and tiers, the built-in commands, the session, document, job, device, plugin and knowledge commands, the whole write flow with scope, previews, confirm tokens, confirm-time review, records, locks, read-back, receipts, batches and long jobs, the CLI side of the host protocol and the fake host switch.
- The general and driver conformance suites `conformance/suites/`, and the sample tool `tests/sample/` they run against in CI, with and without a host component.
- `update` in the driver runtime: versions asked through npm with npm's own settings, the downgrade guard, moving the running program aside on Windows, npm run without a shell, the version check with a return to the earlier version when it fails, the provenance check through npm's registry signatures and attestations, direct command entries for cmd, PowerShell and Git Bash, and the sync of installed Skills.
- The project template `template/`: every root file and document in English and Chinese with its fixed text, the entry Skill, two knowledge entries, the Python package with an empty adapter, the npm launcher, scripts that build the native program, pack and check the npm packages, run platform delivery against a local registry and gate the release, and the CI and release workflows.
- The project scripts, which run from the release bundle: `instantiate` generates a tool project, `sync_spec` pins a release into it, `check_project` checks it and with `--fix` writes the generated content, and `run_matrix` runs a behavior matrix on the real application and writes the live record.
- `tests/e2e_template.py`, which generates, fills in, checks, tests, builds, packs, delivers and updates a tool from the template, and runs in CI on Windows, macOS and Linux.
- The evaluation suite `conformance/eval/`: one question for each of the eighteen scenarios, each with a grader and a right and a wrong scripted agent, run with the template tool on the fake host by `tests/eval_template.py`; CI checks on Windows, macOS and Linux that every grader passes the right agent and fails the wrong ones.
- The evaluation runner `scripts/run_eval.py`, which runs Python question files with Claude Code or with their scripted agents: a fresh workspace per question, the documents beside it, the tool on PATH behind a shim that records every run, and an evaluation report tied to each question file by its SHA-256. `check_project` checks the question files, and accepts a stable command only with the newest report from the real application that covers every current question, all passed.
- The development Skill `skills/build-driver-cli/`, shipped in the release bundle: it guides an Agent through the eight onboarding steps with the clauses to read, what to fill and the check to run, then reviews the tool against the specification; its reference files cover command registrations and behavior matrices, domain Skills and rename stubs, knowledge entries and evaluation questions. The onboarding guide `docs/ONBOARDING.md`, in English and Chinese, for a person who wants a new driver tool.
- Pointers from errors to knowledge: an adapter error with `knowledge=[...]`, or a host error with `data.knowledge`, puts the entry IDs in `details.knowledge` and the `knowledge get` command in `next_action`, also for write errors and dialogs after dispatch. The host component manifest `plugin/manifest.json`, whose version, protocol version and file hashes `check_project` writes, with the `methods` the author lists. Rename stubs name the Skill to read instead in `metadata.replaced_by`. `check_project` asks behavior matrices only for the standard commands whose adapter capabilities the tool implements.
- Check and release workflows for Windows, macOS and Linux.
