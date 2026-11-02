# DRIVER-CLI-SPEC

[English](DRIVER-CLI-SPEC.md) | 中文

> 版本 1.0.0-rc.1 · 条款 DCLI-001 至 DCLI-281

## 怎么读

本规范规定驱动工具在命令行上的行为：输出什么、怎样报错、命令怎么命名、怎样写入、怎样自更新，以及怎样连接它所驱动的软件。

用词的含义：

- 必须、禁止：硬性要求。违反的工具不符合本规范。
- 应该、不应该：默认做法。只有说得出理由时才偏离。
- 可以：允许，但不要求。

每条条款有固定编号（如 DCLI-202）、标题、规则正文，以及「为什么：」和「检查：」两行。🤖 表示由测试或脚本检查，👀 表示由人在评审时检查。G00 至 G10、R01 至 R06 是通用一致性测试，D01 至 D23 是驱动一致性测试。引用其他规则时只写条款编号，如 DSEC-015。

标有 `<!-- contract:NAME -->` 的表格重复机器契约 `contract/driver-contract.json` 里的值。这类表格与契约不一致时，以契约为准。

## 适用范围

本规范适用于驱动工具：让 AI Agent 操作专业桌面软件（如 CAD、EDA、仿真软件）和设备（如机床、仪器）的命令行工具。Agent 调用工具；人通过授权范围文件决定 Agent 能改什么。

内容包括：

- 输出信封、错误和退出码；
- 命令名、参数和目标键；
- 内置命令和驱动标准命令；
- 写操作流程：确认级别、预览、确认令牌、读回、回执和操作记录；
- 自更新；
- 单位和坐标；
- 驱动模型：模式、会话、文档、长任务、设备和宿主组件；
- 适配接口、驱动运行时和宿主协议。

本规范不规定领域命令具体做什么（比如怎么布线），只规定它们的命名和形式。本规范不覆盖调用云端服务接口的工具，不提供多步工作流命令，也不涉及跨机器驱动软件。

## 术语

| 术语 | 含义 |
|---|---|
| Agent | 代替人调用工具的 AI |
| 驱动工具 | 让 Agent 操作桌面软件或设备的命令行工具 |
| 软件 | 工具所驱动的桌面软件 |
| 实例、会话 | 实例是软件的一个运行中的副本。会话是工具对一个实例的引用，有会话 ID |
| 文档 | 在实例里打开的文件；文件模式下是工具直接读写的文件 |
| 驱动运行时 | 共享代码，实现信封、内置命令和标准命令、写操作流程和自更新；每个工具原样复制 |
| 适配层 | 工具作者为某个软件实现适配能力（DCLI-260）的代码 |
| 宿主组件 | 装进软件、在软件里运行的那部分工具，比如插件、加载项、脚本服务 |
| 宿主协议 | CLI 与宿主组件之间的本机协议（DCLI-270 至 DCLI-281） |
| 模拟宿主 | 为一致性测试模拟软件、实例和设备的小程序 |
| 信封 | 命令写到 stdout 的那一个 JSON 对象 |
| 效果 | 命令做的是哪一类改动，如 `observe`、`change`、`physical`（DCLI-051） |
| 确认级别 | 写操作怎样确认：直接执行、两步确认或危险（DCLI-052） |
| 风险等级 | T0、T1 或 T2：命令可能造成多大损害（DSEC-001） |
| 授权范围、授权范围文件 | 人允许的效果和目标，写在授权范围文件里（DSEC-010 至 DSEC-017） |
| 目标键 | 对象身份的唯一写法（DCLI-028） |
| 预演、预览 | 带 `--dry-run` 运行，什么都不改，返回这次改动的预览 |
| 确认令牌 | 随预览一起给出的签名令牌，只能用一次，让同一个写操作执行一次（DCLI-055） |
| 确认时的复查 | 写操作执行前，运行时再做一遍的检查（DCLI-056） |
| 派发 | 把修改发给软件或设备 |
| 读回 | 派发后重新读取被改的字段，以核实修改 |
| 回执 | 写操作的报告，按五个维度分别说明结果（DCLI-061） |
| 操作记录 | 一次写操作的留存记录，ID 以 `op_` 开头（DCLI-059） |
| 结果未知 | 写操作可能生效了，也可能没有（DCLI-063） |
| 长任务 | 超出单次调用应有时长的工作；工具返回一个任务，供 Agent 查询（DCLI-065） |
| 状态目录 | 工具按用户存放密钥、记录、锁和缓存的目录（DSEC-030） |
| 不可信内容 | 来自文档、软件或工具之外的文字，一律不当成指令（DSEC-020） |
| 内置命令、标准命令、领域命令 | 运行时为每个工具实现的命令（DCLI-030）；运行时依据适配能力实现的命令（DCLI-200）；工具作者自己写的命令 |
| 一致性测试 | 运行时提供的测试套件：通用测试 G00 至 G10、R01 至 R06，驱动测试 D01 至 D23 |
| 成熟度、证据 | 命令被证明到什么程度，以及证明它的记录（DVER-040） |
| 平台包、启动器、命令入口 | 装着某个平台原生程序的 npm 包；npm 主包里的启动脚本；npm 放到 PATH 上用来启动工具的文件 |
| 来源证明 | 证明 npm 包由本工具发布工作流构建的签名声明 |

## 运行时与工具的分工

| 方面 | 驱动运行时已经提供 | 工具作者还需要做 |
|---|---|---|
| 输出与错误 | 信封、错误对象、退出码、列表分页、大小限制、状态到错误码的映射 | 领域结果数据；把软件自己的报错原文放进 `native_message`；声明哪些结果字段是不可信内容（DSEC-021） |
| 命令 | 参数解析，全局、共享和目标参数，目标键规范化 | 登记领域命令：名词、动词、效果、单位、目标类型、能力编号（DREPO-061）、成熟度和证据 |
| 内置命令 | `reference`、`context`、`doctor`、`changelog`、`operation`、`update`、`--version`、`--help` | 提供 npm 包名和 CHANGELOG |
| 标准命令 | `session`、`doc`、`job`、`device`、`knowledge` 和 `plugin` 命令 | 实现它们调用的适配能力（DCLI-260） |
| 写操作 | 授权范围检查、确认分级、预览与令牌、确认时的复查、操作记录与锁、回执与 `ok` 的推导、批量操作、长任务查询 | 实现 `preview`、`apply` 和 `read_back`；为每个领域写命令提供一个有效样例（DVER-002） |
| 单位 | 解析参数里的单位，换算成标准单位 | 为每个物理量参数和输出字段声明单位；在适配层里换算成软件的单位 |
| 自更新 | `update`、更新提示、命令入口、Skill 同步 | 除 npm 包名外无需再做什么 |
| 宿主组件 | 宿主协议的 CLI 端；已提供的宿主端库 | 用软件支持的语言编写宿主组件 |
| 测试 | 通用和驱动两组一致性测试、模拟宿主 | 在真实软件上跑行为矩阵，做真实软件验收 |

## 输出

### DCLI-001 stdout 上只有一个信封

在默认的 `--format json` 下，命令必须向 stdout 写恰好一个 JSON 信封，后面跟一个换行，此外什么都不写。进度、警告和诊断必须写到 stderr。stderr 不是终端时，禁止写进度条、动画和横幅。`--quiet` 必须关掉 stderr 上除错误以外的全部输出。

为什么：Agent 把 stdout 当作一个 JSON 文档解析，多出一行就会解析失败，白白浪费一次调用。
检查：🤖 通用一致性测试 R04 校验测试中见到的每一个信封。

### DCLI-002 输出格式

`--format` 取以下值之一：

- `json`：默认格式，也是给 Agent 的唯一格式。
- `text`：给人看。不同版本之间可以变化；Agent 和脚本禁止解析它。
- `raw`：只限声明了它的命令，比如导出日志或文件内容。必须按字节原样输出。

`--json` 必须等同于 `--format json`。JSON 默认必须紧凑输出；`--pretty` 加缩进，给人看。命令不支持的格式必须返回 `E_USAGE`。

为什么：只有一种机器格式，Agent 读所有工具的方式都一样；会变化的文本格式只有在没人解析时才安全。
检查：🤖 运行时单元测试。

### DCLI-003 信封的键

成功信封必须恰好有 `ok`、`schema_version`、`data`、`meta` 四个键；失败信封必须恰好有 `ok`、`schema_version`、`error`、`meta` 四个键。失败时禁止返回 `data`。`schema_version` 必须是由本规范的主版本号和次版本号组成的字符串：所有 1.0.x 版本都是 `"1.0"`。

成功：

```json
{"ok":true,"schema_version":"1.0","data":{"id":"doc_1","path":"D:/proj/board.kicad_pcb","session":"kicad-1234","revision":7,"dirty":true,"readonly":false,"state":"dirty"},"meta":{"duration_ms":38}}
```

失败：

```json
{"ok":false,"schema_version":"1.0","error":{"code":"E_BUSY","message":"KiCad is running a design rule check; nothing was sent.","retryable":true,"details":{"dispatch_state":"not_started","next_action":"Wait 5 s, then run the same command again.","retry_after_ms":5000}},"meta":{"duration_ms":120}}
```

为什么：键固定后，Agent 先看 `ok`，再到一个确定的位置读结果或错误。
检查：🤖 通用一致性测试 R04。

### DCLI-004 meta

`meta` 必须只有以下三个键：

- `duration_ms`：每个信封都有；运行耗时，整数毫秒。
- `notices`：提示列表，每条为 `{type, severity, message}`，`severity` 取 `info` 或 `warning`。更新提示（DCLI-079）就是一例。为空时省略。
- `untrusted`：信封中存放不可信内容的 JSON 路径列表（DSEC-021）。为空时省略。

为什么：在每个工具里，Agent 都在同一个位置找到耗时、提示和不可信标记。
检查：🤖 通用一致性测试 R04。

### DCLI-005 命名与取值

- 所有键必须用 snake_case，`data` 和 `details` 里的键也一样。
- ID 必须是字符串。
- 时间必须是带 `Z` 后缀的 ISO 8601 UTC 时间，放在以 `_at` 结尾的键下；不带时刻的日期必须放在以 `_on` 结尾的键下。
- 枚举值必须用小写 snake_case。
- 物理量的键名带单位后缀，如 `x_mm`、`angle_deg`，具体要求见 DCLI-081。

为什么：只有一套命名规则，Agent 不用猜键名怎么拼、时间是哪个时区、数值是什么单位。
检查：🤖 通用一致性测试 R04。

### DCLI-006 列表

返回列表的命令必须返回 `items`、`count`（本页条数）和 `has_more`。知道总数时必须另给 `total`；`has_more` 为 `true` 时必须另给 `next_offset`。没有匹配时必须返回空的 `items`，`ok` 为 `true`，禁止返回 `E_NOT_FOUND`。

为什么：Agent 用同一种方式翻页，并能分清「没有匹配」和「目标不对」。
检查：🤖 通用一致性测试 R04 检查列表的键；行为矩阵（DVER-030）的「空结果」一行覆盖空列表的情况。

### DCLI-007 默认字段

每个列表命令必须声明默认字段，按 Agent 对这类对象最常问的问题来选。`--fields a,b` 必须只返回指定的字段，`--fields all` 必须返回全部字段。

为什么：默认结果简短，省下 Agent 的上下文；需要更多时再用 `--fields` 取。
检查：👀 评审 `reference` 里的默认字段。

