# AGENT.md — {{NAME}} playbook

{{NAME}} is a driver CLI. Two pinned rule sets apply, both vendored in this repository and checked by `check_project.py`:

| Rule set | Where | Read when |
|---|---|---|
| ai-native-cli-spec (base) | `.agent/driver/base/ai-native-cli-spec/` — `AGENT.md`, `CLI-SPEC.md`, `SKILL-SPEC.md`, `SEC-SPEC.md`, `REPO-SPEC.md` (each with `_zh`) and `contract.json` | any change to output, errors, flags, self-description, Skills, security or the repository layout |
| tool-driver-cli-spec (driver layer) | `.agent/driver/docs/` — `LAYERING.md`, `CORE-SPEC.md`, `DRIVER-SPEC.md`, `VERIFICATION-SPEC.md`, `DELIVERY-SPEC.md`, `SKILL-ADDENDUM.md`, guides | any change that touches targets, plans, receipts, scope, long operations, devices or evidence |

Read only the parts the task needs. The driver layer never relaxes the base; `LAYERING.md` lists what it adds.

## What is generated, what is yours

- `registry.json` is the single source of the commands. `python .agent/driver/scripts/generate_product.py --registry registry.json --output {{PACKAGE}}/generated --update` writes `{{PACKAGE}}/generated/` (contract, reference, contract-ext, Skill capability summary). Never hand-edit generated files; CI runs the generator with `--check`.
- `.agent/driver/` and `.agent/vendor/sdk/` are pinned copies. Never edit them; replace them by instantiating a newer starter or re-copying from a newer specification package, and record the change in CHANGELOG.
- `{{PACKAGE}}/adapter.py` is the native side: targets, snapshots, plans, receipts and read-back. The SDK owns flags, tokens, scope checks, the operation store and envelopes.

## Before designing commands

Read `.agent/driver/docs/COMMAND-DESIGN.md` and COR-026. Survey the actual application's tasks, resources, interfaces, version and license; preserve sources. Update `registry.json.design` with separate application support, automation reachability, adapter implementation, CLI exposure and actual testing states. Explain the scoped inventory/denominator, deferred/excluded/unknown areas and tree decisions. The `target inspect/apply` paths are placeholders, not a prescribed CRUD tree or proof of application coverage.

Keep capability/task/command/readback/test references closed. A supported task needs critical parameters, hashed implementation entrypoints and actual command/readback evidence bound to the run, source, application version and environment. Unknown, blocked, not_run and contract fixtures cannot count as completed tasks. The checker establishes consistency, not survey exhaustiveness or tree quality.

## Workflow A — add a command

1. Declare it in `registry.json`: path, type, params (with `unit` for quantities), output schema, examples (`--dry-run` / `--confirm` pair for writes, `--dangerous` for dangerous ones) and the `driver` block (effects, phases, modes, maturity, environments, limits, recovery, profiles, error codes).
2. Regenerate with `--update`; fix whatever the generator reports.
3. Implement it in the adapter: `run(call)` for reads; `plan(call)` and `apply(call, plan)` for writes. `plan` must not change the target. `apply` re-checks the baseline (or implement `revision(target)`), dispatches, reads the result back and returns the receipt fields honestly. Raise `DriverError` with the real `dispatch_state` when something fails.
4. Add command-level tests to `tests/test_contract.py`: success, missing or invalid parameters, missing scope, confirmation, conflict, native failure and unknown outcome as they apply. The FCC guard fails when a reference command has no test.
5. Update `CHANGELOG.md` (`Unreleased`) and the Skill (`skills/{{NAME}}/SKILL.md`) if agents need to know.
6. Keep `maturity` at `draft` until a real application or file consumer confirms the behaviour; record that evidence before raising it.

## Workflow B — change an existing command

Read the clause the behaviour belongs to first. Changing a parameter, default, unit, effect or result meaning is a breaking change (DEL-024): bump the version accordingly and say what callers must change.

## Self-check before you finish

- [ ] `check_project.py`, the generator `--check` and the tests pass
- [ ] `python .agent/driver/scripts/check_product_design.py --registry registry.json --require-design` passes; application coverage is reported separately from declared-command FCC
- [ ] every new or changed command has command-level tests, including failure paths
- [ ] no command claims `verified` or `stable` without evidence
- [ ] receipts report what was observed; nothing is assumed saved, delivered or verified
- [ ] CHANGELOG and the Skill describe the change
- [ ] registry version, pyproject, Skill/min_version and generated reference match (`sync_version.py`, then regenerate)
- [ ] publishable readiness has recorded actual multi-model task evaluation; fixtures are not eval evidence
