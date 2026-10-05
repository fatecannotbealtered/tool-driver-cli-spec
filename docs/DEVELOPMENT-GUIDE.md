# 从注册表建立驱动工具

规范版本：`1.0.0`；基线：ai-native-cli-spec `v1.6.3`。

本文供 CLI 和适配器作者使用，假设读者了解 Python、JSON 和目标应用的基本操作。开发支持包括产品注册表、生成器、Python SDK 和种子工程；它们是本规范的参考实现，不要求每个驱动 CLI 都用 Python。

## 分工

| 部件 | 负责 |
|---|---|
| 产品注册表（`registry.json`） | 命令、参数、效果、阶段、输出结构、示例、兼容环境、成熟度和产品错误码；唯一来源 |
| 生成器（`scripts/generate_product.py`） | 补上内置命令，产出运行时契约、reference、contract-ext 和 Skill 能力摘要，检查派生文件漂移 |
| SDK（`packages/tool_driver_sdk`） | 基线全局参数、参数解析、`--dry-run`/`--confirm` 闸门、确认令牌、范围解析、操作记录、内置命令、信封与错误详情 |
| 适配器（产品代码） | 目标与快照、计划、原生调用、读回、回执、原生诊断 |
| 种子工程（`starter/`） | 可直接运行的工程：规范与基线副本、AGENTS.md、CLI 入口、未实现的适配器、测试、CI、CHANGELOG、Skill |

注册表和声明都是数据：生成和发现不执行示例，不根据注册表内容导入代码。适配器必须显式接入；SDK 不会把未知改写成未修改，也不替应用承诺保存、恢复、幂等或授权。

## 注册表与生成

注册表符合 `schemas/product-registry.schema.json`。每条命令就是 reference 里的一条命令：基线字段加 `driver` 块；不要声明内置命令（`reference`、`context`、`doctor`、`changelog`、`operation …`），生成器会补上。
`changelog` 指向产品的 CHANGELOG.md（Keep a Changelog 格式），生成器把已发布的版本段嵌进契约，最新版本必须等于 `product_version`。

```powershell
python scripts/generate_product.py --registry examples/development/product-registry.json --output dist/product-generated
python scripts/generate_product.py --registry examples/development/product-registry.json --output dist/product-generated --check
```

第一条生成输出目录，第二条只核对；注册表变化后用 `--update` 更新。生成器只替换它的所有权清单登记过、且未被手改的文件，遇到其他同名内容会停止。
输出包括 `product_contract.json`（SDK 加载）、`reference.json`（审阅与差异比较）、`contract-ext.json`（驱动与产品扩展码，基线 contract-ext 格式）和 `skill-capabilities.md`。生成器在写出之前用公共 Schema 和 `check_spec` 的规则检查 reference，错误会逐条列出。

## 产品版本与 Agent eval

生成项目以 `registry.json.product_version` 为版本来源。修改后执行 `python sync_version.py` 同步 pyproject、Skill 版本和最小版本，再更新 CHANGELOG、重新生成契约；`check_project.py` 对这些元数据及生成 reference 的版本漂移失败关闭。

产品 Skill 的真实任务运行按 VER-026 记录到 `evidence/agent-eval.json`。`python .agent/driver/scripts/check_agent_eval.py --root . --registry registry.json --report evidence/agent-eval.json` 在 stable/beta 声明下要求真实评测记录；开发模板保持 unpublishable 时明确报告 not_recorded，不把缺记录当已评测。该入口仅读取已保存记录，不调用模型、不执行轨迹里的命令。

## SDK 的调用流程

`tool_driver_sdk.serve(contract, adapter, vendor_root=…)` 处理一次调用；在测试或长期运行的进程里用 `with DriverCLI(…) as cli:`，退出时关闭记录库。

