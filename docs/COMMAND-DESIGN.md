# 从应用能力设计命令树

规范版本：`1.0.2`；基线：ai-native-cli-spec `v1.6.3`。

本文落实 COR-026 的开发流程。先调查应用，再设计用户任务和命令；不能从现有 CLI 命令数反推应用能力，也不能把缺少公开 API 当作应用不支持。机器检查核对记录、引用和字节，应用调查是否完整、命令粒度是否合适仍需要实际任务和人工审阅。

## 先取得可核对的应用清单

记录目标 Application 的产品名称、实际版本、平台/架构/模式、许可条件与来源。调查用户能完成的工作、资源、会话生命周期、保存/导出和检查能力；从官方文档、实际人工操作、接口调查或真实运行取证。明确版本与许可限制。没有证据时保留 unknown；GUI 可完成而没有 API 的工作，应用支持与自动化可达性必须分别记录。

`registry.json.design` 是开发数据，符合 [product-design Schema](../schemas/product-design.schema.json)：

| 数据 | 含义 |
|---|---|
| `application` | 应用版本、许可、环境与证据引用；环境限定本记录所述运行范围 |
| `scope` | 本轮调查范围、清单 ID、清单来源、范围之外的部分和限制 |
| `capabilities` | 每项能力的应用支持、自动化可达性、适配器实现、CLI 暴露、实测状态和处置原因 |
| `tasks` | 用户目标、关键参数、命令、适配器入口、读回判据和测试引用 |
| `commands` | 每条注册命令的能力/任务映射，或明确的工具管理角色及理由 |
| `evidence` / `tests` | 实际文件哈希、来源、运行绑定与逐命令读回检查；fixture 单独标识 |
| `tree_decisions` | 命令树取舍、替代方案和原因 |
| `coverage` | 显式能力分母及 FCC 的声明命令范围；不填写自报的百分比 |

能力的五个维度分别填写：

- 应用支持：`supported` / `unsupported` / `unknown`。
- 自动化：`reachable` / `unreachable` / `unknown`；缺少 API 只能影响接口调查，不能自动推出应用 unsupported。
- 适配器：`implemented` / `unimplemented` / `unknown`。
- CLI：`exposed` / `not_exposed`；暴露了拒绝型占位命令不等于已实现。
- 实测：`verified` / `available_unverified` / `failed` / `blocked` / `unknown` / `not_run`。

调查清单中的每项能力都应说明 `exposed`、`deferred`、`excluded` 或 `unknown` 的处置与原因。清单 ID、能力 ID 和覆盖分母必须一致，避免省略困难项后声称完整覆盖。范围外的工作可显式排除；这不使排除项变成已完成。分母只代表声明的调查范围，不证明应用全部能力已被发现。

## 从任务选择树形与粒度

先列有用任务及验收结果，再识别资源和动作。沿用基线 §12 的统一命名、最短明确任务、非歧义参数与机器发现；沿用 §8.2 的重子资源独立获取、§8.3 的作用域与完整性。命令效果和注册要求仍由 COR-007/008 判定，生命周期、批量和依赖工作流仍遵循 COR-016 与 DRIVER-SPEC。

可以按资源组织查询和编辑，也可以为有明确结果的跨资源任务提供高层命令。记录为何合并或拆开命令，如何选择目标与范围，重负载怎样按需读取，哪些用户步骤仍需人工或尚不可达。没有固定 CRUD 集合、树深度、根词或 API 一比一映射要求；`target inspect/apply` 只是种子占位，必须结合真实应用重新设计。

每条领域命令必须能沿引用找到能力和任务；生成器补入的 reference/context/doctor/changelog/operation 属于工具管理，不计作应用能力覆盖。产品另加的工具管理命令也要写明角色与理由。已存在的路径唯一性、叶子不能兼作父组、参数与效果检查继续由现有 reference 校验器负责。

## 支持声明怎样取证

任务保持 `planned`、`blocked` 或 `unknown`，直到实际证据满足 `supported` 条件。支持任务必须关联每条命令的关键参数（至少包含全部必填参数）、真实适配器源文件及入口、读回判据和实际通过的命令测试。入口使用 `adapter_entries` 的命令路径、实现证据 ID 与入口符号描述；检查器读取实现文件及哈希，但不导入或执行它，也不证明入口能够完成任务。

证据路径相对注册表目录，必须是有界、普通、非链接的文件；SHA-256 与实际字节相同。文档证据保存实际来源材料并记录来源和摘要；仅填写一个远端地址不能代替可检查的材料。已知应用支持需要文档或真实运行证据；许可未知、连接不可达和未实施均保留各自的限制。

`real_run` 使用既有 [evidence Schema](../schemas/evidence.schema.json)，绑定 run ID（`evidence_id`）、source commit、实际应用版本及平台/架构。应用/设备组件身份须实际观测；命令、能力 ID、目标、快照和必需检查须对应。它还引用一个实际文件中的 [verification-result](VERIFICATION-RESULTS.md)，由 expected/observed、单位/容差、来源、快照、覆盖与独立性推导结果；观察来源引用另一个有哈希的 `observation` 文件。执行证据、读回 profile、观察文件、实现文件各自留存。`contract`、模拟适配器或 fixture 不能替代 real_application/artifact_consumer 记录。

`tests` 将任务、命令、运行证据和读回判据 ID 闭合。观察文件须为 JSON，并用 `measurements` 将判据 ID 映射到实际 `{value, unit}` 数值的 JSON Pointer；profile 的 observed 与这些实际字节不一致时必须拒绝。`passed` 只有在这些文件和绑定一致、必需检查通过、实际 expected/observed 推导通过时成立。声明了 `passed` 而没有实际文件，或 blocked/unknown/not_run 被改成完成，检查必须失败。记录真实性和来源认证仍要靠可信执行、独立复核及发布签名；本入口不会替适配器获取读回或认证应用。

## 执行开发检查

```powershell
python scripts/check_product_design.py --registry examples/development/product-registry.json --require-design
python scripts/generate_product.py --registry examples/development/product-registry.json --output dist/product-generated
python scripts/generate_product.py --registry examples/development/product-registry.json --output dist/product-generated --check
```

生成器在写任何输出前检查设计；生成的 `development-design.json` 保存记录、覆盖计数、实际核对的文件哈希与限制，属于开发产物。旧注册表没有 `design` 时继续兼容，并输出 `recorded: false`，不据此声称设计或应用能力已验收。新种子工程的 CI 使用 `--require-design`，占位记录通过只意味着引用一致，verified 计数仍是零。

public reference、driver_profile、SDK 运行时信封及公共驱动结构仍为既有 2.0/1.0，不增加设计字段。增加的开发输出受现有生成器所有权与漂移保护；手改、无主同名文件仍拒绝覆盖。FCC 需要另外执行命令级测试；`development-design.json` 不会把它翻成 verified，也不会决定发布就绪。

正反例在 [示例索引](../examples/index.json)；缺证据、悬空引用、分母遗漏、未知冒充已验证与虚假任务完成会被拒绝。哈希变化、fixture 冒充真实运行、应用版本/环境/源码不匹配、实际读回失败等边界由 `tests/test_product_design.py` 覆盖。这些测试材料是合成契约测试，不是应用能力验收证据。
