# 基线与驱动层

规范版本：`1.0.2`；状态：`stable`；驱动结构版本：`2.0`；基线：ai-native-cli-spec `v1.6.3`。

本文面向驱动 CLI 的实现者和验收人员，说明本规范与 ai-native-cli-spec 的关系：哪些原样继承，哪些在驱动场景下收紧，哪些是本规范新增的。
读者应已读过基线的 CLI-SPEC、SKILL-SPEC 和 SEC-SPEC，原文保存在 [base/ai-native-cli-spec/](../base/ai-native-cli-spec/CLI-SPEC_zh.md)。

## 为什么分层

驱动类 CLI 首先是给 Agent 用的 CLI。它和舰队里其他工具说同一种信封、同一张错误码表、同一套自描述命令，Agent 的 Skill、错误决策树和更新流程才能复用。

驱动真实应用、应用文件和设备，又有基线没有覆盖的问题：运行中的会话、未保存的内存修改、长任务、模态对话框、依赖与版本漂移、领域验证和物理动作。本规范只补这一部分，不另起一套输出、错误和命令约定。

## 符合关系

### LAY-001：先符合基线

驱动 CLI 必须先完整符合固定版本的基线：CLI-SPEC 的输出、错误、写操作、自描述、批量与更新契约，SKILL-SPEC 的 Skill 规则，SEC-SPEC 的风险分级与安全基线，以及适用的 REPO-SPEC 仓库约定。
本规范的条款只能在基线之上增加约束，或使用基线允许扩展的位置（data、error.details、reference 与 context 的附加键、扩展错误码），不得放宽基线的「必须」。与基线存在明确差异的规定是 LAY-007（记录不可用时拒绝派发）和 LAY-008（分发渠道），条款中说明了理由。

验收：同一驱动 CLI 先通过基线的检查清单和 contract.json 一致性测试，再通过本规范的检查。

### LAY-002：固定基线版本

本规范每个版本固定一个基线标签，记录在 [base/base-lock.json](../base/base-lock.json)，并逐字节保存基线文件。
基线升级时，本规范必须发布新版本并列出受影响的条款。产品同时固定基线版本和驱动规范版本，不得只固定其中一个。

验收：base/ 中的文件与锁定记录的 SHA-256 一致，`scripts/check_spec.py` 离线核对；产品的固定记录同时含两个版本。

### LAY-003：识别驱动 CLI

信封保持基线原样：`schema_version` 仍为 `"1.0"`，顶层和 meta 不增加任何键。
消费方通过 `reference.driver_profile` 和 `context.driver_profile` 识别驱动 CLI，读取驱动规范版本、驱动结构版本和基线版本。

验收：只看信封无法区分驱动 CLI 与其他舰队工具；reference 的 driver_profile 给出 tool-driver-cli-spec 版本与基线标签。

## 继承与细化一览

| 基线机制 | 本规范的处理 | 条款 |
|---|---|---|
| 单个 JSON 信封、stdout/stderr、UTF-8 | 原样继承；驱动对象成功时在 data，失败时在 error.details | COR-001、COR-002 |
| 核心错误码、退出码、retryable | 原样继承；增加固定的驱动扩展码 | LAY-004、COR-005 |
| `_untrusted` | 原样继承；规定驱动场景必须标注的来源 | COR-006 |
| reference / context / doctor / changelog | 原样继承；增加 driver_profile、命令的 driver 块、授权与环境、四项 doctor 检查、渐进发现 | COR-007、COR-009 |
| `--dry-run` → `--confirm`、确认令牌 | 原样继承；除 observe 外的效果都走这道门；dry-run 返回驱动计划，令牌绑定基线快照与授权范围 | COR-008、COR-011、COR-012 |
| 风险档与 `--dangerous` | 原样继承；按效果给出最低风险档和必须的危险标记 | COR-008、DRV-039 |
| 幂等键与单次令牌 | 原样继承；重放返回原回执并标记 | COR-013、DRV-027 |
| 令牌存储失败时降级（§9） | **偏离**：操作记录写不进去时拒绝派发 | LAY-007 |
| 批量（items[] + summary） | 原样继承；dry-run 计划逐项列出 operation_id，结果逐项附回执；依赖工作流另行定义 | COR-016、DRV-022、DRV-023 |
| 分页、`--fields`、`--compact` | 原样继承；增加完整性字段 | COR-020 |
| 长任务（§16.2，可选模式） | 沿用基线状态名，增加 planned、cancel_requested、partial、unknown；增加内置 operation 命令 | COR-016、COR-025、DRV-035 |
| 人工介入 E_HUMAN_REQUIRED（§16.3，可选模式） | 驱动 CLI 必须启用；规定模态框、许可登录、物理步骤的 action | COR-024 |
| 凭证生命周期与落盘 | 原样继承 | — |
| 自更新、版本通知、Skill 同步 | 原样继承；自更新不走确认门，验签按 DEL-005 | COR-008、DEL-005、DEL-017 |
| 功能契约覆盖率与发布就绪 | 原样继承；增加逐命令成熟度 | VER-001、VER-002 |
| Skill 编写规范 | 原样继承；增加驱动 Skill 必须写的内容 | [SKILL-ADDENDUM](SKILL-ADDENDUM.md) |
| 供应链（签名、审计） | 原样继承；覆盖加载进原应用进程的组件 | DEL-005 |
| 分发 | GitHub Release 打包、SkillHub 分发；不要求基线的 npm 壳 | LAY-008、DEL-001 |