1. 先认命令路径，再按命令声明的参数解析其余部分（基线全局参数为 `--format`、`--compact`、`--fields`、`--quiet`、`--dry-run`、`--confirm`、`--dangerous`、`--request-id`、`--version`、`--help`）。声明过的参数总是取下一个值；以 `--` 开头的值要写成 `--name=<value>`。复数参数只对 string、integer、number 按逗号拆分，路径和 JSON 不拆。错误返回 `E_USAGE` 或 `E_VALIDATION`，带 `problem`、`parameter`、`expected` 和 `next_action`，不复述输入值。
2. 内置命令由 SDK 完成；`context` 和 `doctor` 调用适配器的可选钩子 `environment()`、`credentials()`、`doctor_checks()`。钩子出错或返回不合规的数据时，context 和 doctor 照常返回，并把该组件标为不可用、`native_backend` 标为 fail。
3. 只有 `observe` 效果的读命令：调用 `adapter.run(call)`，按声明补 `_untrusted`，按 `query_page` 或产品 JSON Schema 校验结果，再按 `--fields` 投影。
4. 除 observe 外有效果的命令（包括打开文档、导出文件）都是写命令：
   - 没有 `--dry-run` 或 `--confirm` 时返回 `E_CONFIRMATION_REQUIRED`；危险命令缺 `--dangerous` 同样如此；
   - 读取范围文件并核对效果、根目录、输出目录、交付位置和次数限制（`E_FORBIDDEN`）；
   - `--dry-run`：分配 `operation_id` 与 `plan_id`，调用 `adapter.plan(call)`，组装并校验计划；有交付效果的计划必须在 `outputs` 里写出交付位置；同一目标上有未登记或仍在运行的操作时拒绝；记录计划，签发令牌；
   - `--confirm`：验证令牌、参数摘要、计划和范围；适配器实现了 `revision(target)` 时先查漂移；然后在一个事务里核对同一目标上没有其他活动操作、幂等键、范围的次数限制，消费令牌并记为已派发，同时写入执行租约；之后调用 `adapter.apply(call, plan)`，执行期间后台线程续租；
   - 补全并校验回执，按回执推导 `ok` 和错误码，写回操作记录。适配器明确报告 `not_started` 时，计划回到待确认，同一令牌在过期前仍可再用；派发之后的其他异常（包括中断）都报 `E_OUTCOME_UNKNOWN`，并且不采用适配器给的查询命令和下一步。
5. 长任务命令（`profiles` 含 `operation_status`，适配器同时实现 `submit` 和 `status`）在 confirm 时调用 `adapter.submit(call, plan)`，只接受 `pending` 或 `running`；之后 `operation show` 通过 `adapter.status(record)` 刷新，钩子失败或结果不合规时显示本地记录并在 stderr 警告。
6. 批量命令（`profiles` 含 `batch`）：`adapter.plan(call)` 返回 `items`，每项有 `key`、`target`、`base_snapshot`、`changes`、`outputs`、`can_apply`；SDK 给每项分配 `operation_id`，一个令牌覆盖整批。confirm 时逐项调用 `adapter.apply(call, item_plan)`（`call.item_key` 为该项），结果按基线批量结构返回；`--continue-on-error=false` 时在第一项失败后停止，其余项报告为跳过。批量命令不接受幂等键。
7. 基线的 `update` 自更新调用 `adapter.update(call)`，不经过确认门和任务范围；`update --dry-run` 以 `call.dry_run` 传给适配器。
8. 输出前用固定的规范副本校验信封；不符合时，派发前报 `E_UNKNOWN`，派发后报 `E_OUTCOME_UNKNOWN` 并把记录改为 unknown。

## 适配器约定

```python
from tool_driver_sdk import DriverError

class Adapter:
    def run(self, call): ...            # 只读命令，返回 data
    def plan(self, call): ...           # 返回 target、base_snapshot、changes、outputs、unknowns、constraints、level；批量返回 items
    def apply(self, call, plan): ...    # 派发、读回，返回回执字段（outcome 五个维度、snapshot_after、changed_items 等）
    def revision(self, target): ...     # 可选：当前修订，用于派发前的漂移检查
    def environment(self): ...          # 可选：组件身份与连接状态
    def doctor_checks(self): ...        # 可选：至少包含 native_backend
    def submit(self, call, plan): ...   # 可选：长任务，返回 {"status": "pending" | "running", ...}
    def status(self, record): ...       # 与 submit 一起：返回当前状态，结束时带回执字段
    def update(self, call): ...         # 可选：基线 §14 自更新
```

