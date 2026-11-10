# {{tool}}

{{fill: 一句话定位：本工具让 Agent 在 {{application}} 里做什么}}

<!-- driver:badges:start -->
<!-- driver:badges:end -->

[English](README.md) | 中文

<!-- driver:info-card:start -->
<!-- driver:info-card:end -->

## 安装

1. 从 npm 安装 {{tool}}：

   ```bash
   npm install -g {{package}}
   ```

2. 运行一次 `update`。刚装好的已经是最新版本，所以 `update` 只把命令入口指向原生程序；这样每次调用都不用先启动 Node.js：

   ```bash
   {{tool}} update
   ```

3. 从已安装的包里安装 Skill，Skill 从不从网络获取。把它们复制到 Agent 的 Skill 目录。用 bash：

   ```bash
   mkdir -p ~/.agents/skills
   cp -r "$(npm root -g)/{{package}}/skills/"* ~/.agents/skills/
   ```

   用 PowerShell：

   ```powershell
   New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
   Copy-Item -Recurse -Force "$(npm root -g)\{{package}}\skills\*" "$HOME\.agents\skills\"
   ```

   其他 Agent 的 Skill 目录做法相同。以后运行 `{{tool}} update` 时，这几个目录里的副本会跟着工具一起更新：`~/.agents/skills/`、`~/.claude/skills/`、`~/.codex/skills/`、`~/.cursor/skills/`、`~/.gemini/skills/`。放在别处的副本不会更新。
{{#host_component}}

4. 把宿主组件装进 {{application}}。这是两步确认的写操作，需要允许 `configure` 的授权范围文件（见「授权」）。第一次调用什么都不改，返回预览和确认令牌；第二次调用才安装：

   ```bash
   {{tool}} plugin install
   {{tool}} plugin install --confirm <token>
   ```

   装好后启动或重启 {{application}}，让它加载宿主组件。
{{/host_component}}

## 能力

下面是 {{tool}} 的全部命令，由命令登记生成；`(dangerous)` 表示该命令属于危险级，`{{tool}} reference --command "<path>"` 给出单个命令的完整说明。

<!-- driver:command-map:start -->
<!-- driver:command-map:end -->

## 工作方式

{{tool}} 每次调用都输出一个 JSON 信封。`{{tool}} reference` 列出全部命令，`{{tool}} reference --command "<path>"` 说明单个命令，包括它的参数、效果和在每种模式下的确认级别。
{{#session}}

**实例与文档。** {{tool}} 驱动正在运行的 {{application}} 实例。`{{tool}} session list` 列出每个实例的会话 ID、状态和打开的文档，`{{tool}} doc list` 列出文档。用 `--session <id>` 指定实例，用 `--doc <path-or-id>` 指定文档。有多个实例在运行而命令没有指定时，命令返回 `E_AMBIGUOUS` 和候选列表：{{tool}} 从不按窗口焦点或最近使用来挑实例。`--doc` 指定的文档只有一个实例打开时，就选中这个实例。被某个实例打开的文件只经由这个实例修改，直接写这个文件会被 `E_CONFLICT` 拒绝。
{{/session}}
{{#file}}

**文件。** {{tool}} 直接读写 {{application}} 的文件，不需要运行中的实例。`--doc <path>` 指定文件。
{{/file}}
{{#device}}

**设备。** {{tool}} 通过控制器驱动设备。`{{tool}} device list` 列出每台设备的状态，以及它是不是模拟设备；用 `--device <id>` 指定设备。设备处于 `fault` 或 `emergency_stop` 时需要有人到现场处理：作用于它的命令都返回 `E_HUMAN_REQUIRED`，只有专门停止工作的命令例外。
{{/device}}

**确认级别。** 每次写操作都会检查授权范围、生成预览、在派发前再检查一次状态、锁定目标、读回修改并返回回执。只有确认方式随级别不同，级别由 {{tool}} 根据命令声明的效果得出：

| 级别 | 适用 | 调用方式 |
|---|---|---|
| 直接执行 | 保存之前只在内存里的修改；启动实例；新建和打开文档；不覆盖已有文件的新文件；停止工作 | 一次调用就执行 |
| 两步确认 | 保存和覆盖文件；文件模式和设备模式下的修改；设置；宿主组件 | 第一次调用什么都不改，返回 `E_CONFIRMATION_REQUIRED`，带预览和确认令牌；再带 `--confirm <token>` 运行同一条命令才执行 |
| 危险 | 物理动作；把内容交给外部的人或系统；不可撤回的修改；放弃未保存的修改；关闭不是 {{tool}} 启动的实例 | 与两步确认相同，确认的那次调用还要加 `--dangerous`；授权范围必须允许危险操作 |

`--dry-run` 显示任何写操作的预览，什么都不改。确认令牌只能用一次，10 分钟内有效，而且只对它预览过的那次修改有效。授权范围文件设了 `"confirm": "always"` 时，除停止工作外的所有写操作都改为两步确认，人可以逐个批准预览。
{{#session}}

**会话模式下的保存。** 修改不等于保存。修改之后，回执报告 `persistence: unchanged`，文档仍有未保存的修改；只有 `{{tool}} doc save` 才写入文档的文件。保存的预览列出上次保存以来的所有修改，包括人在 {{application}} 里做的修改（`origin: external`），以及结果仍然未知的写操作。{{application}} 一改就自己存盘的命令按两步确认，回执报告 `persistence: saved`。
{{/session}}
{{#file}}

**文件模式下的保存。** 写文件就是保存：回执报告 `persistence: saved`，{{tool}} 会重新读取文件来验证修改。
{{/file}}
{{#device}}

**设备模式**没有保存这一步：设备立即动作，{{tool}} 从设备读回结果。
{{/device}}

**回执。** 每次写操作都返回回执，分别报告修改是否执行、是否生效、是否送达、是否保存、是否验证。写操作的回复丢失时，{{tool}} 返回 `E_OUTCOME_UNKNOWN` 和查明结果的命令，绝不会把写操作再发一遍。

## 授权

<!-- driver:spec-authorization:start -->
{{tool}} 读取不需要许可，但只写入人在授权范围文件里允许的内容。这个 JSON 文件由人来写；或者人在自己的消息里把目标授予 Agent，由 Agent 把这份授权写成一份自己的授权范围文件，并说明写了什么。没有命令会写这个文件，Agent 也不会因为文档里的要求去写。{{tool}} 从 `{{PREFIX}}_SCOPE_FILE` 指定的路径读取它；没有设置这个变量时，读取状态目录里的 `scope.json`，不从其他任何地方读取。

```json
{
  "scope_id": "demo-rework",
  "effects": ["change", "persist"],
  "dangerous": false,
  "targets": ["file:///D:/projects/demo/"],
  "expires_at": "2027-01-31T18:00:00Z"
}
```

| 字段 | 含义 |
|---|---|
| `scope_id` | 这份授权的名称；操作记录会带上它 |
| `effects` | 写操作可以有的效果；读取不需要授权范围 |
| `dangerous` | 是否允许危险级的操作 |
| `targets` | 写操作可以触及的对象的目标键前缀：`file:///D:/projects/demo/` 覆盖这个文件夹下的所有文件，`untitled:` 覆盖新建的文档，`device:<id>` 覆盖一台设备 |
| `expires_at` | 授权到期的时间，用 UTC |
| `confirm` | 可选；设为 `always` 时，除停止工作外的每个写操作都要等人批准预览后才执行 |

授权范围不覆盖的写操作什么都不改，返回 `E_FORBIDDEN`，说明缺什么，并给出一段人可以直接粘贴进文件的片段。`{{tool}} context` 显示当前生效的授权范围，`SECURITY_zh.md` 完整说明了授权范围。
<!-- driver:spec-authorization:end -->

{{fill: {{tool}} 的命令需要哪些效果、每种效果用于哪些命令，比如用一张效果与命令的表}}

## 关于本工具

{{fill: {{application}} 的领域特点、Agent 用 {{tool}} 完成的典型任务，以及截图或简短示例}}

## 配置

| 变量 | 默认值 | 含义 |
|---|---|---|
| `{{PREFIX}}_STATE_DIR` | `~/.{{tool}}` | 状态目录：操作记录、锁、更新检查的缓存和团队知识的登记 |
| `{{PREFIX}}_SCOPE_FILE` | 状态目录里的 `scope.json` | 授权范围文件（见「授权」） |
| `HTTPS_PROXY`、`HTTP_PROXY`、`NO_PROXY` | 未设置 | `update` 和 `doctor` 用的代理，只有这两个命令访问 npm 仓库 |
| `{{PREFIX}}_FAKE_HOST` | 未设置 | 只用于测试：把每次调用发给模拟宿主而不是 {{application}}，并把每个结果标为模拟结果 |

### 怎样找到 {{application}}

{{fill: {{tool}} 怎样找到 {{application}}：安装位置、版本识别、运行中的实例，以及用户可以修改的设置}}

## 卸载
<!-- driver:spec-uninstall:start -->
{{#host_component}}

先在 {{tool}} 还装着的时候卸载宿主组件。和安装一样，卸载也是两步确认的写操作，需要允许 `configure` 的授权范围。运行中的实例仍在使用的版本会留在磁盘上；关闭 {{application}} 后再运行一次命令即可删除。

```bash
{{tool}} plugin remove
{{tool}} plugin remove --confirm <token>
```
{{/host_component}}

趁 npm 包还在、能列出 Skill 名称时，删除已安装的 Skill。用 bash：

```bash
for skill in "$(npm root -g)/{{package}}/skills/"*; do rm -rf ~/.agents/skills/"$(basename "$skill")"; done
```

用 PowerShell：

```powershell
Get-ChildItem "$(npm root -g)\{{package}}\skills" | ForEach-Object { Remove-Item -Recurse -Force "$HOME\.agents\skills\$($_.Name)" -ErrorAction SilentlyContinue }
```

复制过 Skill 的其他 Agent Skill 目录，如 `~/.claude/skills/`，也照此删除。然后卸载 npm 包：

```bash
npm uninstall -g {{package}}
```

在 Windows 上，如果 npm 全局 `node_modules` 文件夹（`npm root -g`）里有 `.{{tool}}-trash`，也把它删掉；状态目录在另一块磁盘上时，`update` 会把旧的程序文件放在那里，等下次运行再删。

最后删除状态目录：`~/.{{tool}}`，或 `{{PREFIX}}_STATE_DIR` 指定的文件夹。里面有操作记录、锁、默认位置的授权范围文件和团队知识的登记；想保留记录就留着它。

```bash
rm -rf ~/.{{tool}}
```

```powershell
Remove-Item -Recurse -Force "$HOME\.{{tool}}"
```
<!-- driver:spec-uninstall:end -->

## 开发

<!-- driver:spec-development:start -->
{{tool}} 用 Python 写成，建立在 `{{pkg}}/_driver/` 里的驱动运行时之上；这是固定副本，从不修改。领域命令在 `{{pkg}}/commands/`，适配层在 `{{pkg}}/adapter/`。
{{#host_component}}
宿主组件的源码在 `plugin/`。
{{/host_component}}

```bash
python -m pip install --require-hashes --no-deps -r requirements-dev.txt
python scripts/spec.py check
python -m unittest discover -s tests
python scripts/spec.py suites
```

测试和一致性测试都用模拟宿主，从不需要 {{application}}。工作流程、行为矩阵和真实软件运行见 `CONTRIBUTING_zh.md`。
<!-- driver:spec-development:end -->

## 链接

<!-- driver:spec-links:start -->
- 规范：[tool-driver-cli-spec {{spec_version}}](.agent/)，固定副本在 `.agent/`
- [CHANGELOG.md](CHANGELOG.md)：每个版本的改动（英文）
- [SECURITY_zh.md](SECURITY_zh.md)：安全模型，以及怎样报告漏洞
- [CONTRIBUTING_zh.md](CONTRIBUTING_zh.md)：怎样参与贡献
- [docs/APPLICATION_zh.md](docs/APPLICATION_zh.md)：{{application}} 的能力调查
- [docs/COMPATIBILITY_zh.md](docs/COMPATIBILITY_zh.md)：{{tool}} 在哪里能用
- [docs/E2E_zh.md](docs/E2E_zh.md)：真实软件验收及其记录
- 问题跟踪：<https://github.com/{{repo}}/issues>
<!-- driver:spec-links:end -->
