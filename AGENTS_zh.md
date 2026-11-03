# AGENTS.md

[English](AGENTS.md) | 中文

本仓库是 tool-driver-cli-spec：五份规范、一份机器契约，以及让它们保持一致的检查。改任何东西之前先读本文。

## 目录

| 路径 | 内容 |
|---|---|
| `spec/` | 五份规范，每份一个英文文件和一个 `_zh` 中文文件 |
| `contract/driver-contract.json` | 机器契约：工具或测试能当作数据读取的每一个值 |
| `contract/schemas/` | 信封、回执、授权范围文件、宿主协议报文和契约本身的 JSON Schema |
| `contract/examples/` | `valid/<schema>/` 是必须通过的示例，`invalid/<schema>/` 是必须不通过的示例 |
| `sdk/python/_driver/` | 驱动运行时，每个工具原样复制；只用 Python 标准库 |
| `conformance/fakehost/` | 模拟宿主，也是宿主协议的参考实现；只用 Python 标准库 |
| `conformance/suites/` | 通用和驱动两组一致性测试；以进程方式启动工具，接模拟宿主 |
| `scripts/check_spec.py` | 检查条款格式、编号、中英文对应、契约表格、Schema 和示例 |
| `scripts/build_spec_bundle.py` | 生成发布用的 ZIP 和它的 SHA-256 文件 |
| `docs/OPEN-QUESTIONS.md` | 开放问题；规范正文里不放开放问题 |
| `tests/` | 脚本、模拟宿主和运行时的单元测试；`tests/sample/` 是一致性测试所测的示例工具 |

## 修改规范

1. 改到某个值（错误码、参数、状态、字段）时，先改契约，再改两种语言文件里对应的表格。
2. 英文文件和 `_zh` 文件同步：章节相同，条款编号相同且顺序相同，表格相同且行数相同。
3. 运行下面的检查，全部通过才能提交。

```bash
python scripts/check_spec.py
python -m unittest discover -s tests -v
cd conformance && python -m suites --project ../tests/sample -- python -m sample_cli
```

## 条款格式

每条规则是一条条款：

```markdown
### DCLI-202 选定会话

有多个运行中的实例且命令没有指定 `--session` 时，命令必须返回 `E_AMBIGUOUS` 并列出候选，禁止按窗口焦点或最近使用顺序选择。只有一个实例时可以自动选中，并且必须在输出中写明所选的实例。

为什么：同时开着两个工程时，按焦点选择会改错工程。
检查：🤖 驱动一致性测试 D01。
```

- 标题是 `### <前缀>-<三位编号> <名称>`。
- 正文用规范用词：英文是 MUST、MUST NOT、SHOULD、SHOULD NOT、MAY，中文是必须、禁止、应该、不应该、可以。每条条款至少有一个。
- 条款以两行结尾：英文是 `Why:` 和 `Check:`，中文是 `为什么：` 和 `检查：`。
- 由测试或脚本检查的，检查行以 🤖 开头；由人在评审时检查的，以 👀 开头。写明是哪项测试（`G03`、`D01`）或哪个脚本（`check_project`）。
- 一条条款说一条规则，或几条紧密相关的规则。句子要短、要直白。

## 文档骨架

每份规范文件按下面的顺序组织：

1. `# <名称>` 和语言切换行：`English | [中文](<名称>_zh.md)` 或 `[English](<名称>.md) | 中文`。
2. 版本行：`> Version <VERSION> · Clauses <第一条> to <最后一条>`（中文为 `> 版本 <VERSION> · 条款 <第一条> 至 <最后一条>`）。
3. `## How to Read`（`## 怎么读`）：规范用词的含义；表格与契约不一致时以契约为准。
4. `## Scope`（`## 适用范围`）和 `## Terms`（`## 术语`）。
5. `## Runtime and Tool Responsibilities`（`## 运行时与工具的分工`）：一张表，列出驱动运行时已经提供什么、工具作者还要做什么。
6. 每个编号段一个 `##` 章节，条款按编号从小到大排列。
7. `## Checklist`（`## 检查清单`）：每条条款一行，`- [ ] <编号> <名称>`，顺序和名称与条款一致。

## 编号

- 编号按十位分段；每份规范的编号段列在 `contract/driver-contract.json` 的 `spec_documents` 里。段与段之间留空号，方便以后插入。
- 编号一经发布就不再改动、不再复用。删除的条款保留标题，写一行说明它的规则移到了哪里。
- 引用别的规则只写条款编号，比如 `DSEC-015`。

## 契约表格

重复契约内容的表格，在表格前一行加注释标记：

```markdown
<!-- contract:error_codes -->
| Code | Exit | Retryable | Meaning |
|---|---|---|---|
| `E_USAGE` | 2 | no | ... |
```

- 每行第一格以反引号括起的键开头，顺序与契约一致；键后面可以接说明文字。
- `check_spec.py` 把这些键（有的表格还包括其他列）与契约核对。标记名和它对应的契约内容，见 `scripts/check_spec.py` 里的 `MARKERS`。
- 每个标记在英文文件里只出现一次，在中文文件里也只出现一次。

## 语言与写法

- 英文文件是主文件。中文文件用自然的中文表达同样的内容，不逐字翻译。
- 中文里，中文与英文单词或数字之间加一个空格，如 `Agent 动手`。
- 每份文档都要把规则完整、独立地写清楚，不引用外部文档、旧版本或历史。
- 术语按下表使用：

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

## 本仓库的规则

- 在分支上开发，通过 PR 合并。发布、打标签和推送需要维护者明确同意。
- 每次发布的变化都形成新版本，打带注释的标签，写进 CHANGELOG。一个版本号只对应一份内容。
- 不得提交密钥、真实许可数据，或无权分享的工程文件。
- 对真实软件的测试只在已授权的目标和工作区里进行。本仓库的检查从不需要真实软件。
- 在 Windows 上启动子进程的脚本和测试使用 `CREATE_NO_WINDOW`。
- 提交前检查工作树，保留别人的改动。