- `plan` 不得改变目标；需要试执行时只写隔离区，并在 `outputs` 中列出。交付必须在 `outputs` 中写出目的地（`effect: deliver`）。
- `apply` 报告观测到的结果：没有读回就不报 `passed`，没有核实就不报 `saved` 或 `delivered`；只交付已有文件时，`artifacts` 列出的是交付的文件，不算本次生成的产物。
- 失败时抛 `DriverError(code, message, details=…, receipt=…, dispatch_state=…)`；`dispatch_state` 如实说明是否已派发，只有确实什么都没发出去时才写 `not_started`。在 `apply` 或 `submit` 里抛出而没写 `dispatch_state` 的错误，SDK 按结果未知处理，令牌不会重新生效。
- 来自目标或应用的文字放在 `_untrusted` 列出的字段里。

## 状态与范围

- 范围文件：`<TOOL>_SCOPE_FILE` 或 `~/.<tool>/scope.json`；CLI 只读，不提供授权命令。没有文件时只读。根目录和输出目录必须是绝对路径；时间必须带 `Z`；重复 JSON 字段无效。交付位置和 `locator_prefix` 不得带用户信息、查询或 `.`、`..` 段，也不能用编码后的分隔符改变路径层次；否则整个范围按无效处理。交付位置按 URL 的完整路径段比较（DRV-009）。
- 次数限制：`limits.max_operations` 按范围 ID 累计在记录库里，不随记录过期而清零；没有真正派发的批量项会退回额度。
- 状态目录：`<TOOL>_STATE_DIR` 或 `~/.<tool>/`，保存确认令牌的密钥和 SQLite 操作记录。目录或文件是链接时拒绝使用；记录库不可用时拒绝派发（`E_IO`，LAY-007）；密钥损坏时自动换新，未用的令牌随之失效。
- 写入按目标串行：目标身份由模式、引擎、实例和规范化后的定位符组成，`file://` 定位符按真实路径比较。
- 未登记的 unknown 操作阻止同一目标上的写入（`unresolved_operation`），直到 `operation resolve` 登记读回结果；仍在运行的操作同样阻止（`lock_held`），租约过期前不能登记。同步执行的租约默认 30 秒，由执行中的 CLI 续租（`DriverCLI(lease_seconds=…)`）；已提交的长任务默认 600 秒，每次 `status()` 观测到它仍在进行时续期（`status_lease_seconds=…`）。
- 登记之后才到的结果不覆盖登记，保存在记录里，`operation show` 在 `extensions.late_result` 中给出；派发后不合契约的回执在 `extensions.rejected_receipt` 中给出。
- 适配器回执必须匹配记录的操作、能力、计划、范围及目标身份。长任务结束或已停止而没有效果读回时，结果仍为 unknown，同一目标保持待核实状态，不能仅凭 failed/cancelled 解除写入阻塞。

## 种子工程

```powershell
python scripts/instantiate_starter.py --name sample-driver --profile file --output D:/work/sample-driver
```

输出目录必须不存在。种子工程包含：`AGENTS.md` 与 `.agent/AGENT.md`（Agent 的工作流）、`.agent/driver/`（本规范的正文、Schema、驱动契约、基线副本和校验脚本）、`.agent/vendor/sdk/`（SDK）、`.agent/driver/starter-lock.json`（副本来源与哈希）、`registry.json`、`<package>/`（入口与未实现的适配器）、生成的契约、`tests/test_contract.py`（命令级测试与 FCC 守卫）、`.github/workflows/ci.yml`、`CHANGELOG.md`、`pyproject.toml`、`skills/<name>/SKILL.md` 与 `test-prompts.json`。
实例化之后会在临时状态目录里自检 `reference`、`context`、`doctor`；生成的工程自己的测试也能直接运行：

```powershell
cd D:/work/sample-driver
python -m pip install -r requirements.txt
python check_project.py
python -m unittest discover -s tests -v
```

未实现的命令返回 `E_UNSUPPORTED`。初始化成功、协议测试通过都不能代表原生能力已验收；成熟度只在取得真实证据后提高。

## 测试与进程

- 命令级测试运行真实的 CLI 边界；在 Windows 上启动子进程时传 `CREATE_NO_WINDOW`，避免弹出控制台窗口。
- 临时目录在测试里先 `.resolve()`，避免 macOS 的 `/var` 链接和 Windows 短路径造成的路径比较失败。
- 不要拿墙上时钟作超时测试的触发条件；用可注入的时钟（`DriverCLI(now=…)`）。

## 来源

种子工程和消费项目的副本都按哈希核对；只凭版本字符串不能认定内容相同。实例化与生成过程不联网、不发布、不启动原应用，也不注册插件。
