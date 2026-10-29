# 实施与迁移指南

规范版本：`1.0.2`；基线：ai-native-cli-spec `v1.6.3`。

本文供驱动 CLI 的实现者和适配器作者采用本规范，假设读者了解 JSON、命令行测试和目标工具的基本操作。分三种起点：新建工具、已有的基线驱动 CLI、按 1.0 实现的工具。

## 先确定首批范围

从一个可以核实的目标和一组完整操作开始，例如观察、计划、修改、读回、保存和重新打开。
在运行实例、文件或设备模式中选定实际采用的模式，列出要授权的效果、目标、根目录和输出目录。
没有的会话、撤销、设备或保存能力声明为不适用，不为凑齐命令目录虚构底层保证。

## 当前实施路线

1. 采用固定的软件 CLI 基线加驱动扩展，规范版本为 1.0.2、驱动结构为 2.0。历史标签、源码和 Release 记录保留；旧 Release 上传附件已于 2026-10-29 清理。请固定所采用的源码提交，从干净 Git 检出运行 `python scripts/build_spec_bundle.py` 构建规范包，并按下述结构迁移说明升级。
2. 规范按 VER-024、DEL-025 验收，提供种子、SDK、已实现文件适配器和可执行毕业入口；不把三个工具全部迁移设为规范毕业门槛。
3. 每个工具按 [工程任务验收](ENGINEERING-ACCEPTANCE.md) 选定首批闭环；未实测的环境和命令不提升成熟度。产品交付保持 GitHub Release 打包、SkillHub 分发。

## 新建工具

用种子工程起步（详见[工具工程](DEVELOPMENT-GUIDE.md)）：

```powershell
python scripts/instantiate_starter.py --name demo-cad-cli --profile session --output D:/work/demo-cad-cli
```

生成的工程已经符合基线的信封、错误码、自描述命令和写操作流程，带规范正文与基线副本、AGENTS.md、CHANGELOG、CI、命令级测试骨架和对齐 SKILL-SPEC 的 Skill。之后的工作是：

1. 在 `registry.json` 声明命令，重新生成派生文件；
2. 在 `<package>/adapter.py` 逐条实现原生调用，计划不改目标，执行后读回；
3. 逐步补命令级测试和适用失败路径，如实记录已测与缺口；完整 FCC 守卫作为单独检查，失败不得写成通过；
4. 用真实应用或独立消费者取得证据，再提高命令的成熟度；
5. 按[交付规范](DELIVERY-SPEC.md)构建三端真实包，明确每端架构与运行前提，并记录实际包安装、启动和关键操作 smoke；声明渠道和升级路径的实测范围。

种子工程沿用软件规范的共同规则与语言叠加思路；基线文件以 `.agent/driver/base/` 中固定的版本为准（LAY-002），不要在两处各自升级。分发按 LAY-008 的 Release + SkillHub 约束实现。

## 迁移已有的基线驱动 CLI

creo-cli、xpedition-cli、kicad-cli、auto-cad-cli 这类工具已经符合基线，迁移是增量的，不需要重写 Agent 面：

