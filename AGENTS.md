# AGENTS.md

English | [中文](AGENTS_zh.md)

This repository holds tool-driver-cli-spec: five specifications, a machine contract and the checks that keep them consistent. Read this file before changing anything.

## Layout

| Path | Content |
|---|---|
| `spec/` | The five specifications, each as an English file and a `_zh` Chinese file |
| `contract/driver-contract.json` | The machine contract: every value a tool or test can read as data |
| `contract/schemas/` | JSON Schemas for envelopes, receipts, scope files, host protocol messages and the contract itself |
| `contract/examples/` | `valid/<schema>/` examples that must pass and `invalid/<schema>/` examples that must fail |
| `sdk/python/_driver/` | The driver runtime every tool copies unchanged; Python standard library only |
| `conformance/fakehost/` | The fake host and reference implementation of the host protocol; Python standard library only |
| `conformance/suites/` | The general and driver conformance suites; they start a tool as a process against the fake host |
| `conformance/eval/` | The evaluation questions of every scenario, each with a grader and a right and a wrong scripted agent |
| `template/` | The project template; `{{name}}` marks a value `instantiate` fills in, `{{fill: ...}}` a text the tool author writes |
| `scripts/check_spec.py` | Checks clause format, numbering, language pairs, contract tables, schemas and examples |
| `scripts/build_spec_bundle.py` | Builds the release ZIP and its SHA-256 file |
| `scripts/instantiate.py`, `sync_spec.py`, `check_project.py`, `run_matrix.py`, `run_eval.py` | The scripts tool projects run from the release bundle: generate a project, pin a release, check a project and write its generated content, run a behavior matrix on the real application, run evaluation questions with an Agent |
| `skills/build-driver-cli/` | The development Skill: guides an Agent through the onboarding steps of DREPO-062 and reviews a tool; ships in the release bundle |
| `docs/ONBOARDING.md` | The onboarding guide for a person who wants a new driver tool, with `ONBOARDING_zh.md` |
| `docs/OPEN-QUESTIONS.md` | Open questions; the specifications never contain them |
| `tests/` | Unit tests for the scripts, the fake host and the runtime; `tests/sample/` is the sample tool the suites run against; `tests/e2e_template.py` runs the template end to end; `tests/eval_template.py` runs the evaluation suite with the template tool |

## Changing the specification

1. Change the contract first when a value changes (an error code, a flag, a state, a field). Then change the matching table in both language files.
2. Keep the English file and the `_zh` file in step: same sections, same clause IDs in the same order, same tables with the same number of rows.
3. Run the checks below. All must pass before a commit.

```bash
python scripts/check_spec.py
python -m unittest discover -s tests -v
cd conformance && python -m suites --project ../tests/sample -- python -m sample_cli
```

A change to the runtime, the template or the project scripts also runs `python tests/e2e_template.py`, with the dependencies of `template/requirements-dev.txt` and npm. A change to the runtime, the fake host, the Skill template, `scripts/run_eval.py`, the question checks of `check_project` or the evaluation questions also runs `python tests/eval_template.py`.

## Clause format

Every rule is a clause:

```markdown
### DCLI-202 Selecting a session

When several instances are running and the command has no `--session`, the command MUST return `E_AMBIGUOUS` with the candidates. It MUST NOT pick an instance by window focus or by recent use. With exactly one instance it MAY pick it and MUST name it in the output.

Why: With two projects open, picking by focus changes the wrong project.
Check: 🤖 Driver conformance test D01.
```

- The heading is `### <PREFIX>-<NNN> <Title>` with a three-digit number.
- The body uses MUST, MUST NOT, SHOULD, SHOULD NOT and MAY in English, and 必须, 禁止, 应该, 不应该 and 可以 in Chinese. Every clause has at least one of them.
- The clause ends with two lines: `Why:` and `Check:` in English, `为什么：` and `检查：` in Chinese.
- The check line starts with 🤖 when a test or script checks the clause, and with 👀 when a person checks it in review. Name the test (`G03`, `D01`) or the script (`check_project`).
- A clause states one rule, or a few rules that belong together. Keep sentences short and plain.

## Document skeleton

Each specification file has these parts, in this order:

