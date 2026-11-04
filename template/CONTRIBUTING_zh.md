# 参与 {{tool}} 的贡献

[English](CONTRIBUTING.md) | 中文

人和编程 Agent 都按同样的流程贡献。编程 Agent 还要遵守 `AGENTS_zh.md`。

## 开发环境

需要准备：

- Python 3.12 或更新版本
- Node.js 和 npm，用来构建和测试 npm 包
- Git

测试和一致性测试从不需要 {{application}}：模拟宿主代替它。只有在授权目标上做真实软件运行时才需要 {{application}}（见 `docs/E2E_zh.md`）。

克隆仓库：

```bash
git clone https://github.com/{{repo}}.git
```

然后在克隆下来的文件夹里创建虚拟环境、安装开发依赖，再运行项目检查：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes --no-deps -r requirements-dev.txt
python scripts/spec.py check
```

在 Windows 上改用 `.venv\Scripts\activate` 激活环境。`requirements-dev.txt` 为每个开发依赖固定了版本和哈希，装上的只会是审过的版本。

## 常用命令

| 命令 | 作用 |
|---|---|
| `python scripts/spec.py check` | 运行项目检查：布局、文档及其固定原文、生成的内容、固定副本、版本、Skill、知识、行为矩阵、证据和成熟度 |
| `python scripts/spec.py generate` | 重新生成 `contract/commands.json`、命令地图、徽章行、信息卡、风险块、支持矩阵、证据索引和 `knowledge/index.json` |
| `python scripts/spec.py suites` | 用模拟宿主代替 {{application}}，对 {{tool}} 运行两套一致性测试 |
| `python scripts/spec.py sync <version>` | 用 tool-driver-cli-spec 另一个发布里的副本替换固定副本 |
| `python scripts/spec.py matrix --command "<path>" --set <placeholder>=<value>` | 在真实的 {{application}} 上、在授权目标上运行一个命令的行为矩阵，并写下真实软件记录 |
| `python -m unittest discover -s tests` | 运行单元测试 |
| `python scripts/build.py` | 为本机构建原生程序和平台包 |
| `python scripts/pack.py` | 构建 npm 包，并做包内容检查 |
| `python scripts/smoke.py` | 对构建好的包运行平台交付的关键操作 |

固定副本是 `.agent/`、`contract/driver-contract.json`、`{{pkg}}/_driver/` 和 `licenses/`。禁止修改它们；`sync` 会把它们一起替换。

## 分支与提交约定

- `main` 始终能通过合并门槛。在分支上工作，通过合并请求合入。
- 分支命名为 `<kind>/<topic>`，kind 取 `feat`、`fix`、`docs`、`test` 或 `chore`，例如 `feat/part-move`。
- 提交信息用英文：先是一行不超过 72 个字符的祈使句标题，如 `Add part move`，空一行，再在正文里说明原因。
- 每个提交只做一件事，连同它的测试、行为矩阵、两种语言的文档和 CHANGELOG 条目一起提交。
- 只有维护者才能发布。发布时在 `package.json` 里设新版本（这是版本号的唯一来源），把 `[Unreleased]` 下的条目移进 `[X.Y.Z] - YYYY-MM-DD` 一节。合入后，维护者推送附注标签 `vX.Y.Z`，剩下的由发布工作流完成。

## CI 检查

`.github/workflows/ci.yml` 对每次改动运行合并门槛。任何一项检查失败，都会挡住合并和发布。

| 检查 | 检查什么 | 本地怎样运行 |
|---|---|---|
| Lint | 工具的代码风格规则 | `python -m ruff check .` |
| 单元测试 | `tests/` 里工具自己的测试 | `python -m unittest discover -s tests` |
| 一致性测试 | 两套测试，在每个出包平台上运行 | `python scripts/spec.py suites` |
| 项目检查 | 布局、文档、标签、固定副本、Skill、知识和能力对应 | `python scripts/spec.py check` |
| 输出大小检查 | 每个信封都在大小上限之内；由通用一致性测试 R04 执行 | `python scripts/spec.py suites` |
| npm 包内容检查 | 每个包只含允许的内容，没有安装脚本 | `python scripts/pack.py` |

`.github/workflows/release.yml` 只在维护者推送版本标签时运行。它先跑同样的检查，再做平台交付：在每个平台包对应的操作系统和 CPU 上，把将要发布的包装进干净的环境，启动 {{tool}}，运行一个关键操作，做法与 `python scripts/smoke.py` 相同。只有所有平台包都全部通过，它才带着来源证明发布到 npm。

## 测试与证据

**一致性测试。** `python scripts/spec.py suites` 运行通用和驱动两套一致性测试。它们设好 `{{PREFIX}}_FAKE_HOST`，把 {{tool}} 作为独立进程启动，由模拟宿主代替 {{application}}，只根据退出码、输出和模拟宿主收到的内容做判断。禁止跳过、削弱或修改测试，也禁止把测试标为预期失败；适用却没有运行的测试算作失败。模拟宿主给出的是模拟结果，从不算作证据。

**单元测试。** 工具自己的测试放在 `tests/`。每个测试都把 `{{PREFIX}}_STATE_DIR` 设为新建的临时目录，并且要么把 `{{PREFIX}}_SCOPE_FILE` 指向这个目录里的授权范围文件，要么去掉这个变量。

**行为矩阵。** 每个领域命令，以及每个调用适配层能力的标准命令，都在 `tests/matrix/` 里有一个矩阵文件，以命令路径命名，如 `tests/matrix/part-move.json`。文件把每一行各列一次：`normal`、`empty`、`invalid_input`、`not_found`、`ambiguous`、`conflict`、`no_scope`、`busy`、`dialog`、`disconnect`、`unsaved` 和 `read_back_mismatch`。适用的行写明参数和预期的退出码与错误码；不适用的行写 `applies: false` 和原因。写命令 `normal` 行的参数就是它的样例，通用一致性测试会拿它在模拟宿主上运行。参数只通过占位符 `{session}`、`{doc}`、`{device}` 和 `{dir}` 指定会话、文档、设备和输出文件夹。

**真实软件记录。** `python scripts/spec.py matrix --command "<path>" --set <placeholder>=<value>` 在真实的 {{application}} 上运行一个矩阵，矩阵用到的每个占位符各给一个 `--set`，占位符名不带花括号，如 `--set doc=<file>`；每个值都必须是授权目标。它把真实软件记录写进 `docs/evidence/`，并填上每一行的实际结果和 `live:` 证据引用。具体步骤见 `docs/E2E_zh.md`。无法按需制造的行，如 `disconnect`，可以标为 `unrunnable` 并写明原因；`normal`、`dialog` 和 `read_back_mismatch` 这三行不可以。

**评测。** 命令标为 stable 之前，`tests/eval/` 里要有覆盖它的评测题，评分程序根据 {{application}} 或文件里的真实结果判定；`docs/evidence/` 里还要有一份当前的评测报告 `eval-<date>.json`。

**成熟度。** 每个命令都声明自己的成熟度和背后的证据，`{{tool}} reference` 会显示这两项。

| 级别 | 需要的证据 |
|---|---|
| `draft` | 不需要；但写命令仍要有样例 |
| `verified` | 一份当前的真实软件记录，矩阵中适用的每一行都通过，标为 `unrunnable` 的行除外 |
| `stable` | 另加一份当前的评测报告 |

证据只在它记录的工具版本与 {{tool}} 的主版本和次版本都相同时才算数；出了新的次版本或主版本后，命令要有新证据才能保住原来的级别。证据引用的格式是 `live:docs/evidence/<file>.json#<row>` 或 `eval:docs/evidence/eval-<date>.json`。

