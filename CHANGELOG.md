# Changelog

All notable changes to tool-driver-cli-spec are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0-rc.1] - 2026-11-04

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
