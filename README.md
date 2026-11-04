# tool-driver-cli-spec

A specification for driver tools: command-line tools that let AI Agents operate professional desktop applications and devices.

[![Check](https://github.com/fatecannotbealtered/tool-driver-cli-spec/actions/workflows/check.yml/badge.svg)](https://github.com/fatecannotbealtered/tool-driver-cli-spec/actions/workflows/check.yml)
![Spec](https://img.shields.io/badge/spec-1.0.0--rc.1-blue)
![Status](https://img.shields.io/badge/status-in%20development-orange)
![License](https://img.shields.io/badge/license-Apache--2.0-green)

English | [中文](README_zh.md)

## What It Is

A person sets the scope, the Agent does the work, and the tool makes every step correct and honestly reported.

The specification decides everything a new driver tool would otherwise decide on its own: project skeleton, documents, built-in commands, self-update, the driver model, the write flow, the adapter boundary and the conformance tests. A tool author writes only the domain commands, the adapter, the Skills, the knowledge entries and the evaluation questions. Every tool then behaves the same, so an Agent that knows one knows them all.

| Requirement | Meaning |
|---|---|
| See clearly | The Agent always knows which instances and documents are open, what is unsaved, and whether the application is busy or blocked by a dialog. |
| Change precisely | Every change lands on a named instance, document and object, with explicit units, and is read back afterwards. |
| Report truthfully | Changed, saved and verified are reported separately; unknown is reported as unknown. |
| Stay safe and lean | A person grants what may change; confirmation grows with risk; output is small and calls are few. |

## The Five Specifications

| Specification | Prefix | Covers | Files |
|---|---|---|---|
| DRIVER-CLI-SPEC | `DCLI` | Output and errors, commands, driver model, writes, self-update, adapter and runtime, host protocol | [English](spec/DRIVER-CLI-SPEC.md) · [中文](spec/DRIVER-CLI-SPEC_zh.md) |
| DRIVER-SEC-SPEC | `DSEC` | Risk tiers, authorization scope, untrusted content, state directory, secrets and network, host components, physical effects, supply chain | [English](spec/DRIVER-SEC-SPEC.md) · [中文](spec/DRIVER-SEC-SPEC_zh.md) |
| DRIVER-SKILL-SPEC | `DSKL` | Agent Skills, several Skills per tool, evaluation, the knowledge base | [English](spec/DRIVER-SKILL-SPEC.md) · [中文](spec/DRIVER-SKILL-SPEC_zh.md) |
| DRIVER-VERIFY-SPEC | `DVER` | Conformance tests, fake host, behavior matrix, maturity and evidence, live acceptance | [English](spec/DRIVER-VERIFY-SPEC.md) · [中文](spec/DRIVER-VERIFY-SPEC_zh.md) |
| DRIVER-REPO-SPEC | `DREPO` | Project layout, documents, badges and labels, pinning, versions and CI, npm distribution, capability survey | [English](spec/DRIVER-REPO-SPEC.md) · [中文](spec/DRIVER-REPO-SPEC_zh.md) |

## Machine Contract

Every value a tool or a test can read as data lives in [`contract/driver-contract.json`](contract/driver-contract.json): error codes and exit codes, flags, effects and tiers, receipt rules, states, standard commands, units, the host protocol and the knowledge formats. [`contract/schemas/`](contract/schemas/) holds the JSON Schemas and [`contract/examples/`](contract/examples/) holds examples that must pass or fail them. The tables in the specifications are checked against the contract, so the two never drift apart.

## Status

Version 1.0.0-rc.1 is in development. Nothing is released yet. The driver runtime, the conformance suites, the project template, the evaluation suite, the development Skill and the onboarding guide exist; tools can adopt the specification once 1.0.0-rc.1 is released.

| Phase | Content | State |
|---|---|---|
| 1 | Design | Done |
| 2 | Specifications, contract, schemas, checks | Done |
| 3 | Fake host, the reference implementation of the host protocol | Done |
| 4 | Python driver runtime, the two conformance suites and the project template | Done |
| 5 | Evaluation suite, Skill and knowledge templates, development Skill, onboarding guide | Done |
| 6 | Release 1.0.0-rc.1, then 1.0.0 | Planned |

## Repository Layout

```text
tool-driver-cli-spec/
├── spec/        the five specifications, English and Chinese
├── contract/    driver-contract.json, schemas/, examples/
├── sdk/python/  _driver/, the driver runtime every tool copies (DREPO-032)
├── conformance/ fakehost/, the fake host (DVER-020); suites/, the two conformance suites (DVER-001); eval/, the evaluation questions (DSKL-041)
├── template/    the project template a new tool is generated from (DREPO-062)
├── scripts/     check_spec.py, build_spec_bundle.py; instantiate.py, sync_spec.py, check_project.py, run_matrix.py, run_eval.py for tool projects
├── skills/      build-driver-cli/, the development Skill that guides an Agent through building a tool (DREPO-062)
├── docs/        ONBOARDING.md, the guide for a person who wants a new tool; OPEN-QUESTIONS.md
└── tests/       unit tests for the scripts, the fake host and the runtime; sample/, the sample tool the suites run against; e2e_template.py, eval_template.py
```

## Checks

```bash
python -m pip install --require-hashes --no-deps -r requirements-dev.txt
python scripts/check_spec.py
python -m unittest discover -s tests -v
python scripts/build_spec_bundle.py
cd conformance
python -m suites --project ../tests/sample -- python -m sample_cli
```

The template end-to-end run needs the template's dependencies (they add PyInstaller) and npm:

```bash
python -m pip install --require-hashes --no-deps -r template/requirements-dev.txt
python tests/e2e_template.py
```

The evaluation suite runs every scenario with the template tool on the fake host. CI checks each grader with the scripted agents; before each release the suite runs with a real Agent, Claude Code, and every question must pass:

```bash
python tests/eval_template.py
python tests/eval_template.py --agent claude --report eval-report.json
```

To get a new driver tool, start with the onboarding guide [docs/ONBOARDING.md](docs/ONBOARDING.md): it shows how to install the development Skill `build-driver-cli`, which takes your Agent through every step. A new tool project starts from the release bundle:

```bash
python scripts/instantiate.py ../kicad-cli --tool kicad-cli --package @acme/kicad-cli --application KiCad --versions ">=9.0 <11" --modes file,session
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
