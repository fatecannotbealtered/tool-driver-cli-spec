# 可复用的结构化验证结果

这是 VER-010/011 所需读回与独立判定的一种可选记录格式，不新增行业支持义务。它放在既有 `receipt.outcome.verification.extensions.verification_result`，使用 [verification-result Schema](../schemas/verification-result.schema.json)。不改变公共信封、回执键、状态、错误码或 `driver.profiles` 枚举；未采用它的旧回执按原契约校验。
通过扩展值的 `profile` URN 显式选择该格式。同名但未使用该 URN 命名空间的旧私有扩展保持原语义；该命名空间内不支持的版本会被拒绝。产品可在自己的 Schema 中用 `$ref` 声明此扩展，让发现接口明示其格式。

## 记录与推导

| 字段 | 含义 |
|---|---|
| `profile` | 固定为 `urn:tool-driver-cli-spec:verification-result:2.0` |
| `target` / `snapshot` | 使用公共目标与快照结构；快照未知时为 null |
| `requirements[]` | 当前任务必需检查的 ID、field/structure/visual 类型、RFC 6901 字段路径、原始 expected、单位和比较规则 |
| `observations[]` | 按 requirement ID 保留原始 observed；整个 observed 为 null 表示未读到，`{"value": null, "unit": null}` 则是实际 JSON null |
| `source` | 实际读回/判定来源、完成状态、目标与快照、方法、证据引用、缺陷来源与独立性依据 |
| `source.coverage` / `not_checked` | 实际检查路径、未覆盖路径、是否必需及原因；范围必须明确 |

先确定任务的预期值和必需读回项，再执行写入与独立观察；不要从写接口的返回值生成 observed。比较支持严格 JSON 等值（布尔值不当作数字）、同单位的绝对容差，以及按稳定 finding 身份比较 `no_new_findings`。容差不执行隐式单位换算。
`no_new_findings` 的 expected 是基线 finding 数组，observed 是当前数组，`identity_fields` 给出规则、对象等稳定身份路径。仅比较问题数量会漏掉“旧问题消失、新问题出现”；缺少身份、重复身份或只有数量时不能得出通过。

来源区分 `application_readback`、`file_consumer`、`device_readback`、`native_checker`、`custom_checker` 等。要求官方/原生检查器时，`allowed_sources` 只允许 `native_checker`，自定义解析器的零错误不能替代该要求。截图只能用于明确声明的 visual 项，不能满足 field/structure 读回。`input_echo`、`writer_self_check`、不支持与不可用都不能充当有效结构观察。

每个 requirements 项都会生成既有格式的必需 check。缺少观察、observed 不可用、source 未完成（running/timeout/unknown）、目标或快照不匹配、覆盖缺口、独立性依据不明，均为 incomplete。值确实不符合预期则为 failed。已完成的零问题结果也只证明它实际覆盖的规则。
独立判定项声明 writer、expectation 和 observation 的缺陷来源 ID；已知重叠或任一来源未知时不通过。改名或填写一段依据不能把同一个有缺陷的算法变成独立检查器。

快照绑定检查 ID、来源、revision、依赖和附加身份，允许同一不可变状态的观察时间不同。source 及 profile 快照都要对应回执的 `snapshot_after`；旧快照、旧对象或旧连接代际不能套到当前状态。适配器仍须保证快照 ID/版本准确且不可复用来掩盖状态变化。

## 接入 SDK

```python
from tool_driver_sdk import build_verification

# record 来自当前任务的要求和实际读回；不是从输入复制的“成功”结果。
verification = build_verification(record, scope="对象宽度及指定规则", validator=validator)
receipt_fields["outcome"]["verification"] = verification
```

SDK 在回执入库前重新校验、绑定并推导这些检查，保留 expected/observed 及其来源；适配器先写 passed 也不能越过它。失败仍沿 COR-003 推导 `E_VERIFY_FAILED` / `E_VERIFY_INCOMPLETE`，不把执行、变化或已保存改成未执行；其他维度未知时仍优先报告 `E_OUTCOME_UNKNOWN`。已存在的失败/不完整检查不会被该 profile 提升为通过。结构观察按 `_untrusted` 标记为数据。

独立验证所需的应用版本、源码/包身份、实际命令、规则配置和输入证据继续使用现有 [evidence Schema](../schemas/evidence.schema.json) 并由 `evidence_ref` 引用。历史记录只能证明它绑定的提交、应用版本、运行和范围；不能据此提高当前环境的覆盖或成熟度。

## 示例与边界

[示例索引](../examples/index.json) 含 file/session/device 的格式示例以及不得接受的伪通过回执。三种模式的 JSON 是说明格式的假设数据，不是实际应用/设备证据。`tests/test_verification_results.py` 通过实际 CLI 子进程写入临时数字文件，并由另一个进程重新解析它；覆盖忽略输入、自动调整、截图替代、缺读回、输入回显、同源缺陷、检查未完成/超时、旧快照及 finding 等量替换等情况。

Schema 和 SDK 只检查数据之间的一致性及可见的缺口，无法证明声明的 observed 来自真实应用，无法认证证据或保证未声明的共同缺陷不存在。JSON 字段齐全不等于真实状态、独立判定或完整领域验收已经成立。具体适配器仍按 [能力验收](ENGINEERING-ACCEPTANCE.md)取得对应环境的真实证据。