### DCLI-008 响应大小

用默认参数调用时，成功信封必须不超过 8000 个字符，错误信封必须不超过 2000 个字符，按整个信封计。列表靠分页保持在上限之内（DCLI-006）。结果可能大到放不下的命令，比如返回文件内容或长日志的命令，必须提供 `--output <path>`：完整结果写进这个文件，响应里只给摘要和文件路径。

为什么：工具返回的每个字符都占用 Agent 的上下文，固定上限让每次调用都不贵。
检查：🤖 通用一致性测试 R04 检查大小上限。

## 错误

### DCLI-010 错误对象

`error` 必须恰好有 `code`、`message`、`retryable`、`details` 四个键。

- `message` 是写给模型看的一两句话：出了什么事，改动了什么。
- 只有什么都没改变、稍后可以原样再调用时，`retryable` 才可以为 `true`。写操作要重试时，必须按它的确认级别从头开始（DCLI-052）。

为什么：Agent 根据 `code` 和 `retryable` 决定下一步，`message` 只是补充背景。
检查：🤖 通用一致性测试 R04。

### DCLI-011 派发状态与下一步

`details` 必须始终有以下两项：

- `dispatch_state`：修改请求有没有到达软件或设备。`not_started` 表示没发出，`dispatched` 表示已发出，`unknown` 表示无法确定。读命令必须始终报告 `not_started`。
- `next_action`：一句话告诉 Agent 下一步做什么。有确切命令时，必须放在反引号里。

为什么：出错后 Agent 先要知道有没有发出去，再要知道接下来运行什么。
检查：🤖 通用一致性测试 R03 和 R04。

### DCLI-012 固定的 details 字段

以下错误码和情形必须在 `details` 里带对应的字段：

| 错误码或情形 | 字段 | 内容 |
|---|---|---|
| `E_USAGE` | `problem`、`parameter` | 哪里有误，是哪个参数 |
| `E_AMBIGUOUS` | `candidates` | 匹配到的对象或实例，由 Agent 选一个 |
| `E_CONFLICT` | `conflict` | 哪个前置条件不满足，取值见契约的 `conflict_values`（DCLI-056、DCLI-206、DCLI-211、DCLI-212） |
| `E_FORBIDDEN` | `scope` | 授权范围缺什么（DSEC-015） |
| `E_OUTCOME_UNKNOWN` | `lookup` | 查清结果的确切命令（DCLI-063） |
| `E_BUSY` | `retry_after_ms` | 等多久再试 |
| `E_HUMAN_REQUIRED` | `action`、`resume` | 人要做什么，以及做完后运行的命令（DCLI-066） |
| `E_CONFIRMATION_REQUIRED` | `preview`、`confirm_token`、`expires_at` | 预览和用来确认它的令牌（DCLI-053） |
| 写操作的回执推导出 `ok: false` | `receipt` | 这次写操作的回执（DCLI-062） |
| 批量操作没有全部成功 | `batch` | 这批操作的 `{items, summary}`（DCLI-064） |
| 软件报了错 | `native_message` | 软件自己的报错原文，列入 `meta.untrusted` |
| 有知识条目说明怎么处理 | `knowledge` | 相关知识条目的 ID（DSKL-124） |

为什么：字段固定，Agent 不用解析 `message` 就能处理错误。
检查：🤖 通用一致性测试 R03 检查用法错误带 `problem`；R04 按契约检查每个信封。

### DCLI-013 错误码

工具必须只用本表中的错误码，禁止自创。需要新错误码时，先加进契约，再加进本表。每个错误码的退出码和 `retryable` 都是固定的。

<!-- contract:error_codes -->
| 错误码 | 退出码 | 可重试 | 含义 |
|---|---|---|---|
| `E_USAGE` | 2 | 否 | 命令行有误：未知命令或参数、缺参数、参数值无效 |
| `E_VALIDATION` | 2 | 否 | 格式正确，但内容被软件或工具拒绝，如坐标超出板框 |
| `E_AMBIGUOUS` | 2 | 否 | 一个名字匹配到多个对象或实例；从 `candidates` 中选一个 |
| `E_UNSUPPORTED` | 2 | 否 | 请求有效，但当前软件版本、模式或适配层做不到 |
| `E_NOT_FOUND` | 3 | 否 | 对象、文档、会话、长任务或操作不存在 |
| `E_AUTH` | 4 | 否 | 联网设备或服务要求的凭证缺失、无效或过期 |
| `E_FORBIDDEN` | 4 | 否 | 授权范围没有授予这次操作；`scope` 说明缺什么 |
| `E_CONFIG` | 4 | 否 | 本地配置缺失或无效 |
| `E_BACKEND_UNAVAILABLE` | 4 | 否 | 软件没装、没运行、没有许可或连不上；什么都没派发 |
| `E_CONFIRMATION_REQUIRED` | 5 | 否 | 需要预演和确认，或需要 `--dangerous`；什么都没改 |
| `E_CONFLICT` | 6 | 否 | 前置条件不满足；`conflict` 说明是哪一项（DCLI-056） |
| `E_OUTCOME_UNKNOWN` | 6 | 否 | 修改可能已经生效；先运行 `lookup`，再做别的 |
| `E_NETWORK` | 7 | 是 | 网络不通（自更新、联网设备）；什么都没发出 |
| `E_BUSY` | 7 | 是 | 软件主线程或目标忙；什么都没派发；等 `retry_after_ms` 后再试 |
| `E_TIMEOUT` | 8 | 是 | 读操作超时 |
| `E_HUMAN_REQUIRED` | 9 | 否 | 需要人先处理（`action`），处理完 Agent 运行 `resume`（DCLI-066） |
| `E_PARTIAL` | 1 | 否 | 修改部分生效；看回执或各条目，不要整体重发 |
| `E_VERIFY_FAILED` | 1 | 否 | 修改已生效，但读回与请求不符 |
| `E_VERIFY_INCOMPLETE` | 1 | 否 | 修改已生效，但没能读回核实 |
| `E_NATIVE_FAILURE` | 1 | 否 | 软件拒绝了这次操作，没有留下持久改动 |
| `E_PROTOCOL` | 1 | 否 | CLI 与宿主组件的协议版本不匹配，或回复无法解析 |
| `E_INTEGRITY` | 1 | 否 | 更新包的完整性或来源核对失败；不要重试 |
| `E_IO` | 1 | 否 | 本地文件或状态目录出错；什么都没派发 |
| `E_INTERRUPTED` | 130 | 是 | 在产生任何持久影响之前被中断 |
| `E_UNKNOWN` | 1 | 否 | 内部错误；看 `message` 和 `details` |

为什么：错误码集合固定，一个 Agent 就能用同一套办法处理所有工具的错误。
检查：🤖 通用一致性测试 R03 检查 `E_USAGE`；R04 按契约检查每个错误码。

### DCLI-014 退出码

退出码必须由 DCLI-013 规定的错误码决定。成功时退出码必须为 0。

<!-- contract:exit_codes -->
| 退出码 | 含义 | Agent 的下一步 |
|---|---|---|
| `0` | 成功 | 继续 |
| `1` | 部分生效、核实失败或未完成、软件报错、协议、完整性、本地 IO、内部错误 | 读 `error.details` |
| `2` | 用法、校验、歧义、不支持 | 修正请求，不要原样重试 |
| `3` | 找不到 | 找到正确的目标 |
| `4` | 凭证、授权范围、配置、软件不可用 | 修环境或授权范围，或询问用户 |
| `5` | 需要确认 | 核对预览后用令牌确认，或加 `--dangerous` |
| `6` | 冲突或结果未知 | 重新读取状态，或查询该操作 |
| `7` | 网络不通或软件忙 | 等一会儿再试 |
| `8` | 超时 | 等一会儿再试 |
| `9` | 需要人处理 | 把 `action` 转告用户，人处理后运行 `resume` |
| `130` | 被中断 | 检查状态后再试 |

为什么：只看退出码的脚本或 Agent 也知道该走哪一类下一步。
检查：🤖 通用一致性测试 G01、G06 和 G09 检查退出码 5；R04 按契约检查其他退出码。

## 命令形式

### DCLI-020 先名词后动词

领域命令必须是「名词 动词」的形式，如 `footprint move`。命令树应该扁平：用 `footprint move`，不用 `board footprint move`。

为什么：形式固定，Agent 从对象和动作就能猜出命令。
检查：🤖 通用一致性测试 R02。

### DCLI-021 路径与别名

一个命令路径必须要么是命令组，要么是命令，不能两者都是。别名必须在同级之间唯一；别名不能用哪些名字，见 DCLI-024。

为什么：一个路径如果能有两种意思，同样的话就会执行不同的命令。
检查：🤖 通用一致性测试 R02。

### DCLI-022 动词

领域命令必须从本表中选动词，禁止使用 `show`、`inspect`、`info`、`status` 这类同义词。内置命令和标准命令的名字和效果以 DCLI-030 和 DCLI-200 为准。

<!-- contract:verbs -->
| 动词 | 效果 | 含义 |
|---|---|---|
| `list` | `observe` | 返回一页对象；没有匹配时返回空列表，不报 `E_NOT_FOUND` |
| `get` | `observe` | 返回一个对象；不存在时报 `E_NOT_FOUND`，一个名字匹配到多个时报 `E_AMBIGUOUS` |
| `search` | `observe` | 按 `--query` 查找，返回一页结果 |
| `check` | `observe` | 检查规则或一致性（如设计规则检查），不做修改 |
| `create` | `change` | 新建对象，结果里带新对象的 `ref` |
| `update` | `change` | 只修改给出的属性，没给的不动；一个属性都没给时返回 `E_USAGE` |
| `delete` | `change` | 删除；目标不存在时在预览阶段就报 `E_NOT_FOUND` |
| `move` | `change` | 移动、改变位置 |
| `import` | `change` | 把外部文件导入当前文档 |
| `render` | `artifact` | 生成图片、PDF 或其他预览 |
| `export` | `artifact` | 导出为其他格式的文件 |
| `run` | — | 启动一个长任务，返回 `job`（DCLI-065）；效果由各命令自行声明 |

为什么：动词表短而固定，Agent 不用纠结该调 `show`、`info` 还是 `get`。
检查：🤖 通用一致性测试 R02。

### DCLI-023 名词

名词必须是完整的英文单词。唯一的例外是行业或软件里通用的缩写，如 `pcb`、`bom`，可以使用；禁止使用 `sch`、`fab`、`kb` 这类自造缩写。名词应该用软件自己的叫法，即界面和手册里的词，因为用户和 Agent 说的就是这些词。

为什么：Agent 要把用户的话对应到命令上，自造缩写会让这种对应失效。
检查：👀 评审命令树。

### DCLI-024 保留名

以下名字留给内置命令和标准命令：`reference`、`context`、`doctor`、`changelog`、`update`、`operation`、`help`、`version`、`session`、`doc`、`job`、`device`、`plugin`、`knowledge`。领域命令禁止用它们作名词，别名也禁止与它们相同。

为什么：这样每个工具的内置命令和标准命令都在同样的名字下。
检查：🤖 通用一致性测试 R02。

### DCLI-025 全局参数

全局参数只有本表这些，在每个工具里含义相同。工具禁止新增全局参数；命令参数禁止与全局参数重名。

