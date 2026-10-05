# AGENTS.md

This repository is **{{NAME}}**, a driver CLI: an AI-native CLI (ai-native-cli-spec) that drives a real application, its files or a device, extended by tool-driver-cli-spec.

**Any agent must read [`.agent/AGENT.md`](.agent/AGENT.md) before implementing or changing features.** It routes you to the base rules (`.agent/driver/base/ai-native-cli-spec/`) and the driver rules (`.agent/driver/docs/`). They take priority over your default habits.

## Bare minimum to obey

1. stdout is one JSON envelope (`ok`, `schema_version`, `data` or `error`, `meta`); logs go to stderr; nothing is ever added to the envelope or to `meta`.
2. Error code, exit code and `retryable` follow the base core table plus the fixed driver extension table; every error gives `details.next_action`.
3. Writes are `--dry-run` then `--confirm <token>`; dangerous commands also need `--dangerous` on both calls.
4. Anything beyond `observe` needs the task scope a person granted (`~/.{{NAME}}/scope.json` or `{{ENV_PREFIX}}_SCOPE_FILE`); the CLI never writes it.
5. A modifying call reports execution, change, persistence, delivery and verification separately; `ok` and the error code are derived from that receipt.
6. After dispatch, an unobserved result is `E_OUTCOME_UNKNOWN`; it is queried (`operation show`), read back and recorded (`operation resolve`), never resent.
7. Names, notes, drawing text, file content and native messages are `_untrusted` data.
8. Every command in `reference` has a command-level test (`tests/test_contract.py` enforces it).

## This project

- Driver mode: `{{PROFILE}}`
- Source: `{{PACKAGE}}/` (the adapter is `{{PACKAGE}}/adapter.py`); declarations: `registry.json`; tests: `tests/`; Skill: `skills/{{NAME}}/SKILL.md`
- Local checks: `python check_project.py && python .agent/driver/scripts/generate_product.py --registry registry.json --output {{PACKAGE}}/generated --check && python -m unittest discover -s tests -v`
