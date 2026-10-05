# 变更记录

## 未发布 — 工作版本 1.0.0，驱动结构 2.0

状态：草案。既有 Release 1.0.0 不替换。规范准入与原生工具逐任务验收分别进行；冻结发布需要新的不可变提交、规范包验收与新标签。

### 软件规范逐项对照

- 完整 Agent 评测保留八类强制场景的适用性，拒绝用三场景子集冒充完整符合；区分未测与不支持。
- 提供冻结 SVG 多模型任务输入、实际子进程录制及独立 Chrome 判定工具，不生成伪造模型轨迹。

- 对照当前 ai-native-cli-spec 提交 d673343，记录开发、机器契约、FCC、评测与交付的逐项落实和有意差异。
- 补产品元数据版本单源同步与漂移守卫，拒绝 pyproject、Skill/min_version 和生成 reference 的不同版本。
- 补 Agent eval 记录 Schema、离线哈希/轨迹/多模型覆盖检查和种子 CI 门禁；不宣称实际模型评测已执行。
- 两条规范工作流补依赖审计与有限的语法/未定义名称检查，标签工作流补 checksum 的 Sigstore keyless 签名与身份校验；真实发布签名待授权执行。
- 对齐种子 Skill 的未发布安装边界与 Release/SkillHub 约束。

### 可执行验收与收尾

- 增加 `check_graduation.py`：静态检查、回归、独立浏览器消费，保留全部源文件哈希和实际日志；提供 ZIP 时运行包内检查。
- 交付验证器由消费端规定必需正文、Schema、SDK、种子和可执行例子；拒绝哈希自洽的缺文件包，核实基线副本与锁定哈希。
- 增加真实 SVG 标题适配器，实际 CLI 子进程覆盖跨进程确认/查询、默认只读、人工漂移、非法输入与独立读回。
- 从 Xpedition、KiCad、Creo 的实现和证据边界提出首批工程任务验收；不声称本次完成原生适配或实测。
- 恢复 GitHub Release + SkillHub 产品交付配置，显式记录 LAY-008；版本号与机器结构分开固定。


### 定位

- 改为 ai-native-cli-spec 的驱动扩展层：驱动 CLI 先完整符合固定的基线（`v1.6.3`，逐字节保存在 `base/`，锁定记录 `base/base-lock.json`），本规范只增加驱动场景特有的要求。新增[基线与驱动层](docs/LAYERING.md)说明继承、收紧与新增的逐项关系。
- 新增机器可读的驱动契约 `contract/driver-contract.json`：固定的驱动扩展错误码、由回执推导 ok 与错误码的规则、错误详情的必含键、效果分类和范围文件约定。

### 破坏性变化

