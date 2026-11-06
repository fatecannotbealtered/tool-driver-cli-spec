# 接入指南：为你的软件做一个驱动工具

[English](ONBOARDING.md) | 中文

本指南写给想要一个驱动工具的团队成员。驱动工具是让 AI Agent 操作专业桌面软件或设备的命令行工具，比如操作 KiCad 的 `kicad-cli`。工具通常由你的 Agent 来开发，你只做必须由人做的决定。

## 你会得到什么

- 一个用 npm 安装的命令行工具，Agent 用它读取和修改软件。每次修改在执行前都先预览、先检查，按风险要求确认，改完后读回核对，并如实汇报：改了什么、存了没有、验证了没有。
- 随工具一起发布的 Agent Skill 和知识库，始终和工具版本一致。
- 一个每次合并都通过规范检查的项目，带一致性测试、行为矩阵和证据，说明每条命令可信到什么程度。
- 一个和其他驱动工具行为一致的工具：Agent 会用一个，就会用所有。

## 你需要准备什么

- Python 3.12 或更高版本
- Node.js 和 npm
- Git，以及给工具用的 GitHub 仓库
- 能使用 Skill 的 Agent，比如 Claude Code
- 运行评测要用 Claude Code，不管开发工具的是哪个 Agent；评测会消耗模型额度
- 装好的软件本身，以及允许自动化操作的许可证
- 负责授权目标的人：由他决定在真实软件上测试时可以用哪些文件、文件夹和设备。通常就是你。
- 发布时，还要有一个 npm 账号或组织来拥有这个包

## 安装开发用 Skill

tool-driver-cli-spec 在 GitHub Releases 上的每个发布包里都有开发用 Skill `build-driver-cli`。它带着你的 Agent 走完下面八步，最后对照规范检查工具。

1. 从 <https://github.com/fatecannotbealtered/tool-driver-cli-spec/releases> 下载 `tool-driver-cli-spec-<version>.zip` 和 `tool-driver-cli-spec-<version>.sha256`。
2. 校验下载的文件：`python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" tool-driver-cli-spec-<version>.zip` 输出的值必须等于 `.sha256` 文件的第一个词。build-driver-cli Skill 做的也是这项校验。值不同就删掉这两个文件，不要使用。
3. 用 `python -m zipfile -e tool-driver-cli-spec-<version>.zip .` 解压。
4. 把 `skills/build-driver-cli/` 复制到 Agent 的 Skill 文件夹，比如 Claude Code 的 `~/.claude/skills/`，或者 `~/.agents/skills/`。

   用 bash：

   ```bash
   mkdir -p ~/.claude/skills
   cp -r tool-driver-cli-spec-<version>/skills/build-driver-cli ~/.claude/skills/
   ```

   用 PowerShell：

   ```powershell
   New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
   Copy-Item -Recurse -Force "tool-driver-cli-spec-<version>\skills\build-driver-cli" "$HOME\.claude\skills\"
   ```

5. 启动 Agent，然后提出请求，比如：「用 build-driver-cli Skill 给 KiCad 做一个驱动工具。」

## 八个步骤一览

| 步骤 | Agent 做什么 | 你做什么 |
|---|---|---|
| 1 调查 | 写能力调查 `docs/APPLICATION.md`：软件能做什么、怎样自动化、有哪些限制和风险 | 回答手册里没写清的问题，读一遍调查 |
| 2 选模式 | 提出用哪些模式：文件模式（直接读写文件）、会话模式（驱动运行中的实例）或设备模式；需要时加宿主组件；支持哪些平台 | 决定模式 |
| 3 生成项目 | 用模板生成项目并检查 | 决定工具名、npm 包名（用你拥有的作用域）、GitHub 仓库和作者 |
| 4 登记命令 | 登记领域命令，每条都能追溯到调查里的能力 | 审一遍命令清单：名字，以及每条命令可以改什么，这决定它怎样确认 |
| 5 实现适配层 | 写和软件打交道的代码 | 不用做什么，除非 Agent 来问 |
| 6 测试 | 在模拟宿主上运行一致性测试，再在真实软件上运行行为矩阵 | 授权目标，并为这些目标写授权范围文件 |
| 7 写 Skill 和知识库 | 写 Skill、知识条目和评测题，并运行评测 | 授权一个评测用的文件夹，审一遍 Skill |
| 8 发布 | 构建并打包，用 `scripts/smoke.py` 在本机做交付测试，准备发布 | 批准合并和发布，推送标签 |

