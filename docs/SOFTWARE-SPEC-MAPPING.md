# 与软件 spec 的逐项对照

规范工作版本：`1.0.0`；驱动结构：`2.0`。本次对照 ai-native-cli-spec 远端 main 与本地一致的提交 `d6733433e2a9b93a4e6fb169c6927f6604ec89c7`（`v1.6.3`），不以 README 里的旧示例 pin `v1.5.0` 为当前契约。`base/base-lock.json` 固定的也是这个提交，基线副本不修改。

## 对照与落实

| 软件 spec 的实际要求与位置 | tools spec 的落实及可执行证据 | 结论 |
|---|---|---|
| [AGENT §工作流 A/B、自检](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/AGENT_zh.md#L29)、[INSTANTIATE](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/INSTANTIATE.md#L61)：先定契约、common + 一种语言、开发入口、生成与测试 | `AGENTS.md`、种子 `.agent/AGENT.md` 分别给规范作者和产品作者导航；`instantiate_starter.py` 复制固定副本、SDK、CI、测试、Skill，并实际自检。`tests/test_starter.py` 运行生成项目及其测试 | 已实现；模板原生命令仍拒绝，不能将模板初始化当工程任务完成 |
| [CLI §3.1](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/CLI-SPEC_zh.md#L86)、[REPO §5c](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/REPO-SPEC_zh.md#L183)：单源、固定副本、生成物零漂移、真实运行时对齐 | `base/base-lock.json`、`contract/driver-contract.json`、公共 Schema；注册表生成 reference/contract-ext/运行契约，`--check` 检查派生物；`check_project.py` 校验固定副本；静态检查重复表格、正反例和文档链接；实际 CLI 测试校验输出 | 已实现。离线哈希检查不证明发布者身份，也不证明实际加载的原生服务版本 |
| [CLI §7/9/11](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/CLI-SPEC_zh.md#L167)：HMAC 确认、幂等、自描述、环境与更新真相 | SDK 统一参数、令牌、授权、状态库、计划/回执、operation 查询；产品适配器负责底层事实。`test_sdk.py`、`test_review_regressions.py` 覆盖重放、漂移、失回复、租约和错误回执 | 已实现公共层。自动更新、凭证、异步、设备只在声明支持时验证，不能由 SDK 代替应用承诺 |
| [CLI §13](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/CLI-SPEC_zh.md#L519)、[REPO §6](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/REPO-SPEC_zh.md#L193)：所有公开行为的 FCC，成功/失败/参数/输出/退出码，stable 对应本次候选真实 smoke | VER-001/022/025；种子实际子进程调用与运行时命令集守卫，默认 `unpublishable/fcc missing`。规范的 `check_graduation.py` 留存静态、回归、真实消费及源文件哈希；候选 ZIP 已在隔离 checkout 消费 | 已有机制与真实运行。命令集守卫只证明叶子被调用，不能单独证明所有参数与失败行为覆盖；具体产品仍须逐行为证据 |
| [SKILL §1/6](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/SKILL-SPEC_zh.md#L13)：使用者通过 Skill 意图配方与实时 reference 使用工具 | README、种子 Skill 和 `reference --index/--command` 分工；修正种子 Skill 残留的未验证 npx 安装配方，与 Release + SkillHub 约束一致 | 入口已对齐；原生包安装与 SkillHub 路径仍由各产品实测，模板不宣称已有发布 |
| [SKILL §9](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/SKILL-SPEC_zh.md#L184)：先跑无 Skill 代表任务、至少三场景、多模型、A/B 实例迭代与实际导航 | SKL-010、VER-026 已要求实测；此次补 `agent-eval` Schema、离线 `check_agent_eval.py`、种子 CI 的记录门禁。绑定源文件、Skill、场景、模型版本、实际 argv/退出码/stdout/stderr、轨迹和结果证据；发布声明要求多模型全场景及无 Skill 基线；fixture 不能满足门禁 | 记录/门禁机制已补。真实 Agent、多模型、A/B 导航观察尚未执行；CLI 回归和模拟记录不能替代 |
| [SEC §5](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/SEC-SPEC_zh.md#L89)：每个分发生态在合并和发布路径审计；校验材料由标签工作流 keyless 签名 | 查 Requires-Dist 后补齐 Python <3.13 的 typing-extensions pin，与原五项一起固定；`check_graduation --audit` 使用现有 pip-audit、禁用 pip 解析/安装/修复，保留 JSON。两条工作流均启用；Release 工作流补 Sigstore bundle 签名与精确 workflow/tag 身份校验，审计失败不能签名或发布 | 原五项在线审计通过；完整六项在最终验收重跑。工作流签名尚未运行；CLI 自更新的进程内签名验证属于产品要求，规范哈希验证器不冒充它 |
| [REPO §4/5c](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/REPO-SPEC_zh.md#L79)、[version-files.js](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/scripts/version-files.js#L142)：版本单源、CHANGELOG、不可变源码和生成物同步 | 规范 VERSION、契约、文档和正反例互相核对；种子新增 `sync_version.py` 从 registry 同步 pyproject/Skill/min_version，`check_project.py` 拒绝这三处及生成 reference 的版本漂移；候选标 dirty，正式 Release manifest 拒绝 dirty | 补上产品版本守卫与写入器；正式冻结、签名和发布仍未执行，已有 Release 1.0.0 不替换 |

## 有意调整与按条件适用

- 规范仓库是文本、契约和参考实现的包，不是原生 CLI 产品：没有客户端升级、登录凭证、应用安装和设备动作，不要求为它构造伪造的产品能力。真正的产品仍按这些基线条款验收。
- LAY-007 明确收紧令牌存储失败降级：操作账本不可写时拒绝派发，保留工程写入失回复后的可查询性；这是已经记录的偏离。
- LAY-008 按既定交付选择 GitHub Release + SkillHub，替代 npm 壳；当前分发没有 npm 生态，不添加无关的 npm audit。采用其他语言、运行时或分发组件的产品仍审计其全部适用生态。
- common + 语言叠加思路保留，但目前只提供 Python 参考 SDK，不把多语言实现列为规范毕业门槛。Python 版本与平台范围如实声明，不复制软件模板的所有构建矩阵。
- 本仓库 AGENTS 明确规范正文用中文；不机械复制全部双语、徽章和开源社区模板。具体 CLI 产品的 LICENSE/CONTRIBUTING/SECURITY/第三方 NOTICE/兼容矩阵仍按基线 REPO-SPEC 适用性补齐；种子当前只保证直接运行的开发起点，不声称公开产品仓库准备完成。
- 当前工作版本按用户要求保留 1.0.0，机器结构独立标识 2.0；正式发布不同内容需要新标签/版本与显式结构迁移，不修改原 Release。

## 真实缺口与取证边界

没有真实 Agent eval 的产品不能凭场景文件或记录格式通过发布评测。记录校验也不认证录制者、不证明模型真的产生轨迹；需要保留实际执行来源，并由独立检查或审查复核工程结果。未支持的环境与命令可以限制成熟度，无需伪造通过结果。

后续收紧完整场景门禁：八类强制场景逐项保留适用性与来源，完整门禁不能只按数量放行；真实 SVG 子集有单独结果，不能满足完整 Skill 或发布门禁。新增冻结输入、实际 argv/原始 stdout/stderr 录制和独立 Chrome 判定工具；输入计划本身不生成真实模型评测证据，父控制者仍需实际执行独立任务并保留平台身份与公开事件。

实际应用加载身份、独立制造/CAD 消费、SkillHub 原生安装/升级和真实多模型评测仍是产品验收项。当前新增的 Sigstore 发布步骤需要在获授权的新标签工作流中真实执行；本次仅核对其 CLI 参数和 YAML，不声称已有签名。

运行检查依赖依据 Requires-Dist 核对 closure：Python 3.11/3.12 为六包（包含条件依赖 typing-extensions），Python >=3.13 不需要该项；最终审计查询公开漏洞库。这不是全系统审计，也不证明未来无漏洞。可选审计/签名工具在 `requirements-workflow.txt` 固定直接版本，其传递依赖没有逐 wheel 哈希锁；不可声称整个 CI 工具链逐字节可复现。规范 ZIP 则由固定源码字节确定性构建，候选 ZIP 由逐文件哈希绑定，两者分别取证。