- 信封改为基线信封：删除顶层 `request_id` 与 `phase`，失败信封不再携带 data，驱动对象改放 `error.details`；`meta.notices` 改为基线的通知对象。
- 退出码改为基线核心表加驱动扩展表，不再由各工具自定；`E_OUTCOME_UNKNOWN` 为 6，`E_HUMAN_REQUIRED` 为 9，`E_BUSY` 为 7（可重试）。
- 写操作改用基线 `--dry-run` / `--confirm <token>`，删除 `--phase`；`operation_id` 在 dry-run 时分配，不再要求调用方自己生成 `--request-id`。
- reference 改为基线结构（`commands`、`schemas` 的 `fields`/`untrusted_fields`、`error_codes`、`exit_codes`、`risk_tier`、`release_readiness`）加每条命令的 `driver` 块和顶层 `driver_profile`；公共驱动 Schema 改为 URN 引用，不再内联。
- 回执增加交付维度（`outcome.delivery`、`deliveries[]`）、`failed_stage`、`capability_id`、`plan_id` 和 `replayed`；独立批量改用基线批量结构，`workflow` 只表示依赖工作流。
- 除 `observe` 外有任一效果的命令都是写命令，走 `--dry-run` / `--confirm`，包括打开文档（`session`）和导出文件（`artifact`）；这两种效果的最低风险档改为 T1。基线 §14 的 `update` 自更新是唯一例外（COR-008）。
- 长任务状态沿用基线 §16.2 的名称：`queued` 改为 `pending`，`completed` 改为 `succeeded`；驱动层只增加 `planned`、`cancel_requested`、`partial`、`unknown`。
- 时间一律为带 `Z` 的 UTC（基线 §8），公共 Schema 拒绝其他时区写法；基线通知的 severity 只有 info 与 warning。
- 「留下了效果」中的产物只算本次调用生成的（回执声明 `artifact` 效果）：只交付已有文件而被拒收时报 `E_NATIVE_FAILURE`，不再报 `E_PARTIAL`（DRV-018）。
- 批量汇总按基线 §15.5 只计已尝试的项，跳过的项单独计数。
- `driver_profile.record` 必须写明记录能否在 CLI 退出、重连、实例重启后继续查询。
- 固定记录（adoption-lock）增加 `source_kind`、`source_dirty`，可以记录取自 Git 检出或无版本副本的副本；`check_adoption` 只核对取自规范包的记录。
- 所有公共 Schema 的标识改为 `urn:tool-driver-cli-spec:<name>:2.0`。

### 新增

- 任务范围文件（scope Schema）：由人写，CLI 只读；缺省只读；`context.authorization` 展示；缺授权时 `E_FORBIDDEN` 给出缺什么、在哪里授予。DRV-042 写明它防护的对象。
- context、doctor、batch、changelog 的结构；doctor 的 authorization、native_backend、state_store 检查。
- 内置 `operation show`、`operation list`、`operation resolve`；未登记的未知操作阻止同一目标上的写入（`unresolved_operation`），仍在运行的操作同样阻止（`lock_held`），租约过期前不能登记；已提交的长任务同样持有租约，由每次观测续期（DRV-035、DRV-041）。
- LAY-007：操作记录写不进去时拒绝派发。这是对基线 §9「令牌存储失败时降级」的唯一偏离，理由写在条款里。
- 批量的 dry-run 计划（`total`、`targets`、逐项 `operation_id`）和批量的操作记录（`operation_status.items`）。
- 范围文件增加 `destinations`（允许交付的位置前缀，按 URL 的完整路径段比较，`share://release` 不覆盖 `share://release-evil`），`limits.max_operations` 开始生效并按范围 ID 累计；根目录和输出目录必须是绝对路径。
- `reference --index` 与 `reference --command` 的公共 Schema，及其语义检查。
- 每个错误都给出 `dispatch_state`；`unresolved_operation`、`lock_held` 冲突给出 `active_operation`。
- LAYERING 增加驱动 CLI 的自检清单；`check_spec` 核对正文中重复的错误码表、`problem`、冲突原因、人工动作、状态和效果列表与机器契约一致。
- 同步调用碰到模态框、登录或许可窗口时返回 `E_HUMAN_REQUIRED` 及 action、resume（COR-024）。
- 错误详情必须给出 `next_action`，用法错误给出 `problem`、`parameter`、`expected`。
- reference 的渐进发现：`reference --index` 与 `reference --command <path>`。
- [驱动 Skill 增补](docs/SKILL-ADDENDUM.md) 与 Skill 评测要求（VER-026）。
- DEL-001 不再禁止 npm：渠道由产品选择，要求至少一条验证过的 Agent 安装与升级路径；DEL-005 采用基线的 Sigstore 签名与验签。
- Python SDK 与种子工程重写：基线全局参数、确认令牌、范围解析、SQLite 操作记录、内置命令和带具体原因的错误；种子工程带规范副本、AGENTS.md、CHANGELOG、CI、测试骨架和对齐 SKILL-SPEC 的 Skill。
- SDK：按参数声明解析（以 `--` 开头的值写成 `--name=<value>`），派发前在同一事务里核对活动操作、幂等键和次数限制，执行期间续租，适配器明确未派发时令牌仍可再用，派发后的任何异常（含中断）报 `E_OUTCOME_UNKNOWN`，幂等键只重放记录过的回执，支持批量与 `update`，context 和 doctor 在适配器钩子出错时降级而不失败。