<!-- contract:global_flags -->
| 参数 | 取值 | 含义 |
|---|---|---|
| `--format` | `json\|text\|raw` | 输出格式（DCLI-002） |
| `--json` | — | 等于 `--format json` |
| `--pretty` | — | 缩进 JSON |
| `--fields` | `<a,b\|all>` | 选择返回的字段（DCLI-007） |
| `--quiet` | — | 关掉 stderr 上的非错误输出 |
| `--dry-run` | — | 只预演，不修改（DCLI-054） |
| `--confirm` | `<token>` | 用预演给出的令牌执行写操作（DCLI-055） |
| `--dangerous` | — | 危险级写操作必须带（DCLI-052） |

为什么：Agent 学一次，就能在所有工具里用。
检查：🤖 运行时单元测试（参数解析）。

### DCLI-026 共享参数

命令提供以下功能时，必须用这里的参数名和含义。

<!-- contract:shared_flags -->
| 参数 | 取值 | 含义 |
|---|---|---|
| `--limit` | `<n>` | 每页条数。帮助里写明默认值和最大值；超过最大值时返回 `E_USAGE`，不悄悄调低 |
| `--offset` | `<n>` | 本页的起始位置 |
| `--query` | `<text>` | `search` 要找的内容 |
| `--sort` | `<field>` | 列表按哪个字段排序 |
| `--order` | `asc\|desc` | 排序方向 |
| `--state` | `<state>` | 按状态过滤；`all` 表示不过滤 |
| `--ids` | `<a,b,c>` | 一次作用于多个对象（DCLI-064） |
| `--continue-on-error` | `true\|false` | 批量操作中某个对象失败后是否继续（DCLI-064） |
| `--wait` | `<duration>` | 等到状态变化或时长用完再返回 |
| `--output` | `<path>` | 把结果写到本地文件，响应里只给摘要（DCLI-008） |
| `--input` | `<path\|->` | 从文件或 stdin 读入全部参数，格式为一个 JSON 对象 |

时长必须写作 `<n>ms`、`<n>s`、`<n>min` 或 `<n>h`。带单位的物理量参数见 DCLI-082。

为什么：同一功能在每个工具里都用同一个参数，Agent 不用再查。
检查：👀 评审 `reference` 里每个命令的参数。

### DCLI-027 目标参数

作用于会话、文档、设备和长任务的命令，必须用以下命令级参数选择对象，所有工具用同样的名字，如 `job get --job 7`。操作记录和知识条目用 `--id` 选择。

<!-- contract:target_flags -->
| 参数 | 对象 | 含义 |
|---|---|---|
| `--session` `<id>` | 会话 | 选择实例。只有一个实例时可以省略；有多个实例时省略返回 `E_AMBIGUOUS`（DCLI-202） |
| `--doc` `<path-or-id>` | 文档 | 选择文档；文件模式下就是文件路径（DCLI-213） |
| `--device` `<id>` | 设备 | 选择设备 |
| `--job` `<id>` | 长任务 | 选择长任务 |

为什么：同一类对象在每个工具里都用同一种方式指定。
检查：👀 评审 `reference`。

### DCLI-028 目标键

目标键是对象身份的唯一写法。授权范围文件、预览、回执和操作记录必须用它。目标键由人能事先写下的东西构成，比如文件路径或设备 ID，因为写授权范围文件时还没有会话 ID。

<!-- contract:target_keys -->
| 类型 | 格式 | 例子 |
|---|---|---|
| `file`：整个文件 | `file:///<absolute-path>` | `file:///D:/proj/board.kicad_pcb` |
| `file_object`：文件里的对象 | `file:///<absolute-path>#<domain-path>` | `file:///D:/proj/board.kicad_pcb#/footprints/R1` |
| `untitled_document`：未保存的新文档 | `session:<session-id>/untitled:<n>` | `session:kicad-1234/untitled:1` |
| `device_part`：设备的部件 | `device:<device-id>/<part>` | `device:cnc-01/axis-x` |

匹配必须按前缀进行：授权范围文件里写 `file:///D:/proj/`，就覆盖这个文件夹下所有文件里的所有对象。比较之前，运行时必须先规范化路径：绝对路径、统一分隔符，Windows 上不区分大小写。前缀必须只在边界上匹配，即满足以下任一条件：目标键与前缀相同；前缀以 `/` 或 `#` 结尾；目标键在前缀之后紧接着 `/` 或 `#`。所以 `file:///D:/proj` 覆盖 `file:///D:/proj/board.kicad_pcb`，不覆盖 `file:///D:/proj2/board.kicad_pcb`。

为什么：工作开始前写好的授权范围，必须能匹配 Agent 之后碰到的对象。
检查：🤖 运行时单元测试（规范化与前缀匹配）。

## 内置命令

### DCLI-030 内置命令

驱动运行时为每个工具实现以下命令，工具作者禁止自己写。它们必须都按 `observe` 效果声明：工具自己的状态（操作记录、令牌密钥、更新缓存）和 `update` 都不算效果。

<!-- contract:builtin_commands -->
| 命令 | 参数 | 返回什么 |
|---|---|---|
| `reference` | `--index`、`--command <path>` | 全部命令的说明（DCLI-031） |
| `context` | — | 本地状态，不联网（DCLI-032） |
| `doctor` | — | 健康检查（DCLI-033） |
| `changelog` | `--since <version>` | 来自内置 CHANGELOG 的发布说明（DCLI-034） |
| `operation get` | `--id` | 一条操作记录（DCLI-035） |
| `operation list` | `--state`、`--limit`、`--offset` | 操作记录，按时间倒序（DCLI-035） |
| `operation resolve` | `--id`、`--outcome`、`--evidence` | 登记结果未知的写操作的实际结果（DCLI-035） |
| `update` | `--check`、`--target-version <v>`、`--allow-downgrade` | 自更新（DCLI-070） |

为什么：每个工具都用同样的命令回答同样的问题，作者也不用重复造这些命令。
检查：🤖 通用一致性测试 R01 和 R05。

### DCLI-031 reference

`reference` 必须说明每条命令：路径、摘要、参数、输出 Schema、示例、效果、确认级别、成熟度和证据、适用模式、所需的适配能力、可能的错误码，以及相关的知识条目（DSKL-124）。它还必须返回 `driver` 块：支持的模式、所驱动的软件及其支持的版本范围。条款允许工具偏离某个默认做法时，`reference` 必须在受影响的命令上写明每一项偏离，并注明允许它的条款编号，放在该命令的 `departures` 列表里。

- `reference --index` 必须只返回索引，不超过 8000 个字符。
- `reference --command <path>` 必须只返回一条命令，不超过 6000 个字符。

为什么：Agent 用一条命令就能了解整个工具，包括每个写命令的确认级别，不用猜。
检查：🤖 通用一致性测试 R01 和 R02；👀 评审每一项偏离都注明了条款。

### DCLI-032 context

`context` 必须不联网，只读本地状态。它返回以下键：

<!-- contract:context_keys -->
| 键 | 内容 |
|---|---|
| `tool` | 工具名 |
| `version` | 工具版本 |
| `spec_version` | 工具遵循的本规范版本 |
| `state` | 状态目录：路径、是否可用、实际的访问保护方式（DSEC-032） |
| `authorization` | 授权范围的状态（DSEC-016）、ID、文件路径、允许的效果、是否允许危险操作、到期时间 |
| `application` | 软件的安装位置、版本和许可状态 |
| `sessions` | 运行中实例的概况 |
| `components` | CLI 版本、磁盘上的宿主组件版本、各实例已加载的宿主组件版本 |
| `knowledge` | 内置知识的条目数，以及团队知识的登记列表：`id`、`title`、`kind`、`url`（DSKL-125） |

为什么：动手之前，Agent 用一次不联网的调用就能看清自己所处的环境。
检查：🤖 通用一致性测试 R05。

### DCLI-033 doctor

`doctor` 必须返回 `checks` 列表，每项为 `{check, status, message, fix}`，`status` 取 `pass`、`warn` 或 `fail`。它必须做以下检查：

<!-- contract:doctor_checks -->
| 检查项 | 检查什么 |
|---|---|
| `state_store` | 状态目录可用且受保护（DSEC-032） |
| `authorization` | 授权范围文件的状态（DSEC-016） |
| `version` | CLI 与已安装的 Skill 版本一致（DSKL-031） |
| `update` | 有没有新版本（DCLI-079） |
| `application` | 软件的安装位置和版本 |
| `license` | 软件的许可状态 |
| `plugin` | 磁盘上的宿主组件版本与各实例已加载的版本一致（DSEC-053） |
| `sessions` | 运行中的实例及其状态 |
| `knowledge` | 知识索引、条目格式和登记文件；登记了团队知识时，PATH 上有没有 lark-cli（DSKL-125） |

为什么：一条命令就能找出常见的环境问题，并说明每个问题怎么修。
检查：🤖 通用一致性测试 R05 检查固定检查项是否齐全。

### DCLI-034 changelog

`changelog` 必须读取工具自带的 CHANGELOG，返回 `current_version` 和 `entries`。每条为 `{version, date, changes}`，`changes` 必须按 `added`、`changed`、`deprecated`、`removed`、`fixed`、`security` 分组。`changelog --since <version>` 必须只返回比该版本新的条目。

为什么：更新之后，Agent 不联网也能看到改了什么。
检查：🤖 运行时单元测试。

### DCLI-035 操作记录命令

- `operation get --id <id>` 必须返回一条操作记录。
- `operation list [--state <state>] [--limit <n>] [--offset <n>]` 必须按时间倒序列出操作记录。
- `operation resolve --id <id> --outcome applied|not_applied|partial --evidence <text>` 登记结果未知的写操作实际发生了什么（DCLI-063）。授权范围没有覆盖该操作的效果时，必须拒绝（DSEC-017）。

为什么：Agent 随时能回看自己做过什么，也能把结果未知的写操作查清结案。
检查：🤖 通用一致性测试 R05 在空状态下运行 `operation list`；驱动一致性测试 D06 登记一次结果未知的写操作。

### DCLI-036 版本与帮助

每个工具必须支持 `--version`（报告工具版本）和 `--help`（显示用法）。两者都由运行时实现。

为什么：`update` 要靠 `<tool> --version` 确认实际装上的版本（DCLI-074）。
检查：🤖 运行时单元测试。

## 写操作

### DCLI-050 写操作流程

每个写操作都必须按以下顺序进行，全程保留操作记录（DCLI-059）：

1. 检查授权范围（DSEC-014、DSEC-015）。
2. 按确认级别返回预演并等待确认，或者直接继续（DCLI-052）。
3. 执行前复查状态（DCLI-056）。
4. 派发修改（DCLI-057）。
5. 读回核实（DCLI-057）。
6. 返回回执（DCLI-061）。

每一级都必须检查授权范围、保留操作记录、读回核实并返回回执。直接执行只省掉确认这一步，安全检查一样不少。

为什么：流程固定，每个工具的每次写操作都同样谨慎，报告也同样清楚。
检查：🤖 通用一致性测试 G07；驱动一致性测试 D16。

### DCLI-051 效果

每个命令都必须声明效果。效果决定默认的确认级别和最低风险等级：