## 新增或修改命令

1. **调查。** 在 `docs/APPLICATION_zh.md` 的能力表里找到这项能力。没有时，加一行并给它新的 `CAP-nnn`。有命令提供它之后，把处置改为 `provided`。
2. **命名。** 用 `noun verb` 的形式。动词从固定列表里选：`list`、`get`、`search`、`check`、`create`、`update`、`delete`、`move`、`import`、`render`、`export`、`run`、`stop`。名词用 {{application}} 自己的术语，写成完整的英文单词。名词不能用内置命令或标准命令的名称，如 `session`、`doc` 或 `job`。
3. **登记。** 在 `{{pkg}}/commands/` 里登记命令，写明说明、效果、模式、目标类型、参数及其类型、每个物理量的单位量、机密参数、输出中的不可信字段、调用的适配层能力，以及 `survey_ids` 里的能力编号。每个效果都要声明。{{application}} 无法撤回的修改标 `irreversible: true`，只用来停止工作的命令标 `halt: true`。{{application}} 会取整或吸附数值的地方，给出读回容差；相关的知识条目写在 `related_knowledge` 里。
4. **实现。** 在 `{{pkg}}/adapter/` 里实现命令需要的适配层能力；{{application}} 的接口只能在它的进程里或主线程上调用时，写在 `plugin/` 的宿主组件里。禁止重新实现驱动运行时已经做的事。
5. **矩阵。** 在 `tests/matrix/` 里写行为矩阵，每一行都要有。写命令的 `normal` 行就是它的样例。
6. **生成与检查。** 运行 `python scripts/spec.py generate`，再运行 `python scripts/spec.py check`、`python -m unittest discover -s tests` 和 `python scripts/spec.py suites`。
7. **证明。** 命令一开始是 `draft`。用 `python scripts/spec.py matrix` 在真实的 {{application}} 上、在授权目标上运行它的矩阵，并提交真实软件记录，命令就可以标为 `verified`。只要改动影响到命令与 {{application}} 的交互，就重新运行矩阵。
8. **Skill 与知识。** 命令地图会自动更新。命令对应的任务需要好几步时，在拥有这个命令的 Skill 里加一个剧本。入口 Skill 要超过 150 行时，按用户所说的任务拆成领域 Skill，每个都在 `metadata.commands` 里列出自己的命令。把发现的限制和错误写成 `knowledge/` 里的条目。
9. **CHANGELOG。** 在 `[Unreleased]` 下加一条：新命令或新参数用 `Added`，行为变化用 `Changed`，以后要删除的用 `Deprecated`，已经删除的用 `Removed`，缺陷修复用 `Fixed`，漏洞修复用 `Security`。

## 合并请求

- 一个合并请求只做一件事。描述里写明改了什么、为什么改，列出涉及的命令和能力编号，并附上新的真实软件记录或评测报告的链接。
- 所有 CI 检查都通过，生成的内容重新生成，不手改。
- 英文和中文文档一起改，内容一致。
- 代码、测试和 `docs/evidence/` 里都不能有机密、许可证数据或无权分享的文件。
- 评审者对照能力调查检查声明的效果，以及 `irreversible` 和 `halt` 标记，并检查不可信字段、Skill 文字，以及矩阵中不适用或无法运行的行所给的原因。
- 由维护者合入。包只由发布工作流发布。

## 安全

不要在公开的 Issue 或合并请求里报告漏洞。请按 `SECURITY_zh.md` 的说明，通过 <https://github.com/{{repo}}/security/advisories/new> 私下报告。