### 修正

- 本轮收尾审查：范围文件拒绝重复 JSON 字段；URL 授权拒绝编码分隔符隐藏的路径穿越；异步终态没有效果读回时保留 unknown 与目标阻塞；回执与原操作的计划、范围及目标身份不一致时不再接受为成功。
- 规范包校验增加内部身份一致性：已包含的 STATUS 必须等于 manifest.status，基线锁定记录必须与 manifest.base 一致；不以包内哈希一致掩盖声明冲突。
- Release 描述改为从 CHANGELOG 对应版本段生成，删除手写的 `docs/RELEASE-NOTES.md`。
- 规范仓库自己的校验工具输出改为基线信封，退出码改用基线表。
- `v1.0.0` 标签之后加入的开发支持（SDK、种子工程、产品注册表）没有以独立版本发布，内容并入 1.0.0；`v1.0.0` 的 Release 资产保持原样。

迁移说明见[实施与迁移指南](docs/ADOPTION-GUIDE.md)。

## 1.0.0 开发支持补充 — 2026-10-03

- 增加产品能力声明的同源生成、派生文件漂移检查和可实例化工程种子。
- 提供公共 Python SDK，以受控声明解析参数和发现能力，保留原生适配器的状态与授权职责。
- 增加能力索引与按命令详情、只读诊断提供方和最小 Skill 场景清单。

规范版本保持 `1.0.0`。本节对应主分支增强；已有 `v1.0.0` 标签和 Release 资产不替换，源码提交与文件哈希区分不同内容。

## 1.0.0 — 2026-10-03

- 冻结核心机器协议，增加公共操作状态、工作流、查询分页及规范采用锁定结构。
- 补齐可信授权引用、受控操作记录、阶段与实际效果、状态漂移及未知结果处理。
- 提供离线符合性、ZIP 完整性与消费项目副本校验，补齐真实命令边界测试及跨平台 CI。
- 增加受控 SVG 文件模式探针，通过独立浏览器读回与重新打开检查产物，并保留故意失败与回复丢失的状态。
- 提供实施与迁移指南，以及仅发布 GitHub Release 的规范包构建和发布流程。

规范与产品成熟度分别验收。`0.1.0` 未发布草案的采用者需更新发现目录、公共结构及相应守卫；变更详见实施与迁移指南。

## 草案补充 — 2026-10-03

- 补齐默认 JSON、UTF-8、非交互及请求成功与退出码的一致关系。
- reference 增加离线 Schema 目录、参数绑定、阶段、示例及错误码映射，并校验引用与示例输入。
- 明确查询完整性与有界负载、首次回复丢失后的查询身份、连接代际、锁失效及模态阻塞处理。
- 增加公开行为到实际测试报告的追溯，以及消费项目固定规范与检查漂移的要求。

本轮仍属 `0.1.0` 未发布草案。新增的 reference 字段是必需字段，已有草案采用者需更新发现输出。

## 0.1.0 — 2026-10-02

状态：草案；未发布 Release，未上传 SkillHub。

- 建立核心协议、应用与设备操作、交付、验证四份独立规范。
- 定义任务范围授权、计划等级、实际状态、操作回执和未完成验证的表达。
- 区分运行实例、文件直编和设备模式，区分独立批量与依赖工作流。
- 明确 GitHub Release 与 SkillHub 交付链路，不默认依赖 npm 分发或安装。
- 增加 JSON Schema、正反例、静态校验及可追溯规范包构建。

本版本的校验只覆盖规范结构与合成样例，不代表实际工具能力已通过验证。