<!-- contract:effects -->
| 效果 | 含义 | 确认级别 | 风险等级 |
|---|---|---|---|
| `observe` | 只读 | 不需要 | `T0` |
| `session` | 改变软件的运行状态，但不改文件，如启动实例、打开文档 | 直接执行 | `T1` |
| `change` | 修改软件里或文件里的对象 | 会话模式直接执行；文件模式和设备模式两步确认 | `T1` |
| `artifact` | 新建本地文件，如导出、另存为 | 直接执行；目标文件已存在时按 `persist` 处理 | `T1` |
| `persist` | 覆盖已有的本地文件，如保存 | 两步确认 | `T1` |
| `configure` | 修改设置、权限或宿主组件 | 两步确认 | `T2` |
| `deliver` | 把内容交给外部的人或系统，如提交到 PLM 系统、发邮件 | 危险 | `T2` |
| `physical` | 物理动作，如移动机床的轴、通电 | 危险 | `T2` |

- 声明了多个效果的命令，必须取其中最严的确认级别。
- 不论效果是什么，以下操作都必须是危险级：不可撤销的删除、放弃未保存的修改、关闭不是本工具启动的实例。
- `job cancel` 声明的效果是 `change`，但在所有模式下都必须直接执行，因为它只是请软件停下本工具启动的长任务（DCLI-221）。

为什么：确认的严格程度跟着风险走：只改内存的直接执行，写盘和影响外部世界的才要确认。
检查：🤖 通用一致性测试 R01 检查每个命令都声明了效果；G01 和 G09 检查由效果得出的确认级别。

### DCLI-052 确认级别

| 级别 | 适用 | 调用方式 |
|---|---|---|
| 直接执行 | 只改软件内存、可以丢弃的操作：会话模式下对文档的修改；打开实例和文档；新建文件且不覆盖已有文件；取消本工具启动的长任务 | 一次调用就执行。Agent 可以加 `--dry-run` 先看预览 |
| 两步确认 | 写到磁盘或改变环境的操作：保存和覆盖文件；文件模式和设备模式下的修改；修改设置；安装宿主组件 | 先带 `--dry-run` 拿到预览和令牌，再带 `--confirm <token>` 执行 |
| 危险 | 物理动作；把内容交给外部；不可撤销的删除；放弃未保存的修改；关闭不是本工具启动的实例 | 按两步确认进行，两步都加 `--dangerous`；授权范围必须允许危险操作 |

- 级别按 DCLI-051 的规则得出，由运行时判定。工具禁止降低级别（DSEC-003）。
- `reference` 必须标出每个写命令的级别，让 Agent 不用猜。
- 授权范围文件设了 `confirm: always` 时，所有写操作都必须两步确认，直接执行级的也一样（DSEC-013）。

举例：移动 20 个器件再保存。用批量命令时，一次直接执行的批量移动，加上保存的预演和确认，共 3 次调用；逐个移动时要 22 次。

为什么：会话模式下修改在保存前只在内存里，每个小改动都确认只会多花调用；真正需要把关的是保存和影响外部世界的操作。
检查：🤖 通用一致性测试 G09；驱动一致性测试 D16 和 D17。

### DCLI-053 需要确认

两步确认级的命令既没带 `--dry-run` 也没带 `--confirm` 时，必须什么都不改，返回 `E_CONFIRMATION_REQUIRED`，并在 `details` 里带预览、确认令牌和 `expires_at`。Agent 核对预览后直接用这个令牌确认，不必另做预演。危险级命令在任何一步没带 `--dangerous` 时，必须什么都不改，返回 `E_CONFIRMATION_REQUIRED`。`--format text` 禁止改变以上任何一点。

为什么：漏带标志不会多花调用，也绝不会导致写入。
检查：🤖 通用一致性测试 G01、G06 和 G09。

### DCLI-054 预演与预览

预演（`--dry-run`）必须什么都不改，返回 `data` = `{preview, confirm_token, expires_at, operation_id}`。写操作属于直接执行级时，预演必须只返回 `{preview}`；授权范围设了 `confirm: always` 时它改为两步确认，预演同样给出令牌（DSEC-013）。预览包括：

<!-- contract:preview_fields -->
| 字段 | 内容 |
|---|---|
| `operation_id` | 计划中的操作的 ID |
| `command` | 命令路径 |
| `action` | 一句话说明要做什么 |
| `target` | `{key, kind, label}`；`key` 是目标键（DCLI-028） |
| `effects` | 命令的效果 |
| `tier` | `direct`、`two_step` 或 `dangerous` |
| `changes` | 每项改动一条：`{field, before, after, origin}`；`origin` 取 `tool` 或 `external`（DCLI-058） |
| `session` | `{id, generation}` |
| `document` | `{id, revision, dirty}` |
| `inputs` | 回显全部输入；机密显示为 `***`，文件显示为 `{sha256, bytes}` |
| `can_apply` | 能不能执行 |
| `blocked_by` | 不能执行时的原因 |

为什么：任何改动发生之前，Agent 和人都能看清要改什么、改在哪个对象上。
检查：🤖 通用一致性测试 G02。

### DCLI-055 确认令牌

确认令牌必须绑定以下各项；任何一项变了，都禁止再接受这个令牌。

<!-- contract:token_binds -->
| 绑定的值 | 含义 |
|---|---|
| `command` | 命令路径 |
| `inputs` | 规范化后的全部输入 |
| `target` | 目标键 |
| `session_id` | 会话 ID |
| `session_generation` | 会话代际（DCLI-203） |
| `document_revision` | 文档版本（DCLI-210） |
| `document_dirty` | 文档有没有未保存的修改 |
| `plugin_version` | 实例已加载的宿主组件版本 |
| `scope_id` | 授权范围文件的 ID |
| `scope_hash` | 授权范围文件内容的哈希 |

令牌必须用状态目录里的本机密钥签发（DSEC-033），必须在 10 分钟后过期，并且必须只能用一次。

为什么：令牌绑定了预览里的一切，就不能被挪用到另一次改动上。
检查：🤖 通用一致性测试 G03、G04 和 G05。

### DCLI-056 确认时的复查

命令带 `--confirm` 执行时，驱动运行时必须按顺序做以下检查，遇到第一项不通过就停。不通过的检查必须阻止写入，返回 `E_CONFLICT`，`details.conflict` 写明是哪一项。第 3 项发现授权范围不再授予这次操作时，必须改为返回 `E_FORBIDDEN`。

<!-- contract:confirm_review -->
| 步骤 | 检查 | 不通过时的 `conflict` |
|---|---|---|
| `1` | 令牌有效、没过期、没用过 | `token_invalid`、`token_expired`、`token_used` |
| `2` | 命令和全部输入与令牌一致；错误里指出不一致的参数 | `token_mismatch` |
| `3` | 授权范围文件没变，且仍然授予这次操作 | `scope_changed` |
| `4` | 目标没有被锁（DCLI-060） | `target_locked` |
| `5` | 会话还在，代际不变 | `session_changed` |
| `6` | 文档版本和未保存状态不变 | `document_changed` |
| `7` | 宿主组件版本不变 | `plugin_changed` |
| `8` | 重新计算预览，仍然可以执行 | `blocked` |

直接执行级的命令没有令牌，派发前必须同样做第 3 至 8 项检查。

为什么：从预览到确认之间情况可能变了，派发前再查一遍，能拦下与批准内容不再相符的写入。
检查：🤖 通用一致性测试 G03、G04 和 G10；驱动一致性测试 D02 和 D03。

### DCLI-057 执行与读回

- 派发前，运行时必须检查会话状态（DCLI-204）、文档状态（DCLI-211）、设备状态（DCLI-230）和已加载的宿主组件版本（DSEC-053）。其中任何一项拦下这次写入时，必须返回这些条款规定的错误。能确定没有发出时，`dispatch_state` 必须为 `not_started`。
- 然后运行时派发修改。
- 派发后，运行时必须从运行中的实例、文件或设备读回这次修改涉及的字段，放进回执的 `observed`。只有读回与请求一致时，验证才可以记为 `passed`；不一致的字段必须列在 `mismatched` 里。

为什么：只有工具亲眼看到修改落实，才算完成。
检查：🤖 驱动一致性测试 D04、D07 和 D08。

### DCLI-058 保存才是提交点

会话模式下，修改不等于保存。会话模式下修改之后，回执的 `persistence` 必须为 `unchanged`，文档的 `dirty` 必须为 `true`。只有 `doc save` 和新建文件的写操作才报告 `saved`。

效果为 `artifact` 的写操作，如 `doc save-as`、`export`、`render`，会新建一个文件。它的回执必须报告 `change: not_applicable` 和 `persistence: saved`，验证必须读回这个新文件：文件存在，大小和 SHA-256 与写入的一致。

`doc save` 的预览必须列出上次保存以来的全部修改：本工具做的修改标为 `origin: tool`；不是本工具做的修改，比如人在软件里手动改的，标为 `origin: external`。每次 CLI 调用都很短，收不到两次调用之间的事件，所以宿主组件（没有宿主组件时由适配层）必须保存上次保存以来的修改清单。软件说不清改了什么时，预览也必须为每个不是本工具造成的版本变化列出一条外来修改，不带字段细节。

为什么：「改了没存」绝不能看起来像「做完了」，保存时也要看清写到磁盘上的到底是什么。
检查：🤖 驱动一致性测试 D09 和 D18。

### DCLI-059 操作记录

- 每个写操作都必须有一个以 `op_` 开头的操作 ID。
- 记录必须保存在状态目录里，内容包括：命令、目标、效果、授权范围 ID、预览、回执、各阶段的时间、状态（`planned`、`dispatched`、`completed`、`failed` 或 `unknown`），以及 `operation resolve` 登记的结果。
- 记录必须保留 30 天。
- 操作记录写不进去，或令牌密钥不可用（DSEC-033）时，所有写操作都必须以 `E_IO` 拒绝，什么都不派发；读操作必须照常工作。

为什么：没有记录，事后谁也说不清 Agent 做过什么，结果未知的写操作也无从结案。
检查：🤖 通用一致性测试 G08。

### DCLI-060 目标锁

- 派发前，运行时必须锁住目标。同一目标同一时间只允许一个写操作；同一目标上的另一个写操作必须得到 `E_CONFLICT`（`target_locked`），可以稍后再试。写操作有了确定的结果，不论成功还是失败，都会解锁。
- 锁必须放在状态目录里，由同一用户的所有进程共用；这样多个 Agent 对同一目标的写操作会一个接一个地进行。
- 工具不检测人是否正在软件里操作。人改过文档，文档版本就会变：确认时得到 `document_changed`（DCLI-056），保存预览里显示为外来的修改（DCLI-058）。
- 写操作结果未知的目标必须保持锁定，直到用 `operation resolve` 登记结果（DCLI-063）。

为什么：两个写入方改同一个对象会互相覆盖，加锁把这种情况变成明确的冲突。
检查：🤖 驱动一致性测试 D06；运行时单元测试（两个进程写同一目标）。

### DCLI-061 回执

写操作成功时必须返回 `data` = `{operation_id, receipt, result}`，其中 `result` 是命令自己的结果。回执推导出 `ok: false` 时，回执改放在 `error.details.receipt` 里（DCLI-062）。回执包括：

- `operation_id`、`command`、`target`、`effects`、`tier`；
- `outcome`，即下表的五个维度；
- `observed` 和 `mismatched`：读回的值，以及不一致的字段；
- `session` `{id, generation}` 和 `document` `{id, revision, dirty}`；
- `failed_stage`：失败或中断时所在的阶段：`apply`、`deliver`、`persist` 或 `verify`；
- `notes`：补充说明。