## 授权目标

在真实软件上测试会做出真实的修改，所以只使用你列出的目标。

- 准备专门用来测试的目标：项目的一份副本，或者为测试准备好的设备。不要用正式项目或生产机器。
- 把每个目标列在工具 `docs/E2E.md` 的「Authorized Targets」一节，一个目标占一个列表项：目标写在反引号里，文件或文件夹写成 `file://` URL，设备写成 `device:<id>`，后面跟冒号和说明。这一节是唯一的清单，Agent 从不往里加目标。例如：

  ```markdown
  - `file:///D:/e2e/demo-board/`: a copy of the demo board, made for live runs
  ```

- 软件的实例不列进清单，因为实例没有固定的 ID。为这次运行由你自己启动一个实例，并且只在里面打开清单里的文件。
- 授权范围文件由你自己写，也可以明确让 Agent 代写：它先把内容给你看，你同意后它再写。读它的是工具，不是 Agent：工具从环境变量 `<PREFIX>_SCOPE_FILE` 给出的路径读取它。`<PREFIX>` 是工具名改成大写、把 `-` 换成 `_`，比如 `KICAD_CLI_SCOPE_FILE`。把文件路径告诉 Agent。下面是一个最小的授权范围文件，允许在上面那个文件夹里修改和保存，到设定的时间失效：

  ```json
  {
    "scope_id": "live-runs",
    "effects": ["lifecycle", "change", "persist"],
    "dangerous": false,
    "targets": ["file:///D:/e2e/demo-board/"],
    "expires_at": "2026-12-31T18:00:00Z"
  }
  ```

- Agent 从不写或改授权范围文件，你在对话里要求也不行。写操作因为缺少授权被拒绝时，`E_FORBIDDEN` 错误里带着一段能放行它的片段；Agent 把片段拿给你看，你同意就把它粘贴进文件。完整做法见工具的 `docs/E2E.md`。
- 评测时，列出一个放评测工作区的文件夹，以及评测题的 `SCOPE` 用到的其他目标，比如设备。评测运行器会自己为每道题写授权范围文件。

## 证据与成熟度

每条命令处在 `draft`、`verified` 或 `stable` 之一，`<tool> reference` 会连同证据一起显示。`verified` 要求这条命令的行为矩阵在真实软件上跑通，`stable` 还要求用真实 Agent 做的评测全部通过。证据只对主版本号和次版本号相同的工具版本有效，在模拟宿主上得到的结果从不算证据。

## 发布

- 只有工具仓库里的发布工作流能发布。推送与 `package.json` 版本相同的附注标签 `vX.Y.Z` 后它才启动。它对每个平台包运行全部检查和平台交付测试，全部通过才带来源证明发布到 npm。像 `1.2.0-rc.1` 这样的版本以 npm 标签 `next` 发布。
- 由你或维护者创建 npm 作用域或组织，并把 `merge gate passed` 设为主分支必须通过的检查。首次发布用仓库里的 `NPM_TOKEN` 密钥；首次发布后，为这个包配好可信发布，并禁止用令牌发布。
- 没有你的批准，Agent 从不发布、打标签或推送。它来请你批准时，批准合并，然后自己推送标签，或者在你批准后让 Agent 运行这两条命令：

  ```bash
  git tag -a vX.Y.Z -m "vX.Y.Z"
  git push origin vX.Y.Z
  ```

- 之后用户用 `npm install -g <package>` 安装工具，运行一次 `<tool> update`，再按工具 README 的说明复制它的 Skill。

## 换用新的规范发布

先装上新发布的开发用 Skill：照「安装开发用 Skill」一节，用新发布包里的 `skills/build-driver-cli/` 覆盖你装的那份。然后让 Agent 把工具换到新的发布上。它会钉住新的发布、修好检查报出的问题，再检查一遍工具；不要自己去运行同步。