1. `# <NAME>` and the language switch line: `English | [中文](<NAME>_zh.md)` or `[English](<NAME>.md) | 中文`.
2. The version line: `> Version <VERSION> · Clauses <first ID> to <last ID>` (Chinese: `> 版本 <VERSION> · 条款 <first ID> 至 <last ID>`).
3. `## How to Read` (`## 怎么读`): the meaning of the normative words, and that the contract wins when a table and the contract disagree.
4. `## Scope` (`## 适用范围`) and `## Terms` (`## 术语`).
5. `## Runtime and Tool Responsibilities` (`## 运行时与工具的分工`): a table of what the driver runtime already provides and what the tool author still does.
6. One `##` section per numbering segment, holding the clauses in ascending order.
7. `## Checklist` (`## 检查清单`): one line per clause, `- [ ] <ID> <Title>`, in the same order and with the same titles.

## Numbering

- Numbers are grouped in segments of ten; `contract/driver-contract.json` lists the segments of each specification under `spec_documents`. Leave gaps so later clauses can be inserted.
- A published number never changes and is never reused. A removed clause keeps its heading with one line saying where its rule went.
- Refer to other rules only by clause ID, such as `DSEC-015`.

## Contract tables

A table that repeats contract values is marked with a comment on the line before it:

```markdown
<!-- contract:error_codes -->
| Code | Exit | Retryable | Meaning |
|---|---|---|---|
| `E_USAGE` | 2 | no | ... |
```

- The first cell of each row starts with the key in backticks, in contract order. Text may follow the key in the same cell.
- `check_spec.py` compares the keys, and for some tables more columns, with the contract. The marker names and the contract values they mirror are listed in `MARKERS` in `scripts/check_spec.py`.
- Each marker appears exactly once in the English files and once in the Chinese files.

## Language and style

- The English file is the main file. The Chinese file says the same thing in natural Chinese; it is not a word-for-word translation.
- In Chinese text, put a space between Chinese and English words or numbers, as in `Agent 动手`.
- Write each document as a complete, standalone description of the rule. Do not cite outside documents, earlier versions or history.
- Use these terms:

| English | 中文 |
|---|---|
| driver tool | 驱动工具 |
| driver runtime | 驱动运行时 |
| adapter (layer) | 适配层 |
| host component | 宿主组件 |
| host protocol | 宿主协议 |
| fake host | 模拟宿主 |
| session, instance | 会话、实例 |
| document | 文档 |
| long job | 长任务 |
| effect | 效果 |
| confirmation tier: direct, two-step, dangerous | 确认级别：直接执行、两步确认、危险 |
| risk tier | 风险等级 |
| authorization scope, scope file | 授权范围、授权范围文件 |
| target key | 目标键 |
| dry run | 预演 |
| preview | 预览 |
| confirm token | 确认令牌 |
| confirm-time review | 确认时的复查 |
| read-back | 读回 |
| receipt | 回执 |
| operation record | 操作记录 |
| outcome unknown | 结果未知 |
| state directory | 状态目录 |
| untrusted content | 不可信内容 |
| built-in command, standard command, domain command | 内置命令、标准命令、领域命令 |
| conformance test | 一致性测试 |
| behavior matrix | 行为矩阵 |
| maturity, evidence | 成熟度、证据 |
| entry Skill, domain Skill | 入口 Skill、领域 Skill |
| command map, write recipe, STOP checkpoint, playbook | 命令地图、写入配方、STOP 检查点、剧本 |
| builtin knowledge, team knowledge | 内置知识、团队知识 |
| capability survey | 能力调查 |
| platform package, launcher, command entry | 平台包、启动器、命令入口 |
| provenance | 来源证明 |
| live acceptance | 真实软件验收 |

## Rules for this repository

- Work on a branch and merge through a pull request. Publishing, tagging and pushing need the maintainer's explicit approval.
- Every released change gets a new version, an annotated tag and a CHANGELOG entry. One version number has one content.
- Before each release, run `python tests/eval_template.py --agent claude --report <file>`. Every question must pass with the real Agent, and the report is attached to the release.
- Never commit secrets, real license data or project files you are not allowed to share.
- Tests against real applications run only on authorized targets and workspaces. The checks in this repository never need a real application.
- Scripts and tests that start subprocesses on Windows use `CREATE_NO_WINDOW`.
- Check the working tree before committing and keep other people's changes.