<!-- contract:receipt_dimensions -->
| 维度 | 取值 |
|---|---|
| `execution` 执行 | `not_started`、`running`、`completed`、`failed`、`interrupted`、`unknown` |
| `change` 变化 | `not_applicable`、`not_applied`、`applied`、`partial`、`rolled_back`、`unknown` |
| `delivery` 送达 | `not_applicable`、`not_attempted`、`delivered`、`partial`、`rejected`、`unknown` |
| `persistence` 保存 | `not_applicable`、`unchanged`、`saved`、`partial`、`unknown` |
| `verification` 验证 | `not_applicable`、`not_run`、`passed`、`failed`、`incomplete` |

五个维度必须分开报告，禁止合并成一个成功标记。

```json
{"ok":true,"schema_version":"1.0","data":{"operation_id":"op_7mq2xk4v","receipt":{"operation_id":"op_7mq2xk4v","command":"footprint move","target":{"key":"file:///D:/proj/board.kicad_pcb#/footprints/R1","kind":"footprint"},"effects":["change"],"tier":"direct","outcome":{"execution":"completed","change":"applied","delivery":"not_applicable","persistence":"unchanged","verification":"passed"},"observed":{"x_mm":12.5,"y_mm":30.0},"mismatched":[],"session":{"id":"kicad-1234","generation":3},"document":{"id":"doc_1","revision":8,"dirty":true}},"result":{"ref":"R1","x_mm":12.5,"y_mm":30.0}},"meta":{"duration_ms":640}}
```

为什么：执行了、改了、送达了、存了、核实了是不同的事实，Agent 必须逐一如实报告。
检查：🤖 通用一致性测试 R04；驱动一致性测试 D09。

### DCLI-062 推导 ok 和错误码

工具禁止自己决定写操作的 `ok` 和错误码。运行时必须按下表从回执推导这两者，取第一条匹配的规则。`ok` 为 `false` 时，回执必须放在 `error.details.receipt` 里。

<!-- contract:derivation -->
| 规则 | 回执中有 | ok | 错误码 |
|---|---|---|---|
| `1` | 执行、变化、送达或保存中有 `unknown`，或执行为 `running` | false | `E_OUTCOME_UNKNOWN` |
| `2` | 变化、送达或保存中有 `partial` | false | `E_PARTIAL` |
| `3` | 执行为 `failed`、`interrupted` 或 `not_started`，但已有持久效果（变化 `applied`、送达 `delivered` 或保存 `saved`） | false | `E_PARTIAL` |
| `4` | 执行为 `failed`、`interrupted` 或 `not_started`，且没有持久效果 | false | 失败原因的错误码，默认 `E_NATIVE_FAILURE` |
| `5` | 变化为 `rolled_back` | false | 回滚原因的错误码，默认 `E_VERIFY_FAILED` |
| `6` | 送达为 `rejected` | false | 拒收原因的错误码，默认 `E_FORBIDDEN` |
| `7` | 验证为 `failed` | false | `E_VERIFY_FAILED` |
| `8` | 验证为 `incomplete`，或变化为 `applied` 而验证为 `not_run` | false | `E_VERIFY_INCOMPLETE` |
| `9` | 其他情况 | true | 无 |

第 8 条保证「改了但没核实」不会被当成成功。

为什么：`ok` 由运行时根据事实推导，任何工具都没法报告它没亲眼看到的成功。
检查：🤖 驱动一致性测试 D07 和 D08；运行时单元测试覆盖每一条规则。

### DCLI-063 结果未知

- 派发之后失去连接、软件崩溃或超过期限，工具无法判断修改是否生效时，命令必须返回 `E_OUTCOME_UNKNOWN`，`dispatch_state` 为 `unknown`。
- `details.lookup` 必须给出查清结果的确切命令：读取目标，或 `operation get --id <id>`。
- Agent 必须先运行这条查询，禁止直接重发写操作。
- 目标一直锁着，直到用 `operation resolve` 登记结果（DCLI-060）；登记后目标解锁。原始回执必须保持不变。

为什么：重发一个已经生效的写操作，可能让它生效两次。
检查：🤖 驱动一致性测试 D06。

### DCLI-064 批量操作

- 作用于多个对象的命令必须用一个 `--ids` 列表接收这些对象。运行时必须去重并保持输入顺序；列表为空时必须返回 `E_USAGE`。
- 一份预览必须列出全部对象，一个令牌必须覆盖整批。预览显示任何一个对象不能执行（`can_apply: false`）时，整批都禁止执行。
- 结果必须逐个对象报告 `{target, operation_id, ok, receipt 或 error}`，被跳过的对象报告为 `{target, ok: false, skipped: true}`，另给 `summary` `{total, succeeded, failed, unknown, skipped}`。批量没有全部成功时，`error.details.batch` 里放同样的 `{items, summary}`。
- 全部对象成功才算成功。否则：有对象结果未知的，错误码必须为 `E_OUTCOME_UNKNOWN`；没有结果未知、但有对象已生效的，为 `E_PARTIAL`；都不是时，取第一个失败对象的错误码。
- `--continue-on-error` 默认必须为 `true`，危险级命令默认必须为 `false`。批量停下后，剩余对象必须报告为已跳过，并计入 `summary.skipped`。
- 工具禁止声称软件没有提供的「要么全成、要么全不成」。
- 同一类操作经常要对多个对象做时（如移动器件、改属性、删除），工具应该提供批量形式。

为什么：一次调用处理多个对象能省调用；逐个对象报告结果，部分失败时报告也是实话。
检查：🤖 运行时单元测试。

### DCLI-065 长任务

单次调用应该在 60 秒内返回。预计更久的工作必须做成长任务。提交长任务是一次普通的写操作（DCLI-050）。提交这次调用的结果里，`data.result.job` 必须为 `{id, status, poll}`，`poll` 是查询这个任务的确切命令，如 `job get --job 7 --wait 60s`（DCLI-220）。

为什么：一次调用挂上几分钟，在 Agent 看来就和工具死掉一样。
检查：👀 评审行为矩阵里的命令耗时（DVER-030）。

### DCLI-066 需要人处理

遇到弹窗、许可、登录、设备上的确认等必须由人处理的情况时，命令禁止等待或猜测，必须立即返回 `E_HUMAN_REQUIRED`，并在 `details` 里带：

- `action`：下表中的一个值；
- `resume`：人处理完后要运行的确切命令；
- `dispatch_state`：有没有派发。

<!-- contract:human_required_actions -->
| `action` 取值 | 人要做的事 |
|---|---|
| `dismiss_dialog` | 处理软件里的弹窗 |
| `activate_license` | 处理许可 |
| `sign_in` | 登录 |
| `install_component` | 安装组件 |
| `confirm_on_device` | 在设备上确认 |
| `restart_application` | 重启或重新加载软件实例，比如为了加载新的宿主组件（DSEC-053） |
| `other` | 其他事项 |

弹窗的标题和文字必须放在 `details` 里，并必须列入 `meta.untrusted`。

为什么：模态弹窗可能让调用永远挂着；立即返回，Agent 才能去问人。
检查：🤖 驱动一致性测试 D05。

### DCLI-067 撤销与保证

工具可以提供 `doc undo`，撤销本工具最近一次修改；软件本身没有撤销功能时，禁止提供。工具禁止声明软件没有提供的事务、撤销、取消或幂等保证。

为什么：软件做不到的承诺，比不承诺更糟。
检查：👀 对照能力调查评审（DREPO-060）。

## 自更新

### DCLI-070 必须提供 update

每个工具都必须提供 `update`，由运行时实现。工具只填写自己的 npm 包名，禁止自己写更新逻辑。

为什么：没有统一实现时，各工具要么不做自更新，要么各写一套。
检查：🤖 `check_project` 按哈希核对运行时副本（DREPO-034）。

### DCLI-071 选择版本

- `update` 必须从 npm 仓库查询版本。
- 使用前必须按 semver 校验每个版本号。
- 必须拒绝降级，除非同时给出 `--target-version` 和 `--allow-downgrade`。
- `update --check` 必须只查询，不安装。

为什么：格式不对的版本号或无意的降级，绝不能交给 npm 执行。
检查：🤖 运行时单元测试。

### DCLI-072 移开正在运行的程序

Windows 上正在运行的程序不能被覆盖，但可以改名移走。所以在 Windows 上，调用 npm 之前，`update` 必须把原生程序从平台包目录移到同一磁盘上的其他位置，默认是状态目录下的 `trash/`。下一次运行 `update` 时，必须删掉移到那里的文件。

为什么：不这样做，npm 就替换不了正在执行更新的那个程序。
检查：🤖 运行时单元测试。

### DCLI-073 安全地运行 npm

`update` 必须只用校验过的包名和版本号拼出 npm 的参数，禁止经过 shell 运行 npm，必须调用在 PATH 上按绝对路径找到的 npm，禁止调用当前目录里的同名文件。

为什么：精心构造的版本号，或放在工作目录里的假 npm，都不能借此执行代码。
检查：🤖 运行时单元测试。

### DCLI-074 核对结果

安装后，`update` 必须运行 `<tool> --version`，以它报告的版本为准；只有它等于目标版本，更新才算成功。接着 `update` 必须核对已安装的包的来源证明。只有核对确实做了并且通过，`provenance_status` 才可以为 `verified`；核对没法做时为 `not_checked`。做了核对但没通过，返回 `E_INTEGRITY`（DCLI-078）。

为什么：npm 可能报告成功，而实际运行的仍是旧程序。
检查：🤖 运行时单元测试。

### DCLI-075 直接运行的命令入口

在 Windows 上，经 npm 启动器启动工具比直接运行原生程序慢得多，每次多一秒以上。因此 `update` 必须把 npm 的命令入口改为直接运行平台包里的原生程序：Windows 上是 cmd、PowerShell 和 Git Bash 各用的三个入口文件，其他系统上是一个符号链接。启动器保留作后备。入口直接运行原生程序时，结果中的 `entry` 必须为 `direct`；仍经启动器时必须为 `launcher`。

为什么：Agent 调用次数多，每次多一秒，一个任务下来就是几分钟。
检查：🤖 运行时单元测试。

### DCLI-076 同步 Skill

安装后，`update` 必须从新包同步已安装的 Skill：把每个已安装的 Skill 目录换成新副本，必须保持符号链接不动，禁止新建原本没装的 Skill。

为什么：CLI 和 Skill 必须保持同一版本（DSKL-030）。
检查：🤖 运行时单元测试。

### DCLI-077 重复运行 update

已经是目标版本时，`update` 必须返回 `status: up_to_date`，并补完上次没做完的命令入口修改和 Skill 同步，所以重复运行总是安全的。装了新版本时，`status` 为 `updated`。`update --check` 什么都不装，有更新的版本时返回 `available`，否则返回 `up_to_date`。结果的 `data` 包括：

| 键 | 内容 |
|---|---|
| `status` | `up_to_date`、`updated` 或 `available` |
| `current_version` | 现在装着的版本 |
| `target_version` | `update` 要装的版本 |
| `previous_version` | 这次更新之前的版本 |
| `update_available` | 有没有比已装版本更新的版本 |
| `provenance_status` | `verified` 或 `not_checked`（DCLI-074） |
| `skill_sync_status` | `synced`、`not_needed`、`failed` 或 `skipped` |
| `entry` | `direct` 或 `launcher`（DCLI-075） |

