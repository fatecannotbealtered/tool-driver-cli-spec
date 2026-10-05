# 核心机器协议

规范版本：`1.0.0`；状态：`stable`；驱动结构版本：`2.0`；基线：ai-native-cli-spec `v1.6.3`。

本文面向驱动 CLI、适配器和消费方的实现者，假设读者已读过基线 [CLI-SPEC](../base/ai-native-cli-spec/CLI-SPEC_zh.md)。
本文只写驱动层在基线之上增加或收紧的要求；基线已规定的内容不重复，除非驱动场景需要额外约束。与基线的关系见[基线与驱动层](LAYERING.md)。
「必须」「不得」是可验收要求；「建议」允许说明理由后采用其他方案。

## 目标与范围

定义 Agent 如何发现驱动能力、识别目标、取得计划、提交修改并读取实际结果。
本协议覆盖阶段成功、实际变化和验证证据，不替代工具自己的领域判定。操作语义见[应用与设备操作规范](DRIVER-SPEC.md)，证据见[验证规范](VERIFICATION-SPEC.md)。
公共字段描述目标和执行语义，不预设 CAD、PCB、GUI 或某种文件格式。`driver.modes` 和 `effects` 决定附加要求的适用范围；领域对象、规则与诊断放在产品 Schema 或允许的 `extensions` 中，不重定义公共状态。协议示例中的对象与格式是说明材料，不是支持清单。

## 输出与错误

### COR-001：单一结构化结果

输出格式、编码、stdout/stderr 分工和非交互要求沿用基线 §1、§4、§5。
驱动补充：强制终止、进程崩溃或输出通道中断可能没有完整信封；消费方不得把缺失的信封解释为成功或未执行，可能已执行的修改按 COR-013 查询。

验收：默认结果可按 UTF-8 解析；无终端、无交互 stdin 时不等待提示；缺失信封不触发盲目重试。

### COR-002：基线信封与驱动对象的位置

信封必须是基线信封，键集合精确：成功为 `ok`、`schema_version`、`data`、`meta`，失败为 `ok`、`schema_version`、`error`、`meta`；meta 只有 `duration_ms` 和可选 `notices`。
驱动对象只出现在下表位置，失败信封不得携带 data：

| 对象 | 成功时 | 失败时 |
|---|---|---|
| 计划（dry-run） | `data.preview`、`data.confirm_token`、`data.expires_at` | — |
| 回执 | `data.receipt` | `error.details.receipt` |
| 依赖工作流 | `data.workflow` | `error.details.workflow` |
| 操作状态 | `data.operation_status` | `error.details.operation_status` |
| 检查结论 | `data.verification` | — |
| 独立批量 | `data.items`、`data.summary`（基线） | — |
| 列表 | data 本身符合 query-page | — |

`schema_version` 保持基线值；驱动结构版本见 `reference.driver_profile`。信封符合 [response Schema](../schemas/response.schema.json)。

验收：response Schema 拒绝顶层或 meta 的额外键、带 error 的成功和带 data 的失败；驱动对象只出现在上表位置。

### COR-003：由回执决定 ok 和错误码

`ok: true` 表示本次调用完成了它声明的职责。读取、计划、提交受理和状态查询按基线判断。
修改调用返回回执时，`ok` 和错误码必须按下表从回执推导，按顺序取第一条匹配的规则：

| 回执状态 | ok | 错误码 |
|---|---|---|
| 执行、变化、保存或交付任一为 unknown | false | `E_OUTCOME_UNKNOWN` |
| 执行为 running | false | `E_OUTCOME_UNKNOWN` |
| 变化、保存或交付任一为 partial | false | `E_PARTIAL` |
| 执行为 failed、interrupted 或 not_started，且留下了效果（变化 applied、已保存、已交付，或本次调用生成了产物：回执声明 `artifact` 效果且 `artifacts` 非空） | false | `E_PARTIAL` |
| 执行为 failed、interrupted 或 not_started，没有留下效果 | false | `E_NATIVE_FAILURE`，或说明停止原因的 `E_CONFLICT`、`E_BUSY`、`E_BACKEND_UNAVAILABLE`、`E_HUMAN_REQUIRED`、`E_FORBIDDEN`、`E_UNSUPPORTED`、`E_PROTOCOL`、`E_INTERRUPTED`、`E_TIMEOUT`、`E_NOT_FOUND`、`E_IO`、`E_CONFIG`、`E_VALIDATION` |
| 验证 failed | false | `E_VERIFY_FAILED` |
| 验证 incomplete，或变化 applied 而验证 not_run | false | `E_VERIFY_INCOMPLETE` |
| 其余 | true | — |