### LAY-004：驱动扩展错误码

驱动 CLI 使用下列错误码时，必须使用表中的退出码和 retryable。产品自定义的其他扩展码遵循基线扩展规则。

| 错误码 | 退出码 | retryable | 含义 |
|---|---|---|---|
| `E_UNSUPPORTED` | 2 | false | 当前构建、模式或会话无法执行这个合法请求；换能力 |
| `E_BACKEND_UNAVAILABLE` | 4 | false | 应用、服务、插件或设备缺失、不可达、未授权许可或协议不符；未派发 |
| `E_PROTOCOL` | 1 | false | 后端回复无法解析；先看 dispatch_state 再决定后续写入 |
| `E_BUSY` | 7 | true | 主线程或目标正忙；未派发；稍后重试 |
| `E_NATIVE_FAILURE` | 1 | false | 原应用拒绝操作且没有留下效果；读回执 |
| `E_PARTIAL` | 1 | false | 部分阶段或部分项已生效；读回执，不重发整批 |
| `E_OUTCOME_UNKNOWN` | 6 | false | 可能已执行但结果无法确定；先查询记录、读回目标 |
| `E_VERIFY_FAILED` | 1 | false | 已生效，但必需的读回检查失败 |
| `E_VERIFY_INCOMPLETE` | 1 | false | 已生效，但必需的读回检查没能完成 |
| `E_HUMAN_REQUIRED` | 9 | false | 基线已知扩展；对话框、登录或许可、审批、物理步骤需要人先处理 |

基线的 `E_TIMEOUT`、`E_INTERRUPTED` 可重试，所以驱动 CLI 只在尚未派发、或已观测到没有留下任何效果时使用它们；已派发而结果未观测到时一律报 `E_OUTCOME_UNKNOWN`。
`E_OUTCOME_UNKNOWN` 用退出码 6：基线对 6 的处置是「重新读取状态」，只看退出码的调用方因此会先查询记录、读回目标，而不是重发；信封中的 `retryable: false` 进一步禁止盲目重试。`E_BACKEND_UNAVAILABLE` 用 4（配置或环境问题，不重试），`E_BUSY` 用 7（可重试的瞬时状态），都沿用基线退出码的处置含义。
机器形式见 [contract/driver-contract.json](../contract/driver-contract.json)。

验收：reference.error_codes 中出现的核心码和驱动码，退出码和 retryable 与基线表及本表一致。

### LAY-005：不新增全局参数

控制参数沿用基线：`--dry-run` 取计划，`--confirm <token>` 执行，危险命令两次调用都带 `--dangerous`；`--request-id` 和 `--idempotency-key` 是可选幂等键。
1.0 的 `--phase` 删除。驱动层只给 reference 增加 `--index` 和 `--command <path>` 两个发现参数（COR-007）。

验收：命令参数不与基线全局参数同名；写命令不需要基线之外的参数即可完成计划和执行。

### LAY-006：与基线冲突时

基线后续版本若与本规范冲突，以基线为准，本规范发布新版本修订相关条款。修订发布之前，产品不得升级到冲突的基线版本。