为什么：更新中途被打断时，再运行一次同样的命令就能做完。
检查：🤖 运行时单元测试。

### DCLI-078 更新失败

`update` 必须按下表报告每种失败的错误码，并让工具处于对应的状态：

<!-- contract:update_failures -->
| 情形 | 说明 | 错误码 | 之后的状态 |
|---|---|---|---|
| `registry_unreachable` | 查版本时网络不通或被限流 | `E_NETWORK`（可重试） | 旧版本，未改变 |
| `invalid_version_or_unflagged_downgrade` | 版本号无效，或没带齐两个标志就降级 | `E_USAGE` | 未改变 |
| `npm_not_found` | PATH 上找不到 npm | `E_CONFIG` | 未改变 |
| `running_program_not_movable` | Windows 上移不走正在运行的程序 | `E_IO` | 未改变 |
| `install_failed_or_wrong_version` | npm 安装失败，或装完后程序报告的版本不对；`details` 给出手动安装命令 | `E_IO` | 旧版本 |
| `provenance_check_failed` | 来源证明核对失败 | `E_INTEGRITY`（不要重试） | 如实报告当前装着的版本 |
| `skill_sync_failed` | 工具已更新，但 Skill 同步失败；`details` 给出补救命令 | `E_PARTIAL` | 新工具、旧 Skill；再运行一次 `update` 完成同步 |

为什么：每次失败后，Agent 都必须知道自己在用哪个版本、下一步做什么。
检查：🤖 运行时单元测试。

### DCLI-079 更新提示

- 只有 `update` 和 `doctor` 访问 npm 仓库，其他命令禁止访问。`doctor` 查询时必须最多等 3 秒，失败就忽略。
- 查到的结果必须缓存在状态目录里。其他命令只读缓存，在 `meta.notices` 里附带 `update_available` 提示，每 24 小时最多一次。
- 新版本含安全修复或主版本变化时，提示的 `severity` 必须为 `warning`，否则为 `info`。
- `update` 只更新 CLI 和 Skill，禁止安装宿主组件。宿主组件需要重装时，`update` 的结果和 `doctor` 的输出都必须给出 `plugin install` 命令。

为什么：Agent 不用任何命令联网就能知道有更新，宿主组件也绝不会在用户不知情时被替换。
检查：🤖 运行时单元测试。

## 单位

### DCLI-080 标准单位

每种物理量必须使用一个标准单位，所有工具相同：

<!-- contract:units -->
| 物理量 | 单位 | 键名后缀 | 参数可接受的单位 |
|---|---|---|---|
| `length` 长度 | mm | `_mm` | nm、um、mm、cm、m、mil、in |
| `angle` 角度 | deg | `_deg` | deg、rad |
| `time` 时间 | s | `_s` | ms、s、min、h |
| `temperature` 温度 | degC | `_c` | degC、K、degF |
| `mass` 质量 | kg | `_kg` | mg、g、kg |
| `force` 力 | N | `_n` | N、kN |
| `pressure` 压强 | Pa | `_pa` | Pa、kPa、MPa、bar |
| `speed` 速度 | mm/s | `_mm_per_s` | mm/s、mm/min、m/s |
| `angular_speed` 角速度 | deg/s | `_deg_per_s` | deg/s、rad/s、rpm |
| `frequency` 频率 | Hz | `_hz` | Hz、kHz、MHz、GHz |
| `voltage` 电压 | V | `_v` | uV、mV、V、kV |
| `current` 电流 | A | `_a` | nA、uA、mA、A |
| `resistance` 电阻 | ohm | `_ohm` | mohm、ohm、kohm、Mohm |
| `capacitance` 电容 | F | `_f` | pF、nF、uF、mF、F |
| `inductance` 电感 | H | `_h` | nH、uH、mH、H |
| `power` 功率 | W | `_w` | mW、W、kW |

为什么：所有工具用同一个单位，Agent 在工具之间传值时不用换算。
检查：🤖 运行时单元测试（单位换算）。

### DCLI-081 输出里的单位后缀

物理量的输出键名必须带 DCLI-080 规定的单位后缀，值必须是标准单位下的数，如 `x_mm: 12.5`。信封和宿主协议里的计时字段（`duration_ms`、`retry_after_ms`、`deadline_ms`）以毫秒为单位，不属于领域里的物理量。

为什么：单位写在键名里，Agent 不会读错数值。
检查：👀 评审 `reference` 里的输出 Schema。

### DCLI-082 参数里的单位

物理量参数必须接受带单位的写法，如 `--x 100mil` 或 `--x 2.54mm`，由运行时换算成标准单位。不带单位的数必须按标准单位处理。只接受 DCLI-080 为该物理量列出的单位，其他单位属于无效的参数值（`E_USAGE`）。

为什么：用户和手册混用各种单位，在一处统一换算，每个工具都不会算错单位。
检查：🤖 运行时单元测试。

### DCLI-083 显示单位

工具禁止依赖软件当前设置的显示单位。适配层与软件交换数据时，必须自己换算。

为什么：用户随时可能把显示单位从 mm 切到 mil，相信显示单位的工具会写入错误的数值。
检查：👀 评审适配层；在真实软件上跑行为矩阵的读回行（DVER-031）。

### DCLI-084 坐标系

凡是表示坐标的参数和输出字段，`reference` 都必须写明所用的坐标系：原点、坐标轴方向，以及坐标相对哪个对象。

为什么：原点或某个轴的方向不同，同样的数字指的就是不同的点。
检查：👀 评审 `reference`。

### DCLI-085 未声明单位

没有声明单位的物理量参数，必须在命令登记时就被拒绝。

为什么：未声明的单位在工具发布前就被发现，而不是等写错了数值才发现。
检查：🤖 驱动一致性测试 D13。

## 模式与会话

### DCLI-200 驱动标准命令

运行时根据适配能力（DCLI-260）实现以下命令。工具禁止用其他名字提供同样的功能，比如 `session inspect`、`model open`、`service install`。

<!-- contract:standard_commands -->
| 命令 | 效果 | 模式 | 确认级别 | 说明 |
|---|---|---|---|---|
| `session list` | `observe` | 会话 | — | 列出运行中的实例：会话 ID、软件版本、状态、是否由本工具启动、打开的文档数 |
| `session get` | `observe` | 会话 | — | 一个实例的完整状态，包括是否忙、是否有弹窗 |
| `session open` | `session` | 会话 | 直接执行 | 启动新实例，返回会话 ID |
| `session close` | `session` | 会话 | 直接执行；关闭不是本工具启动的实例为危险 | 关闭实例；有未保存修改时拒绝 |
| `doc list` | `observe` | 文件、会话 | — | 列出文档：路径、版本、是否有未保存修改、是否只读 |
| `doc get` | `observe` | 文件、会话 | — | 一份文档的状态 |
| `doc open` | `session` | 会话 | 直接执行 | 在实例里打开文件 |
| `doc save` | `persist` | 会话 | 两步确认 | 保存到原路径；预览列出上次保存以来的全部修改 |
| `doc save-as` | `artifact` | 会话 | 直接执行；目标文件已存在时两步确认 | 另存为新文件 |
| `doc close` | `session` | 会话 | 直接执行；加 `--discard` 为危险 | 关闭；有未保存修改时拒绝，除非加 `--discard` 放弃修改 |
| `doc undo` | `change` | 会话 | 直接执行 | 可选，软件支持撤销时才提供：撤销本工具最近一次修改 |
| `job list` | `observe` | 全部 | — | 列出长任务 |
| `job get` | `observe` | 全部 | — | 一个长任务的状态；`--wait <duration>` 等到任务结束或时长用完 |
| `job cancel` | `change` | 全部 | 直接执行 | 请求取消本工具启动的长任务；结果区分「已请求取消」和「确认已停止」 |
| `device list` | `observe` | 设备 | — | 列出设备：型号、固件、状态、是否为模拟设备 |
| `device get` | `observe` | 设备 | — | 一台设备的状态 |
| `knowledge list` | `observe` | 全部 | — | 列出知识条目（DSKL-123） |
| `knowledge get` | `observe` | 全部 | — | 内置条目返回正文；团队条目返回链接和读取工具 |
| `knowledge search` | `observe` | 全部 | — | 按关键词查找知识 |
| `knowledge create` | `configure` | 全部 | 两步确认 | 登记一份团队知识文档的链接 |
| `knowledge delete` | `configure` | 全部 | 两步确认 | 取消登记一条团队知识，不动链接指向的文档 |
| `plugin get` | `observe` | 有宿主组件时 | — | 磁盘上的版本，以及各实例已加载的版本 |
| `plugin install` | `configure` | 有宿主组件时 | 两步确认 | 安装或升级宿主组件（DSEC-050） |
| `plugin remove` | `configure` | 有宿主组件时 | 两步确认 | 卸载宿主组件 |

`knowledge create` 和 `knowledge delete` 只改工具自己的登记。它们仍然两步确认，但不计入工具的风险等级（DSEC-002）。

为什么：同样的功能在每个工具里叫同样的名字，Agent 不用重新学会话、文档和长任务的用法。
检查：👀 对照本表评审命令树。

### DCLI-201 模式

工具按以下一种或几种模式工作。工具必须在 `reference` 里逐条命令声明支持哪些模式，并必须提供所支持的每种模式的必备命令。

<!-- contract:modes -->
| 模式 | 适用情况 | 必备命令 | 读回从哪里读 | 保存 |
|---|---|---|---|---|
| `file` 文件 | 不启动软件，直接读写文件 | `doc list`、`doc get` | 重新读取文件 | 写文件就是保存 |
| `session` 会话 | 驱动一个正在运行的软件实例 | 除可选的 `doc undo` 外，全部 `session` 和 `doc` 命令 | 运行中的实例 | 只有 `doc save` 才保存 |
| `device` 设备 | 驱动硬件或它的控制器 | `device list`、`device get` | 设备或它的传感器 | 不适用 |

为什么：模式决定了以哪里的数据为准、保存意味着什么，每次写入因此知道该从哪里读回。
检查：🤖 通用一致性测试 R01 检查 `reference` 里的模式声明。

### DCLI-202 选定会话

有多个运行中的实例、且命令没有指定 `--session` 时，命令必须返回 `E_AMBIGUOUS` 并列出候选，禁止按窗口焦点或最近使用顺序选择。只有一个实例时可以自动选中，并必须在输出中写明所选的会话。

为什么：同时开着两个工程时，按焦点选择会改错工程。
检查：🤖 驱动一致性测试 D01。

### DCLI-203 会话对象

会话至少必须有以下字段，完整定义见契约里的 `objects.schema.json`：

- `id`：会话 ID；
- `application`：`{name, version}`；
- `pid`：进程号；
- `owned`：实例是否由本工具启动；
- `generation`：连接代际。宿主组件重新加载，或者与实例的连接断开后重新建立（DCLI-278）时，它加一。对同一个运行中的实例，CLI 的每次调用看到的代际相同；
- `state`：见 DCLI-204；
- `documents`：打开的文档的 ID；
- `plugin_loaded`：这个实例已加载的宿主组件版本；没有加载时为 `null`。

为什么：`owned` 决定关闭是否危险，`generation` 让令牌能发现重连。
检查：🤖 驱动一致性测试 D02。

### DCLI-204 会话状态

命令必须按本表对各会话状态作出反应：