这张表的机器形式是 [driver-contract.json](../contract/driver-contract.json) 的 `receipt_codes`。
检查类命令（只有 observe 效果）发现违规时仍返回 `ok: true`，结论放在 `data.verification`；面向 CI 的模式可以把未通过作为失败，但必须在 reference 中声明。
独立批量按基线：批量执行并产出结果即 `ok: true`，逐项状态在 `items[]`。依赖工作流只有全部请求步骤完成才 `ok: true`。

验收：只看 ok 不会把部分应用、未知结果或未读回的修改当作成功；同一份回执在所有驱动 CLI 中得到同一个错误码。

### COR-004：失败仍保留状态

每个错误的 `error.details.dispatch_state` 都必须说明修改是否已派发：`not_started`（未派发，目标未改动）、`dispatched`（已派发）、`unknown`（无法确定是否派发）。
`dispatched` 或 `unknown` 时必须给出 `operation_id`；有回执的放入 `details.receipt`，没有回执的只能报 `E_OUTCOME_UNKNOWN` 或 `E_HUMAN_REQUIRED`。
只读命令的错误、参数错误等执行前拒绝报 `not_started`；已写入的错误不得当作未开始。

验收：回复丢失、写后验证失败和部分工作流的状态不会被错误信封丢弃。

### COR-005：错误与恢复方向