验收：base-lock 只记录一个基线标签；基线升级的变更记录列出受影响条款。

### LAY-007：记录不可用时拒绝派发

基线 CLI-SPEC §9 要求令牌存储失败时优雅降级、不阻塞写。驱动 CLI 反过来：操作记录（含计划、已消费令牌和租约）写不进去时，必须在派发前拒绝，报 `E_IO`，`dispatch_state` 为 `not_started`。
理由：驱动的目标是运行中的应用和设备，回复丢失后只能靠派发前写下的记录查询和登记（COR-013、DRV-041）；没有记录的派发一旦丢失回复，就既不能确认也不能安全重试。机器形式见契约的 `deviations`。

验收：状态目录不可写时，写命令的 dry-run 和 confirm 都被拒绝且目标不变；context 和 doctor 的 `state_store` 报告原因。

### LAY-008：产品交付渠道

基线 REPO-SPEC §4b 的 npm 分发壳不作为本驱动规范的产品要求；产品使用 GitHub Release 打包、SkillHub 分发。原生多文件组件的来源、安装、升级和加载身份仍按 DEL-001 至 DEL-021 实测，不能用 SkillHub 登记成功代替安装成功。原因是工程工具的原生服务、插件、许可和加载生命周期不同于软件 CLI 壳。

这是交付配置的明确偏离，不改变基线的信封、错误码、命令、Skill 内容和安全要求。具体工具未验证 SkillHub 路径时保留该限制，不宣称全工具已完成交付。

验收：README 与 Skill 使用同一已验证渠道；未经验证的渠道明确披露。

## 自检清单

驱动 CLI 发布前，在基线的检查清单之外逐项确认：

- [ ] reference、context 带 `driver_profile`，其中 `base.version` 与 `spec_version` 同时固定（LAY-002、LAY-003）
- [ ] 错误码表中的驱动扩展码与 LAY-004 一致；已派发后没有可重试的超时或中断（LAY-004）
- [ ] 除 observe 外有效果的命令都是 write，走 `--dry-run` → `--confirm`；`update` 除外（COR-008）
- [ ] 修改调用的 ok 和错误码按回执推导；每个错误都有 `dispatch_state` 和 `next_action`（COR-003、COR-004、COR-005）
- [ ] 没有范围文件时只读；越界、超次数、缺交付位置都在派发前报 `E_FORBIDDEN`（DRV-009、DRV-010）
- [ ] dry-run 分配 `operation_id`，记录在派发前写入；记录不可用时拒绝派发（COR-013、LAY-007）
- [ ] 提供 `operation show`、`operation list`、`operation resolve`；未登记的未知操作和仍在运行的操作阻止同一目标的写入（COR-025、DRV-041）
- [ ] 执行中的操作有租约，CLI 异常退出后记录在有限时间内转为 unknown（DRV-035）
- [ ] 支持 `reference --index` 和 `reference --command`，不内联公共驱动 Schema（COR-007）
- [ ] 模态框、许可登录等返回 `E_HUMAN_REQUIRED`，不自动确认（COR-024）

## 与 1.0 的差异

2.0 是破坏性版本。主要变化：信封改为基线信封，删除顶层 `request_id`、`phase` 和失败时的 data；退出码改为基线表加驱动扩展表；reference 改为基线结构加 driver 块；写操作改用 `--dry-run` / `--confirm`；增加 context、doctor、scope、batch、changelog 的结构，交付维度和操作记录命令。
逐项迁移说明见[实施与迁移指南](ADOPTION-GUIDE.md)。

## 开放问题

- LAY-007 与基线 §9「存储失败不阻塞写」相反。应当在基线中为「回复丢失后必须能查询」的工具增加这一例外；基线采纳之前，这是本规范有意保留的偏离，基线升级时逐版核对。
- 基线如果在 meta 中增加可选的请求关联字段，驱动层可以改用它；目前关联标识只出现在计划、回执和操作记录中。
- 基线 §14 要求 doctor 检查版本是否满足 Skill 的 `min_version`，但没有规定 CLI 如何得知 Skill 期望的版本。驱动层目前让 Skill 的前置体检比较 `context.version` 与 `min_version`（DEL-017）；基线若给出 CLI 侧的机制，驱动层随之采用。