<!-- contract:session_states -->
| 状态 | 含义 | 命令的反应 |
|---|---|---|
| `starting` | 正在启动 | `E_BUSY`，可重试 |
| `ready` | 可以操作 | 正常执行 |
| `busy` | 软件主线程忙 | `E_BUSY`，可重试，附建议等待时间；保证没有派发 |
| `blocked` | 有弹窗、许可窗口等需要人处理 | `E_HUMAN_REQUIRED`，附弹窗标题（不可信内容）和恢复命令 |
| `lost` | 进程还在，但连不上 | `E_BACKEND_UNAVAILABLE`；已派发的写操作记为结果未知 |
| `closed` | 进程已结束 | 会话 ID 失效，`E_NOT_FOUND` |

为什么：每种状态的反应都固定，软件忙或被弹窗挡住时，调用不会一直挂着。
检查：🤖 驱动一致性测试 D04、D05 和 D21。

### DCLI-205 会话读取时限

`session list`、`session get`、`doc list` 和 `doc get` 必须在 5 秒内返回。某个实例 2 秒内没有回应时，命令必须不再等它，把它的 `state` 报为 `busy`，其余实例照常返回。

为什么：一个卡住的实例，不能让 Agent 连其他实例也看不到。
检查：🤖 驱动一致性测试 D22。

### DCLI-206 打开和关闭会话

`session open` 必须启动新实例并返回它的会话 ID。`session close` 必须拒绝关闭有未保存修改的实例，返回 `E_CONFLICT`，`conflict` 为 `unsaved_changes`。关闭不是本工具启动的实例（`owned: false`）必须是危险级（DCLI-051）。适配层没有 `open_session` 或 `close_session` 能力时，对应的命令返回 `E_UNSUPPORTED`（DCLI-260）。

为什么：关闭会丢掉未保存的工作，而不是本工具启动的实例里可能有人正在做的工作。
检查：👀 评审行为矩阵（DVER-030）。

## 文档

### DCLI-210 文档对象

文档至少必须有以下字段，完整定义见契约里的 `objects.schema.json`：

- `id`；
- `path`：文件路径；从未保存过的新文档为 `null`；
- `session`：文档所在的会话；文件模式下为 `null`；
- `revision`：每次修改加一；
- `dirty`：有没有未保存的修改；
- `readonly`；
- `state`：见 DCLI-211。

为什么：有了 `revision` 和 `dirty`，令牌和保存预览都能发现任何修改，包括人做的修改。
检查：🤖 驱动一致性测试 D03。

### DCLI-211 文档状态

命令必须按本表对各文档状态作出反应：

<!-- contract:document_states -->
| 状态 | 含义 | 命令的反应 |
|---|---|---|
| `clean` | 与磁盘一致 | 正常执行 |
| `dirty` | 有未保存的修改 | 读写正常；关闭或放弃修改需要额外确认（DCLI-212） |
| `readonly` | 只读 | 写命令被拒绝，返回 `E_VALIDATION` |
| `conflict` | 打开后，磁盘上的文件被别人改过 | 写和保存被拒绝，返回 `E_CONFLICT`，`conflict` 为 `file_changed_on_disk` |
| `missing` | 磁盘上的文件已不存在 | 保存到原路径被拒绝，返回 `E_CONFLICT`，`conflict` 为 `file_missing` |

为什么：保存绝不能悄悄覆盖别人的修改，也不能悄悄重建已被移走或删除的文件。
检查：🤖 运行时单元测试。

### DCLI-212 文档命令

文档命令的效果和确认级别见 DCLI-200。此外：

- `doc close` 必须拒绝关闭有未保存修改的文档，返回 `E_CONFLICT`，`conflict` 为 `unsaved_changes`。`doc close --discard` 放弃这些修改，必须是危险级。
- `doc save` 写回原路径，它的预览列出上次保存以来的全部修改（DCLI-058）。
- `doc undo` 是可选的（DCLI-067）。

为什么：只有明确要求、并按危险级确认之后，未保存的工作才会被丢掉。
检查：🤖 驱动一致性测试 D10。

### DCLI-213 文件模式下的文档

文件模式下，`--doc` 必须是文件路径。写文件就是保存，读回必须重新读取文件。

为什么：中间没有软件，磁盘上的文件就是唯一的依据。
检查：👀 评审适配层。

## 长任务

### DCLI-220 长任务对象与命令

长任务至少必须有以下字段：`id`、`operation_id`、`status`、`cancel_requested` 和 `started_at`。软件报告进度时，还必须有 `progress` `{done, total, unit}`；总量未知时 `total` 为 `null`。`status` 取 `planned`、`running`、`succeeded`、`failed`、`partial`、`unknown`、`cancelled` 之一。

`job list` 列出长任务。`job get --job <id> --wait <duration>` 必须在任务结束或时长用完时返回，以先到者为准。`--wait` 不得超过 60 秒（DCLI-065），超过时返回 `E_USAGE`。Agent 可以反复调用。

为什么：Agent 用一次次有时限的短调用等待长时间的工作，而不是让一次调用一直挂着。
检查：🤖 驱动一致性测试 D11。

### DCLI-221 取消长任务

`job cancel` 只作用于本工具启动的长任务。它必须先报告 `cancel_requested: true`；状态必须等软件确认任务已停止后才变为 `cancelled`。软件不支持取消时，`job cancel` 必须返回 `E_UNSUPPORTED`。

为什么：软件还没停就报告「已取消」，旧任务还在跑，Agent 就可能开始新的工作。
检查：🤖 驱动一致性测试 D11。

## 设备

### DCLI-230 设备对象与状态

设备至少必须有以下字段：`id`、`model`、`firmware`、`state` 和 `simulated`（是否为模拟设备）。动手前，工具先读取设备状态（DSEC-061），命令必须按本表作出反应：

<!-- contract:device_states -->
| 状态 | 含义 | 命令的反应 |
|---|---|---|
| `ready` | 可以动作 | 正常执行 |
| `busy` | 设备忙 | `E_BUSY`，可重试 |
| `fault` | 设备报告故障 | `E_HUMAN_REQUIRED`，`action` 为 `confirm_on_device` |
| `emergency_stop` | 处于急停状态 | `E_HUMAN_REQUIRED`，`action` 为 `confirm_on_device` |
| `offline` | 连不上设备 | `E_BACKEND_UNAVAILABLE` |

模拟设备的结果标明 `simulated`，不会被当作真实结果（DSEC-062）。

为什么：处于故障或急停的机器，在任何部件动起来之前，需要人到现场处理。
检查：🤖 驱动一致性测试 D15 和 D23；运行时单元测试（用模拟宿主的模拟设备逐一模拟各种状态）。

## 宿主组件

### DCLI-240 宿主组件命令

工具有宿主组件时，必须提供 `plugin get`、`plugin install` 和 `plugin remove`（DCLI-200）。`plugin get` 返回宿主组件对象：`name`、`version_on_disk`、`protocol_version`、`install_path` 和 `loaded`（各实例已加载的版本）。安装和升级必须遵守 DSEC-050 至 DSEC-053。

为什么：只有一条带检查的安装途径，在软件里运行的代码才可控。
检查：🤖 驱动一致性测试 D12。

## 适配层与运行时

### DCLI-260 适配能力

除了领域命令，工具作者只写本表中的适配能力，其余全部由运行时处理（DCLI-261）。缺少某项能力时，运行时必须对需要它的命令返回 `E_UNSUPPORTED`，工具不用写任何代码。

<!-- contract:adapter_capabilities -->
| 能力 | 文件 | 会话 | 设备 | 说明 |
|---|---|---|---|---|
| `probe` | 必需 | 必需 | 必需 | 查找软件的安装位置、版本和许可 |
| `sessions` | — | 必需 | — | 列出实例及其状态 |
| `open_session` | — | 可选 | — | 启动实例 |
| `close_session` | — | 可选 | — | 关闭实例 |
| `documents` | 必需 | 必需 | — | 列出文档及其状态 |
| `open_doc` | — | 必需 | — | 打开文档 |
| `save_doc` | — | 必需 | — | 保存文档 |
| `close_doc` | — | 必需 | — | 关闭文档 |
| `undo` | — | 可选 | — | 撤销本工具最近一次修改（软件支持撤销时） |
| `read` | 必需 | 必需 | 必需 | 执行只读命令 |
| `preview` | 有写命令时 | 有写命令时 | 有写命令时 | 生成预览 |
| `apply` | 有写命令时 | 有写命令时 | 有写命令时 | 执行修改 |
| `read_back` | 有写命令时 | 有写命令时 | 有写命令时 | 读回被改的字段 |
| `job_status` | 有长任务时 | 有长任务时 | 有长任务时 | 查询长任务的状态 |
| `cancel` | 有长任务时 | 有长任务时 | 有长任务时 | 取消长任务 |
| `devices` | — | — | 必需 | 列出设备及其状态 |
| `plugin_status` | 有宿主组件时 | 有宿主组件时 | 有宿主组件时 | 报告宿主组件的版本 |
| `plugin_install` | 有宿主组件时 | 有宿主组件时 | 有宿主组件时 | 安装宿主组件 |

标为「必需」的能力，支持该模式的每个工具都必须实现。「有写命令时」表示工具有写命令时必需；「有长任务时」「有宿主组件时」同理。「可选」的能力可以不实现。「—」表示该模式用不到这项能力。

为什么：作者只写这个软件特有的部分，共用的部分全部来自运行时。
检查：🤖 运行时单元测试。

### DCLI-261 运行时负责的事

驱动运行时负责：

- 参数解析、单位换算与校验、目标键规范化；
- 输出信封、错误对象、输出大小控制；
- 全部内置命令和标准命令；
- 授权范围检查、确认分级、预览与令牌、确认时的复查；
- 操作记录与锁、回执推导、状态到错误码的映射；
- 批量操作、长任务查询；
- 自更新与更新提示。

工具禁止重新实现其中任何一项，必须把运行时原样复制到自己的项目里（DREPO-032）。

为什么：共用的规则只实现一次，在每个工具里的表现才完全一样。
检查：🤖 `check_project` 按哈希核对运行时副本（DREPO-034）。

### DCLI-262 适配代码在哪里运行

每项适配能力的代码，必须在能调用到软件接口的地方运行，按下表决定：

| 软件提供的接口 | 代码在哪里运行 | 用什么语言 |
|---|---|---|
| CLI 能直接调用的接口：Python API、COM、软件自带的命令行、文件格式 | 适配层，在 CLI 进程里 | 运行时的语言 |
| 只能在软件进程里调用的接口：插件 SDK（.NET、Java、C++）、软件自带的脚本语言；或者调用必须在软件主线程上执行 | 宿主组件，在软件进程里，经宿主协议与 CLI 通信 | 软件支持的语言 |

- 两种方式可以混用，比如读文件走适配层，改模型走宿主组件。
- 本规范提供 Python 版的驱动运行时。Python 能直接调用 COM、多数软件的 Python 接口和常见文件格式；其他接口都经宿主协议接入，所以一种运行时就能覆盖各种软件。

为什么：软件提供什么接口，决定了代码能在哪里运行；规则定好，每个作者就不用再做一遍选择。
检查：👀 对照能力调查评审（DREPO-015）。

### DCLI-263 黑盒一致性测试

一致性测试必须把 CLI 当作黑盒：从命令行调用，配合模拟宿主检查结果，与实现语言无关。其他语言的运行时必须通过同一套测试。