错误码、退出码和 retryable 遵循基线核心表与 [LAY-004](LAYERING.md#lay-004驱动扩展错误码) 的驱动扩展表。
每个错误的 details 都必须有 `dispatch_state`（COR-004）和 `next_action`（下一步做什么），并按错误码再提供：

| 错误码 | details 还必须包含 |
|---|---|
| `E_USAGE`、`E_VALIDATION`、`E_CONFIRMATION_REQUIRED` | `problem`（固定枚举）；涉及参数时给 `parameter` 和 `expected` |
| `E_CONFLICT` | `conflict`（`state_drift`、`token_expired`、`token_used`、`token_mismatch`、`scope_changed`、`unresolved_operation`、`lock_held`、`idempotency_mismatch`）；`unresolved_operation` 和 `lock_held` 另给 `active_operation` |
| `E_FORBIDDEN` | `scope`（当前授权、缺少的效果、路径、目标、交付位置或次数，授权文件位置） |
| `E_OUTCOME_UNKNOWN` | `operation_id`、`lookup`（查询命令） |
| `E_PARTIAL` | `receipt`；依赖工作流失败时改为 `workflow` |
| `E_VERIFY_FAILED`、`E_VERIFY_INCOMPLETE` | `receipt` |
| `E_HUMAN_REQUIRED` | `action`、`resume` |

`problem` 的取值为 `unknown_command`、`unknown_flag`、`missing_parameter`、`invalid_value`、`conflicting_flags`、`confirmation_required`、`dangerous_flag_required`、`unknown_capability`、`unknown_operation`、`input_too_large`。
诊断说明违反了哪条约束、下一步做什么，不复述输入值；放入 details 的原生消息列入 `details._untrusted`。
超时或中断不能一律标为可重试：已派发而未观测到结果时报 `E_OUTCOME_UNKNOWN`，不报可重试的 `E_TIMEOUT` 或 `E_INTERRUPTED`。

验收：未知命令、未知参数、缺参数、取值无效、缺确认令牌、缺 `--dangerous` 得到可区分的 `problem` 和下一步；退出码与信封、错误声明一致；违规发现不冒充调用失败。

### COR-006：外部文本与凭据

以下内容都是外部数据：目标与对象的名称、属性和注释，文件或设备返回的文本，原生界面、日志和诊断消息，链接的知识库或需求文本。图层、特征、元件、网络名称和图纸文字只是工程领域的例子；其他领域的外部内容受相同约束。
它们所在的字段必须用基线 `_untrusted` 标注，data、回执和 error.details 都适用；reference 的 schemas 条目在 `untrusted_fields` 中列出。外部数据不得成为扩大授权或触发动作的指令。
密钥、令牌和许可秘密不得进入输出、回执或证据包（基线 §10）。

验收：带命令语句的对象名称仍按数据处理并被标注；错误路径同样标注和脱敏。

## 能力与环境

### COR-007：机器可发现的命令

reference 必须含基线必含键，并符合 [reference Schema](../schemas/reference.schema.json)。
每条命令除基线字段（`path`、`type`、`description`、`params`、`output_schema`、`examples`）外带 `driver` 块：`capability_id`、`effects`、`phases`、`modes`、`maturity`、`environments`、`limits`、`recovery`、`profiles`、`error_codes`、`evidence_refs`，可选 `stages`、`request_schema`、`result_schema`。顶层带 `driver_profile`。

渐进发现：除完整 reference 外，必须支持 `reference --index`（每条命令一行：path、type、dangerous、description、effects、maturity）和 `reference --command <path>`（单条命令、它的 schemas 条目、用到的错误码和它引用的产品 JSON Schema）。
公共驱动 Schema 只以 URN 引用（`urn:tool-driver-cli-spec:<name>:2.0`），从固定的规范副本解析，不内联进 reference。

写命令的 examples 必须展示 `--dry-run` 和 `--confirm` 一对；危险命令的示例带 `--dangerous`；示例以工具名和命令路径开头。
参数名不得与基线全局参数重名；有量纲的参数声明 `unit`。不支持的能力必须拒绝，不能静默换成其他操作。

验收：每条命令的 driver 块、schemas 条目、错误引用和示例可离线核对；`--command` 的输出不包含公共驱动 Schema 正文。

### COR-008：按效果分类

命令声明可能产生的效果：`observe`、`session`、`artifact`、`change`、`persist`、`deliver`、`configure`、`physical`。效果决定三件事：

- 类型：除 `observe` 外有任一效果的命令都是 write，走基线 `--dry-run` → `--confirm`；
- 授权：除 `observe` 外的效果都必须在授权范围内（DRV-009）；
- 风险：含 `deliver`、`configure`、`physical` 的命令必须标 `dangerous: true`；工具的 `risk_tier` 不得低于效果要求的最低档：`physical` 为 T2，其余非 `observe` 效果为 T1（基线 SEC-SPEC 的 T0 只读）。

`session` 指打开、关闭、切换文档、视图或其他执行上下文等改变会话、不改变目标内容的动作，不要求存在 GUI；`artifact` 指在授权的输出目录新建文件，覆盖已有文件属于 `persist`。只连接或附着已有实例、不改变会话，属于 `observe` 的已披露附带效果。

工具自己的记录（操作记录、令牌密钥、更新缓存）不是目标，读写它们不算效果；内置命令（reference、context、doctor、changelog 和三个 operation 命令）都是只有 `observe` 的 read 命令。
唯一的例外是基线 §14 的 `update` 自更新：它改变的是工具本身而不是目标，一次调用完成，不接受 `--confirm`，声明为 type write、效果 `[observe]`。

验收：查询不能隐藏打开、导出、保存、配置或设备动作；产物位置在执行前可确定；reference 中 type 与效果一致。

### COR-009：实际环境身份

context 和 doctor 遵循基线必含键，并符合 [context Schema](../schemas/context.schema.json) 和 [doctor Schema](../schemas/doctor.schema.json)。context 增加：

- `driver_profile`；
- `authorization`：当前授权范围的摘要（状态、范围 ID、来源、允许的效果、根目录、输出目录、交付位置、是否允许危险命令、到期时间）；
- `environment`：CLI、适配器、运行中的服务和磁盘上的服务、原应用及必需组件，每项给出版本、构建身份、位置（disk、running、remote）和身份是否观测到；连接状态、实例和连接代际；
- `state`：操作记录目录、是否可用、保护方式和保留期限。

doctor 必须包含 `release_readiness`（基线）、`authorization`、`native_backend`、`state_store` 四项检查。
配置存在、文件安装和握手成功是不同观察；无法核实的许可或能力不得报告通过。诊断失败不得擅自重启、注册或改变应用配置。

验收：旧服务仍在运行时，context 同时显示磁盘上的新版本和运行中的旧版本，doctor 的 native_backend 报 fail 并给出修复方法。

### COR-010：单位、身份与重连

对象 ID 是字符串；时间是 UTC 的 ISO 8601，带 `Z` 后缀（基线 §8），公共 Schema 拒绝其他时区写法。
有物理或空间意义的数值必须附单位和必要的坐标语义；计数、ID 和索引不虚构单位。临时面、边或连接身份必须声明稳定性和重连后的解析方式。

验收：输入中的数字不会因默认单位或失效身份指向另一个目标。

## 计划、授权与回执

### COR-011：dry-run 返回可核对的计划

写命令的 `--dry-run` 必须返回 `data.preview`（符合 [plan Schema](../schemas/plan.schema.json)）、`data.confirm_token` 和 `data.expires_at`，两处过期时间一致。
计划记录 `plan_id`、预先分配的 `operation_id`、`capability_id`、目标、基线快照、授权范围、效果、预览等级、结构化的 `changes`、将写入的 `outputs`、未知项、约束、`can_apply` 和过期时间。
预览等级固定为 `plan`、`estimate`、`trial_observed`，定义见 DRIVER-SPEC 的 DRV-019。`can_apply` 为 false 时必须说明阻止执行的约束或未知项。
批量的计划不带单个 `target` 和 `base_snapshot`，改为 `total`、`targets`（基线 §15.2）和逐项的 `items`：每项有自己的目标、基线快照、变化、输出、`can_apply` 和将使用的 `operation_id`；任一项不能执行时整批 `can_apply` 为 false。

dry-run 不得改变目标；需要试执行时只能写入隔离的试执行区（DRV-016）。计划记录在操作记录中，`operation show` 能取回；回执通过 `plan_id` 关联它。

验收：没有每步人工确认时，消费方仍能取回执行前的计划，与回执逐项对照。

### COR-012：令牌绑定计划，授权单独核实

确认令牌遵循基线 §7、§9：用机器本地密钥做 HMAC，绑定命令、参数、目标、基线修订、授权范围和过期时间，单次消费，在派发前标记为已消费。
令牌只证明「这份计划曾在本机校验过」，不是人工批准证明；授权范围另行核实（DRV-009）。

`--confirm` 时必须重新核实授权和目标基线：参数或目标变化报 `E_CONFLICT`（`token_mismatch`），基线变化报 `E_CONFLICT`（`state_drift`），令牌过期或已用过报 `E_CONFLICT`（`token_expired`、`token_used`），授权范围变化报 `E_CONFLICT`（`scope_changed`），授权不再覆盖报 `E_FORBIDDEN`。

验收：GUI 改动或依赖替换使旧计划失效；同一令牌第二次使用被拒绝且不派发；范围内的迭代不重复索取相同授权。

### COR-013：预先知道的操作身份

`operation_id` 在 dry-run 时分配并返回，`--confirm` 之前调用方已经知道它。
操作记录必须在派发前写入；写不进记录时不得派发。回复丢失后，调用方用 `operation show --id <operation_id>` 查询；记录过期或不可用时报告 unknown，不得虚构回执，也不得把查无记录当作未执行。

`--request-id` / `--idempotency-key` 是可选幂等键（基线 §9）：同键同内容不再派发，返回原回执并标 `replayed: true`；同键不同内容报 `E_CONFLICT`（`idempotency_mismatch`）。

验收：丢失首次执行回复后，消费方仍能用预知标识查询；不必为确认结果再次提交修改；重放的回执与新执行可以区分。

### COR-014：五个维度分别报告

回执符合 [receipt Schema](../schemas/receipt.schema.json)，outcome 分五个维度：

| 字段 | 枚举 |
|---|---|
| `outcome.execution` | `not_started` / `running` / `completed` / `failed` / `interrupted` / `unknown` |
| `outcome.change` | `not_applied` / `applied` / `partial` / `rolled_back` / `unknown` |
| `outcome.persistence` | `not_applicable` / `unchanged` / `unsaved` / `saved` / `partial` / `unknown` |
| `outcome.delivery` | `not_applicable` / `not_attempted` / `delivered` / `partial` / `rejected` / `unknown` |
| `outcome.verification.status` | `not_run` / `passed` / `failed` / `incomplete` / `not_applicable` |

这些维度分开表示：执行结束但修改只应用了一部分；内存修改已验证但未保存；本地产物已生成但交付被拒。
执行失败或中断时，`failed_stage` 指明失败的阶段（`apply`、`persist`、`deliver`、`verify`）。`saved` 要求声明了 `persist` 效果；`delivery` 与 `deliveries[]` 的逐项结果一致；交付被拒时执行不能是 completed。
`rolled_back` 必须有恢复后的读回，不得由错误返回或关闭窗口推定；它表示原操作的修改已恢复到基线，不表示原操作成功。独立的恢复请求使用自己的操作 ID、当前基线与授权。

验收：正反例能区分上述状态，字段组合不允许自相矛盾。

### COR-015：快照与验证范围

快照必须记录来源、版本及必要依赖；`mixed` 必须解释哪些内容来自内存、磁盘或其他来源。
验证必须绑定 `scope`、目标快照、检查项、未检查项和证据引用。`passed` 要求声明范围内的必需检查全部通过；范围外尚未检查的领域事项仍需披露。
整体 `not_applicable` 必须说明原因，且不能包含适用的必需检查或未检查项，不能借此绕过失败。

验收：对磁盘版本做的检查不会被表述为对未保存内存版本的验证。

### COR-016：组合、长任务与取消

独立批量用基线批量结构，每个已派发的项带 `operation_id` 或回执，符合 [batch Schema](../schemas/batch.schema.json)；批量的 dry-run 计划列出全部目标和每项将使用的 `operation_id`（DRV-022）。依赖工作流用 [workflow Schema](../schemas/workflow.schema.json)。
长任务的提交同样走 `--dry-run` → `--confirm`，confirm 返回 `data.operation_status`（pending 或 running），之后用 `operation show` 查询。状态沿用基线 §16.2 的 `pending`、`running`、`succeeded`、`failed`、`cancelled`，驱动层增加 `planned`（已计划未确认）、`cancel_requested`、`partial`、`unknown`。
查询不会把已失败的任务重新提交；取消请求被接受不证明已停止或已恢复，只有观测到停止才报 `cancelled`。

验收：依赖步骤失败会停止下游；回复丢失后的状态和设备动作不会被普通重试掩盖。

### COR-017：产物与保存

保存或导出必须记录来源快照、输出位置及可取得的校验值。
文件存在、原生返回成功、文件可重新打开和产物符合预期是不同的验证层次。只有实际保存结果经过核实才能报告 `saved`；部分文件已生成时用 `partial`，不丢弃成功项的信息。交付到他处按 `delivery` 维度单独报告。

验收：图像、文档和导出包能追溯到明确的对象与版本。

## 演进与验收

### COR-018：扩展与兼容

厂商或领域专有字段放在 `extensions` 中，不能重新解释核心字段和枚举。
四个版本分别记录：基线版本（`driver_profile.base.version`）、驱动规范版本（`driver_profile.spec_version`）、驱动结构版本（`driver_profile.schema_version`）、CLI 版本（`reference.version`），任何一个变化都不自动改写其他版本。驱动结构的破坏性变化必须同时升级驱动结构主版本和规范主版本。

验收：消费方能拒绝不理解的驱动主版本；核心字段在不同产品中保持同义。

### COR-019：结构验证的限度

JSON Schema 检查形状；示例校验器补充可以静态判断的状态关系。二者都不能证明状态来自真实工具，真实操作和产物仍按 VERIFICATION-SPEC 取证。
发布包的来源、组件与安装规则按[交付规范](DELIVERY-SPEC.md)验收。

验收：本仓库示例通过不会成为某个应用或设备的真实操作证据。

### COR-020：查询完整性与有界负载

列表沿用基线分页（`items`、`count`、`next_cursor` 或 `offset`/`next_offset`、`has_more`、`truncated`）和 `--fields`、`--compact`，并符合 [query-page Schema](../schemas/query-page.schema.json)：声明 `scope`、来源快照（没有时给出原因）和排序，可选 `consistency`、`limits`、`unread_scopes`。
`has_more` 时给出续取位置或无法续取的原因；`truncated` 时说明原因或未读范围；跨页来源变化必须拒绝或明确披露。
大对象、日志和产物以身份和读取入口引用，不内联进列表（基线 §8.2）。

验收：消费方能判断返回范围、是否完整以及如何续取；列表不会隐藏截断，也不会被无界内容占满。

### COR-021：受控记录

确认令牌的密钥、已消费令牌和操作记录保存在工具的状态目录，默认 `~/.<tool>/`。
POSIX 上目录为 0700、文件为 0600；Windows 上依靠用户目录的默认 ACL 或显式设置 ACL，`context.state.protection` 如实报告是哪一种，未显式设置时不得声称「仅属主可读」（基线 SEC-SPEC §4）。
实现必须处理并发、链接与路径替换、写入中断和记录损坏。记录不可用时不得默认为空账本、未执行或已批准；失去记录会使修改不安全时，必须在派发前拒绝。

验收：记录损坏、越界链接和并发重放不能放行新的修改；错误给出核实方向。

### COR-022：可选公共结构

命令通过 `driver.profiles` 声明适用的结构：`core`、`batch`、`workflow`、`operation_status`、`query_page`。不具备某类能力的工具无需实现该结构。
结构分别按对应 Schema 校验，不能把只有字段的包装当作实现了行为保证。
状态中的命令入口（argv）只提供参数数据；调用方必须在已识别的 CLI 可执行入口内解析，不能把参数第一项当作另一个程序或 shell 执行。

验收：核心与可选结构可以按命令采用；嵌套结构同样接受结构及语义校验。

### COR-023：原生诊断与输入边界

已取得的原生错误码、调用阶段及是否派发必须在脱敏的结构化诊断中保留，原生消息列入 `_untrusted`；不得只按本地化消息文字猜测错误类型。未取得的事实必须标明未知。
参数校验必须在修改前完成；未知参数、无效枚举和超出声明范围的数值必须拒绝。需要文件或 JSON 输入时必须声明入口、大小上限和解析规则，不能用交互提示补齐。
单位与数值转换不得产生 NaN、无穷值或静默溢出；不支持的表示范围必须拒绝并说明限制。

验收：错误消息的语言改变不改变已知的原生分类；超界输入到不了原生写入。

### COR-024：需要人处理

原软件出现必须由人处理的状态时（模态对话框、登录或许可窗口、需要人批准、需要人完成的物理步骤、需要安装组件），同步调用返回基线 `E_HUMAN_REQUIRED`（退出码 9）。
`details.action` 取 `dismiss_dialog`、`sign_in`、`licence`、`approve`、`physical_step`、`install_component`、`other` 之一；`details.resume` 是人处理完后的续跑命令；`details.blocked_by` 是原生窗口或消息文字，列入 `_untrusted`；`details.dispatch_state` 说明修改是否已经派发，已派发时带 `operation_id`。
长任务改为在 `operation_status.blocked` 中报告。工具不得自动确认含义未知的对话框，也不得无限等待。

验收：模态框出现时调用在有限时间内返回 `E_HUMAN_REQUIRED`；已派发的修改仍能通过 operation_id 查询。

### COR-025：内置操作记录命令

驱动 CLI 必须提供三个内置命令：

- `operation show --id <operation_id>`：一条记录，含计划、状态、回执和事后登记，返回 `data.operation_status`；
- `operation list`：近期记录，可按状态过滤，结果有界并符合 query-page；
- `operation resolve --id <operation_id> --outcome applied|not_applied|partial --evidence <text>`：登记独立读回得到的结果。

它们只读写工具自己的操作记录，不改变目标。`operation resolve` 需要覆盖原操作效果的授权范围；操作仍在运行（执行租约未过期）时拒绝登记，报 `E_CONFLICT`（`lock_held`）。批量的记录按项登记，每项是独立的操作。
未登记的 unknown 操作阻止同一目标上的新 dry-run 和 confirm，报 `E_CONFLICT`（`unresolved_operation`）；仍在运行的操作同样阻止，报 `E_CONFLICT`（`lock_held`）。两种情况都在 `details.active_operation` 给出该操作，见 DRV-041。

验收：回复丢失后可以查询、读回、登记，再继续；登记之前，同一目标的写入被拒绝且不派发。

## 示例对照

以下正例可以直接对照条款阅读；每个正例都有违反单条规则的反例，见[示例索引](../examples/index.json)。

| 条款 | 正例 |
|---|---|
| COR-002、COR-003 | [确认成功](../examples/valid/response-applied-unsaved.json)、[部分应用](../examples/valid/response-partial.json)、[验证失败](../examples/valid/response-verify-failed.json)、[交付被拒](../examples/valid/response-delivery-rejected.json) |
| COR-004、COR-013 | [结果未知](../examples/valid/response-unknown.json)、[幂等重放](../examples/valid/response-replayed.json) |
| COR-005 | [未知参数](../examples/valid/response-usage-unknown-flag.json)、[缺确认令牌](../examples/valid/response-confirmation-required.json)、[状态漂移](../examples/valid/response-conflict-drift.json)、[缺授权](../examples/valid/response-scope-denied.json) |
| COR-007 | [reference](../examples/valid/reference-beta.json)、[--index](../examples/valid/reference-index.json)、[--command](../examples/valid/reference-command.json) |
| COR-009 | [context](../examples/valid/context-connected.json)、[doctor](../examples/valid/doctor.json) |
| COR-011、COR-012 | [dry-run](../examples/valid/response-dry-run.json)、[计划](../examples/valid/plan-estimate.json) |
| COR-014 | [已应用未保存](../examples/valid/receipt-applied-unsaved.json)、[仅保存](../examples/valid/receipt-file-saved.json)、[交付](../examples/valid/receipt-delivered.json)、[设备](../examples/valid/receipt-device-observed.json) |
| COR-016 | [批量计划](../examples/valid/response-batch-dry-run.json)、[独立批量](../examples/valid/response-batch-partial.json)、[依赖工作流](../examples/valid/response-workflow-partial.json)、[长任务](../examples/valid/status-running.json) |
| COR-020 | [列表](../examples/valid/query-snapshot-page.json)、[无法续取](../examples/valid/query-truncated-no-continuation.json) |
| COR-024 | [需要人处理](../examples/valid/response-human-required.json)、[长任务被模态框阻塞](../examples/valid/status-blocked.json) |
| COR-025 | [记录中的计划](../examples/valid/status-planned.json)、[未登记的操作阻止写入](../examples/valid/response-unresolved-operation.json)、[登记未知结果](../examples/valid/status-resolved.json) |

## 开放问题

- 各工具如何把领域对象和依赖映射到可复核的快照，需要按模式验证。
- 回执完整返回时，一次成功的修改约 1.6 KB。是否增加「回执摘要 + 按 operation_id 取全文」的可选结构，留待试点中按实际 token 消耗决定；失败信封始终返回完整回执。
- 会话过期、不同适配器和设备协议的身份刷新，需要声明与实测。
- 设备的专用联锁和物理恢复由领域规则定义，不能由本协议推定。
- 基线如果在 meta 中增加可选的请求关联字段，驱动层可以改用它；目前关联标识只出现在计划、回执和操作记录中。