| 增加或调整 | 做法 |
|---|---|
| 驱动规范版本 | reference 和 context 增加 `driver_profile`；固定基线标签与本规范版本 |
| 命令的 driver 块 | 为每条命令补 `capability_id`、effects、phases、modes、maturity、environments、limits、recovery、profiles、error_codes、evidence_refs |
| 扩展错误码 | 对照 [LAY-004](LAYERING.md#lay-004驱动扩展错误码) 统一退出码；例如结果未知固定为 `E_OUTCOME_UNKNOWN`、退出码 6 |
| 授权 | 现有的写权限开关（例如 `CREO_CLI_PERMISSION`、配置文件中的 `permission`）改为任务范围文件，或在过渡期由开关映射为范围 |
| 计划与回执 | dry-run 返回 `data.preview` 计划（含 `operation_id`）；confirm 返回五个维度的回执；错误码按回执推导 |
| 打开、导出等命令 | 除 observe 外有效果的命令都改为 write，走 dry-run / confirm（COR-008）；原来直接执行的导出命令要拆成计划和确认两步 |
| 操作记录 | 提供 `operation show/list/resolve`；已有的「确认后才继续写」机制（如 creo-cli 的 `operation acknowledge`）对应 `operation resolve` |
| 人工介入 | 模态框、登录与许可窗口统一报 `E_HUMAN_REQUIRED` 并给出 `action`、`resume` |
| Skill | 入口 Skill 增加[驱动 Skill 增补](SKILL-ADDENDUM.md) 的段落；多 Skill 家族按基线 SKILL-SPEC §7 |

各工具先验收一个真实任务，再按命令扩展支持范围。可考虑已有回执状态、写前读回和操作登记的工具；迁移工作量仍应以其当前代码与真实环境验证为准。试点结束的判据是：

- 产品的 reference、context、doctor 与真实调用的信封都通过 `validate_contract.py`；
- 有一次在真实应用上的「dry-run → confirm → 读回 → 回复丢失 → 查询 → 登记」记录；
- 已进行的 Skill 评测按 VER-026 留存结果；未运行时明确标注，不以此代替平台包 smoke。

## 从已发布的驱动结构 1.0 迁移

规范 1.0.1/1.0.2 的驱动结构 2.0 与已发布规范 1.0.0 的结构 1.0 不兼容。必须按规范版本、结构、来源和副本哈希识别，逐项迁移：

| 1.0 | 2.0 |
|---|---|
| 顶层 `request_id`、`phase` | 删除；信封为基线信封，计划和回执里有 `operation_id`、`plan_id` |
| 失败信封带 `data` | 驱动对象改放 `error.details`（receipt、workflow、operation_status） |
| 各工具自定退出码 | 基线核心表加驱动扩展表 |
| `--phase plan/apply`，调用方必须给 `--request-id` | `--dry-run` / `--confirm <token>`；`operation_id` 在 dry-run 时分配；`--request-id` 只是可选幂等键 |
| `capabilities[]`、参数 `binding` 与 `location`、内联公共 Schema | 基线的 `commands[]` 加 `driver` 块；参数为 `name/type/required/multiple`；公共 Schema 用 URN 引用 |
| `workflow.kind: independent_batch` | 独立批量改用基线批量结构；`workflow` 只表示依赖工作流 |
| 回执四个维度 | 增加 `delivery` 维度和 `deliveries[]`、`failed_stage`、`capability_id`、`plan_id`、`replayed` |
| 长任务状态 `queued`、`completed` | 基线 §16.2 的 `pending`、`succeeded`；另有 `planned`、`cancel_requested`、`partial`、`unknown` |
| `session`、`artifact` 效果的命令可以是 read | 除 observe 外有效果的命令都是 write；`session`、`artifact` 的最低风险档为 T1 |
| `meta.notices` 为字符串 | 基线通知对象；弃用提示改写到 stderr |
| Schema 标识 `...:1.0` | `urn:tool-driver-cli-spec:<name>:2.0` |
| `authorization_scope_id` 的来源未定义 | 由人写的范围文件，CLI 只读（DRV-009） |
| GitHub Release + SkillHub | 保持相同渠道；按 DEL-001 验收实际 Agent 安装与升级路径 |

按 1.0 的产品注册表需要改写为 2.0 格式（见[开发样例](../examples/development/product-registry.json)）；1.0 种子工程生成的项目建议用新种子重新生成，再把适配器逻辑迁过去。

## 固定公共契约

1. 从获授权的来源取得确定版本的规范包，核实包的校验值和组件清单。
2. 在项目中记录规范版本、驱动结构版本、基线标签与提交、规范包校验值，以及每个公共文件的校验值，符合 [adoption-lock Schema](../schemas/adoption-lock.schema.json)。
3. 原样保存公共 Schema、驱动契约、基线副本与校验入口，用本地副本做离线检查；升级不临时拉取分支的最新内容。
4. 领域规则单独维护，专有字段放进 `extensions`；不修改公共字段、枚举、错误码含义或引用定义。

固定版本的检查入口如下，在取得的规范包根目录调用，尖括号表示需要替换的实际路径：

```powershell
python scripts/check_adoption.py --lock "<固定版本记录.json>" --root "<消费项目目录>" --bundle "<已取得的规范ZIP>"
```

它只读固定记录、规范 ZIP 和登记的副本，核实包哈希、来源提交、基线锁定和副本字节；拒绝越界、同名冲突、缺失文件、符号链接和 junction；不联网、不更新副本。固定记录本身必须来自受控来源。种子工程用 `.agent/driver/starter-lock.json` 和 `check_project.py` 完成同样的检查；这份记录同样符合 adoption-lock Schema，`source_kind` 为 `git_checkout` 或 `unversioned_copy`，没有包哈希。

## 把静态检查与实际调用分开

静态符合性检查处理公共 Schema、reference 的 driver 块、错误码表、示例和由回执推导的错误码：

```powershell
python scripts/validate_contract.py --schema reference --input examples/valid/reference-beta.json
```

可选的 `--schema` 为 response、reference、reference-index、reference-command、context、doctor、changelog、receipt、plan、operation-status、workflow、batch、query-page、scope、release-manifest、evidence 和 adoption-lock；`-` 表示从 stdin 读取。
通过时退出码为 0，不符合为 2（`E_VALIDATION`），用法错误为 2（`E_USAGE`），输入 I/O 失败为 1（`E_IO`）。诊断说明失败的位置和约束，不复述输入值。

静态检查不执行示例，也不能证明 CLI 实际接受这些参数、按声明退出或产生真实修改。产品必须另外运行命令级测试，保存输入、输出、退出码、环境和测试报告，并关联到命令。模拟适配器只用于协议的失败路径；真实文件、运行应用和设备的证据分别标记。

## 规范仓库自身的检查与打包

```powershell
python scripts/check_spec.py
python -m unittest discover -s tests -v
python scripts/build_spec_bundle.py
python scripts/verify_spec_bundle.py --bundle dist/tool-driver-cli-spec-1.0.2.zip --checksum dist/tool-driver-cli-spec-1.0.2.sha256
```

构建只在工作树干净时进行；ZIP 校验不解压到磁盘，默认解压上限 32 MiB，拒绝加密、分卷、ZIP64 和链接条目。哈希不符为 `E_INTEGRITY`（退出码 1），结构错误为 `E_VALIDATION`（2）。没有独立的期望值时，只能报告包内部一致，不能认证来源。

## 交付验收

规范包按[规范发布门禁](DELIVERY-SPEC.md#del-025规范发布门禁)校验；产品包按[产品发布门禁](DELIVERY-SPEC.md#del-019产品发布门禁)验证三端实际包安装、启动与关键操作。旧基线 FCC 与 `release_readiness` 保持真实语义，不作为新平台支持的通用前提（LAY-009）；完整覆盖、恢复和多模型评测按证据单独报告。

版本化迁移：旧产品继续按其固定版本解释 `reference.release_readiness` 和 `doctor.release_readiness`，不能修改旧字段使之冒称 stable。采用含 LAY-009 的新驱动规范版本后，发布脚本直接执行 `node scripts/check-platform-delivery.js check <包目录> <记录目录> <名称> <版本> --expected-source-sha <40位提交>`，消费各目标的一份 1.0 版 `smoke-<os>-<arch>.json`，并核对实际包和归档内可执行文件。各目标的记录由对应系统运行 `smoke` 生成，包含依赖及真实结果。它只覆盖包冒烟；保留并执行原有授权、安全测试、审计和签名流程。旧脚本须迁移旧就绪等级总门禁，不能把具体授权或安全失败当覆盖缺口忽略；未迁移的消费者仍会阻止，不能宣称已兼容。候选工作流不自动发布，产品现有发布流程须接入上述检查器。
各渠道交付同一套可追溯的产物；上传、绑定、发布和实际安装分别记录结果。