为什么：测试不依赖语言，才能证明每种运行时的行为都一样。
检查：👀 评审一致性测试套件（DVER-011）。

## 宿主协议

### DCLI-270 本机连接

CLI 与宿主组件之间必须只在本机连接：Windows 用命名管道，macOS 和 Linux 用 Unix 套接字。宿主组件禁止开放网络端口，必须只接受当前用户的连接（DSEC-054）。

为什么：宿主组件能修改用户的设计，网络上和本机上的其他人都不能连到它。
检查：👀 评审宿主组件。

### DCLI-271 发现文件

宿主组件启动后，必须在状态目录的 `hosts/` 下写一个发现文件，内容为 `address`、`pid`、`application`、`protocol_version`、`plugin_version` 和 `started_at`；退出时必须删除这个文件。`session list` 必须读取这些文件，并确认每个进程还在。

为什么：崩溃的宿主会留下文件，确认进程是否还在，列表里才不会出现已经不存在的实例。
检查：🤖 运行时单元测试。

### DCLI-272 分帧

报文必须使用 JSON-RPC 2.0。每条报文必须先是一行 `Content-Length: <bytes>`，再空一行，然后是 UTF-8 编码的 JSON 正文。头部这一行和空行都以 CRLF（`\r\n`）结尾。`<bytes>` 是正文的字节数。

为什么：有了长度头，双方都能从数据流里读出完整的报文，不用猜一条报文在哪里结束。
检查：🤖 运行时单元测试。

### DCLI-273 握手

连上之后，CLI 必须先发 `hello`，带 `protocol_version` 和 `cli_version`。宿主必须回复 `protocol_version`、`plugin_version`、`application`（软件名称和版本）、`session` `{id, generation}` 和 `methods`（它支持的方法）。协议主版本不同时，CLI 必须返回 `E_PROTOCOL`，禁止发出任何修改。

为什么：对协议理解不一致的 CLI 和宿主，必须在误解一次写入之前就停下。
检查：🤖 驱动一致性测试 D20。

### DCLI-274 方法与期限

宿主方法必须是本表所列的方法。除 `hello` 和 `ping` 外，每个方法与 DCLI-260 中同名的适配能力含义相同。适配能力 `plugin_install` 没有对应的宿主方法：`plugin install` 在 CLI 进程里运行，并做 DSEC-051 规定的检查。每个请求都必须带 `deadline_ms`，即 CLI 等待回复的毫秒数（DCLI-275）。

<!-- contract:host_methods -->
| 方法 | 写操作 | 含义 |
|---|---|---|
| `hello` | 否 | 握手（DCLI-273） |
| `ping` | 否 | 心跳（DCLI-278） |
| `probe` | 否 | 报告软件的安装位置、版本和许可 |
| `sessions` | 否 | 列出实例及其状态 |
| `open_session` | 是 | 启动实例 |
| `close_session` | 是 | 关闭实例 |
| `documents` | 否 | 列出文档及其状态 |
| `open_doc` | 是 | 打开文档 |
| `save_doc` | 是 | 保存文档 |
| `close_doc` | 是 | 关闭文档 |
| `undo` | 是 | 撤销本工具最近一次修改 |
| `read` | 否 | 执行读取 |
| `preview` | 否 | 生成预览 |
| `apply` | 是 | 执行修改 |
| `read_back` | 否 | 读回被改的字段 |
| `job_status` | 否 | 报告长任务的状态 |
| `cancel` | 是 | 取消长任务 |
| `devices` | 否 | 列出设备及其状态 |
| `plugin_status` | 否 | 报告宿主组件的版本 |

为什么：所有工具共用一套方法，运行时和模拟宿主就能与任何宿主组件通信。
检查：🤖 运行时单元测试。

### DCLI-275 回复里的派发状态

写方法（DCLI-274 中标为写操作的方法）的回复必须带 `dispatch_state`。宿主在开始修改之前就失败的，必须回复 `not_started`。CLI 在期限内收不到回复时，必须把这个写操作记为结果未知（DCLI-063）。

为什么：只有宿主知道修改有没有开始，CLI 不能替它猜。
检查：🤖 驱动一致性测试 D06。

### DCLI-276 主线程

宿主组件必须在软件主线程上调用软件接口。主线程忙时，必须立即回复 `E_BUSY`，禁止把请求放在连接上排队等待。

为什么：排队的请求可能很久以后才执行，那时 Agent 早已做了别的事。
检查：🤖 驱动一致性测试 D04。

### DCLI-277 事件

宿主可以主动推送以下通知：

<!-- contract:host_events -->
| 事件 | 含义 |
|---|---|
| `dialog_opened` | 软件里弹出了弹窗 |
| `busy` | 主线程变忙 |
| `document_changed` | 文档被本工具以外的一方修改了，比如人手动修改 |
| `session_closing` | 实例正在关闭 |

宿主组件必须把每个 `document_changed` 加进上次保存以来的外来修改清单，供保存预览读取（DCLI-058）。

为什么：CLI 得知人的修改，保存预览才能把它们列出来。
检查：🤖 驱动一致性测试 D18。

### DCLI-278 心跳

连接期间，CLI 必须每 5 秒发一次 `ping`。连续 3 次没有回复时，会话状态必须变为 `lost`，正在进行的写操作必须记为结果未知。

为什么：不再回应的宿主不能看起来还活着，它没做完的写操作也不能看起来已经完成。
检查：🤖 驱动一致性测试 D21。

### DCLI-279 宿主错误

宿主必须只返回以下错误码：

<!-- contract:host_error_codes -->
| 错误码 | 什么时候 |
|---|---|
| `E_BUSY` | 主线程忙（DCLI-276） |
| `E_NATIVE_FAILURE` | 软件拒绝了这次操作，没有留下持久改动 |
| `E_HUMAN_REQUIRED` | 有弹窗等需要人处理 |
| `E_NOT_FOUND` | 对象或文档不存在 |
| `E_VALIDATION` | 软件拒绝了内容 |
| `E_UNSUPPORTED` | 软件做不到 |

错误必须以 JSON-RPC 错误发送，错误码为 `-32000`。`data` 里必须有 `code` 和 `dispatch_state`，软件给出了报错原文时还必须有 `native_message`。`E_BUSY` 应该另带 `retry_after_ms`，`E_HUMAN_REQUIRED` 应该另带 `action`。DCLI-012 要求的其他 `details` 字段，如 `next_action` 和 `resume`，由 CLI 补上。`native_message` 是软件自己的报错原文，必须当作不可信内容处理（DSEC-020）。

为什么：宿主错误少而固定，就能直接对应到 Agent 已经熟悉的错误码。
检查：🤖 运行时单元测试。

### DCLI-280 协议版本

协议版本必须遵循 SemVer，并必须同时写在契约和宿主组件的清单里。本规范定义的协议版本是 1.0.0。

为什么：双方在交换任何写入之前就能比较版本。
检查：🤖 驱动一致性测试 D20。

### DCLI-281 宿主端库

本规范提供协议的 Schema（在契约里）、模拟宿主里的参考实现，以及部分宿主语言的宿主端小库。宿主组件所用的语言有对应的库时，应该使用它，不应该自己实现连接、分帧、握手和心跳。

为什么：连接、分帧、握手和心跳容易出细微的错，而且每个宿主都一样。
检查：👀 评审宿主组件。

## 检查清单

- [ ] DCLI-001 stdout 上只有一个信封
- [ ] DCLI-002 输出格式
- [ ] DCLI-003 信封的键
- [ ] DCLI-004 meta
- [ ] DCLI-005 命名与取值
- [ ] DCLI-006 列表
- [ ] DCLI-007 默认字段
- [ ] DCLI-008 响应大小
- [ ] DCLI-010 错误对象
- [ ] DCLI-011 派发状态与下一步
- [ ] DCLI-012 固定的 details 字段
- [ ] DCLI-013 错误码
- [ ] DCLI-014 退出码
- [ ] DCLI-020 先名词后动词
- [ ] DCLI-021 路径与别名
- [ ] DCLI-022 动词
- [ ] DCLI-023 名词
- [ ] DCLI-024 保留名
- [ ] DCLI-025 全局参数
- [ ] DCLI-026 共享参数
- [ ] DCLI-027 目标参数
- [ ] DCLI-028 目标键
- [ ] DCLI-030 内置命令
- [ ] DCLI-031 reference
- [ ] DCLI-032 context
- [ ] DCLI-033 doctor
- [ ] DCLI-034 changelog
- [ ] DCLI-035 操作记录命令
- [ ] DCLI-036 版本与帮助
- [ ] DCLI-050 写操作流程
- [ ] DCLI-051 效果
- [ ] DCLI-052 确认级别
- [ ] DCLI-053 需要确认
- [ ] DCLI-054 预演与预览
- [ ] DCLI-055 确认令牌
- [ ] DCLI-056 确认时的复查
- [ ] DCLI-057 执行与读回
- [ ] DCLI-058 保存才是提交点
- [ ] DCLI-059 操作记录
- [ ] DCLI-060 目标锁
- [ ] DCLI-061 回执
- [ ] DCLI-062 推导 ok 和错误码
- [ ] DCLI-063 结果未知
- [ ] DCLI-064 批量操作
- [ ] DCLI-065 长任务
- [ ] DCLI-066 需要人处理
- [ ] DCLI-067 撤销与保证
- [ ] DCLI-070 必须提供 update
- [ ] DCLI-071 选择版本
- [ ] DCLI-072 移开正在运行的程序
- [ ] DCLI-073 安全地运行 npm
- [ ] DCLI-074 核对结果
- [ ] DCLI-075 直接运行的命令入口
- [ ] DCLI-076 同步 Skill
- [ ] DCLI-077 重复运行 update
- [ ] DCLI-078 更新失败
- [ ] DCLI-079 更新提示
- [ ] DCLI-080 标准单位
- [ ] DCLI-081 输出里的单位后缀
- [ ] DCLI-082 参数里的单位
- [ ] DCLI-083 显示单位
- [ ] DCLI-084 坐标系
- [ ] DCLI-085 未声明单位
- [ ] DCLI-200 驱动标准命令
- [ ] DCLI-201 模式
- [ ] DCLI-202 选定会话
- [ ] DCLI-203 会话对象
- [ ] DCLI-204 会话状态
- [ ] DCLI-205 会话读取时限
- [ ] DCLI-206 打开和关闭会话
- [ ] DCLI-210 文档对象
- [ ] DCLI-211 文档状态
- [ ] DCLI-212 文档命令
- [ ] DCLI-213 文件模式下的文档
- [ ] DCLI-220 长任务对象与命令
- [ ] DCLI-221 取消长任务
- [ ] DCLI-230 设备对象与状态
- [ ] DCLI-240 宿主组件命令
- [ ] DCLI-260 适配能力
- [ ] DCLI-261 运行时负责的事
- [ ] DCLI-262 适配代码在哪里运行
- [ ] DCLI-263 黑盒一致性测试
- [ ] DCLI-270 本机连接
- [ ] DCLI-271 发现文件
- [ ] DCLI-272 分帧
- [ ] DCLI-273 握手
- [ ] DCLI-274 方法与期限
- [ ] DCLI-275 回复里的派发状态
- [ ] DCLI-276 主线程
- [ ] DCLI-277 事件
- [ ] DCLI-278 心跳
- [ ] DCLI-279 宿主错误
- [ ] DCLI-280 协议版本
- [ ] DCLI-281 宿主端库
