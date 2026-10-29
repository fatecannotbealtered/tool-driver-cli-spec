# 与软件 spec 的逐项对照

规范版本：`1.0.2`；驱动结构：`2.0`。本次对照 ai-native-cli-spec 远端 main 与本地一致的提交 `d6733433e2a9b93a4e6fb169c6927f6604ec89c7`（`v1.6.3`），不以 README 里的旧示例 pin `v1.5.0` 为当前契约。`base/base-lock.json` 固定的也是这个提交，基线副本不修改。

下表记录 1.0.2 的历史对照，并非当前软件规范 main 的版本声明。后续提案在 LAY-009 明确替换旧 FCC 和完整多模型评测作为产品平台发布通用前提；旧字段仍按固定基线如实报告，平台包支持按 DEL-019、VER-022 单独取证。软件规范 main 已有 2.0 系列的逐命令成熟度和运行覆盖，不能回退成 1.6.3 的旧源码扫描。

## 对照与落实

| 软件 spec 的实际要求与位置 | tools spec 的落实及可执行证据 | 结论 |
|---|---|---|
| [AGENT §工作流 A/B、自检](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/AGENT_zh.md#L29)、[INSTANTIATE](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/INSTANTIATE.md#L61)：先定契约、common + 一种语言、开发入口、生成与测试 | `AGENTS.md`、种子 `.agent/AGENT.md` 分别给规范作者和产品作者导航；`instantiate_starter.py` 复制固定副本、SDK、CI、测试、Skill，并实际自检。`tests/test_starter.py` 运行生成项目及其测试 | 已实现；模板原生命令仍拒绝，不能将模板初始化当工程任务完成 |
| [CLI §3.1](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/CLI-SPEC_zh.md#L86)、[REPO §5c](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/REPO-SPEC_zh.md#L183)：单源、固定副本、生成物零漂移、真实运行时对齐 | `base/base-lock.json`、`contract/driver-contract.json`、公共 Schema；注册表生成 reference/contract-ext/运行契约，`--check` 检查派生物；`check_project.py` 校验固定副本；静态检查重复表格、正反例和文档链接；实际 CLI 测试校验输出 | 已实现。离线哈希检查不证明发布者身份，也不证明实际加载的原生服务版本 |
| [CLI §7/9/11](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/CLI-SPEC_zh.md#L167)：HMAC 确认、幂等、自描述、环境与更新真相 | SDK 统一参数、令牌、授权、状态库、计划/回执、operation 查询；产品适配器负责底层事实。`test_sdk.py`、`test_review_regressions.py` 覆盖重放、漂移、失回复、租约和错误回执 | 已实现公共层。自动更新、凭证、异步、设备只在声明支持时验证，不能由 SDK 代替应用承诺 |
| [CLI §13](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/CLI-SPEC_zh.md#L519)、[REPO §6](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/REPO-SPEC_zh.md#L193)：所有公开行为的 FCC，成功/失败/参数/输出/退出码，stable 对应本次候选真实 smoke | VER-001/022/025；种子实际子进程调用与运行时命令集守卫，默认 `unpublishable/fcc missing`。规范的 `check_graduation.py` 留存静态、回归、真实消费及源文件哈希；候选 ZIP 已在隔离 checkout 消费 | 已有机制与真实运行。命令集守卫只证明叶子被调用，不能单独证明所有参数与失败行为覆盖；具体产品仍须逐行为证据 |
| [SKILL §1/6](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/SKILL-SPEC_zh.md#L13)：使用者通过 Skill 意图配方与实时 reference 使用工具 | README、种子 Skill 和 `reference --index/--command` 分工；修正种子 Skill 残留的未验证 npx 安装配方，与 Release + SkillHub 约束一致 | 入口已对齐；原生包安装与 SkillHub 路径仍由各产品实测，模板不宣称已有发布 |
| [SKILL §9](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/SKILL-SPEC_zh.md#L184)：先跑无 Skill 代表任务、至少三场景、多模型、A/B 实例迭代与实际导航 | SKL-010、VER-026 已要求实测；此次补 `agent-eval` Schema、离线 `check_agent_eval.py`、种子 CI 的记录门禁。绑定源文件、Skill、场景、模型版本、实际 argv/退出码/stdout/stderr、轨迹和结果证据；发布声明要求多模型全场景及无 Skill 基线；fixture 不能满足门禁 | 记录/门禁机制已补。真实 Agent、多模型、A/B 导航观察尚未执行；CLI 回归和模拟记录不能替代 |
| [SEC §5](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/.agent/SEC-SPEC_zh.md#L89)：每个分发生态在合并和发布路径审计；校验材料由标签工作流 keyless 签名 | 查 Requires-Dist 后补齐 Python <3.13 的 typing-extensions pin，与原五项一起固定；`check_graduation --audit` 使用现有 pip-audit、禁用 pip 解析/安装/修复，保留 JSON。两条工作流均启用；Release 工作流补 Sigstore bundle 签名与精确 workflow/tag 身份校验，审计失败不能签名或发布 | 完整六项在对应提交的验收中重跑，实际审计与签名结果以本版本工作流、签名包和 Release 资产为准；CLI 自更新的进程内签名验证属于产品要求，规范哈希验证器不冒充它 |
| [REPO §4/5c](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/REPO-SPEC_zh.md#L79)、[version-files.js](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/d6733433e2a9b93a4e6fb169c6927f6604ec89c7/template/common/scripts/version-files.js#L142)：版本单源、CHANGELOG、不可变源码和生成物同步 | 规范 VERSION、契约、文档和正反例互相核对；种子新增 `sync_version.py` 从 registry 同步 pyproject/Skill/min_version，`check_project.py` 拒绝这三处及生成 reference 的版本漂移；候选标 dirty，正式 Release manifest 拒绝 dirty | 产品版本守卫与写入器已实现；规范 1.0.1 通过独立标签的发布工作流构建、验收和签名，实际完成情况按该版本发布材料取证，已有 Release 1.0.0 保持原样 |

## 有意调整与按条件适用

- 规范仓库是文本、契约和参考实现的包，不是原生 CLI 产品：没有客户端升级、登录凭证、应用安装和设备动作，不要求为它构造伪造的产品能力。真正的产品仍按这些基线条款验收。
- LAY-007 明确收紧令牌存储失败降级：操作账本不可写时拒绝派发，保留工程写入失回复后的可查询性；这是已经记录的偏离。
- LAY-008 按既定交付选择 GitHub Release + SkillHub，替代 npm 壳；当前分发没有 npm 生态，不添加无关的 npm audit。采用其他语言、运行时或分发组件的产品仍审计其全部适用生态。
- common + 语言叠加思路保留，但目前只提供 Python 参考 SDK，不把多语言实现列为规范毕业门槛。Python 版本与平台范围如实声明，不复制软件模板的所有构建矩阵。
- 本仓库 AGENTS 明确规范正文用中文；不机械复制全部双语、徽章和开源社区模板。具体 CLI 产品的 LICENSE/CONTRIBUTING/SECURITY/第三方 NOTICE/兼容矩阵仍按基线 REPO-SPEC 适用性补齐；种子当前只保证直接运行的开发起点，不声称公开产品仓库准备完成。
- 本次按用户选定的规范版本 1.0.2 发布，沿用 1.0.1 的公共结构与信封，机器结构独立标识 2.0，与旧规范 1.0.0 的结构 1.0 不兼容；使用新标签 `v1.0.2` 并按实施指南迁移，原 Release 保持原样。实际签名、发布和资产身份以对应版本的工作流与发布材料为准。

## 真实缺口与取证边界

没有真实 Agent eval 的产品不能凭场景文件或记录格式通过发布评测。记录校验也不认证录制者、不证明模型真的产生轨迹；需要保留实际执行来源，并由独立检查或审查复核工程结果。未支持的环境与命令可以限制成熟度，无需伪造通过结果。

完整评测声明仍需逐项保留八类场景的适用性与来源；真实 SVG 子集不能冒充完整 Skill 评测。完整评测不再是通用平台包发布门禁。输入计划本身不生成真实模型评测证据，实际运行必须留存平台身份与事件。

实际应用加载身份、独立制造/CAD 消费、SkillHub 原生安装/升级和真实多模型评测按声明范围分别取证；工程最终签核不由平台包支持推定。Sigstore 发布步骤需要在获授权的新标签工作流中真实执行；仅核对 CLI 参数和 YAML 不等于已有签名。

运行检查依赖依据 Requires-Dist 核对 closure：Python 3.11/3.12 为六包（包含条件依赖 typing-extensions），Python >=3.13 不需要该项；最终审计查询公开漏洞库。这不是全系统审计，也不证明未来无漏洞。可选审计/签名工具在 `requirements-workflow.txt` 固定直接版本，其传递依赖没有逐 wheel 哈希锁；不可声称整个 CI 工具链逐字节可复现。规范 ZIP 则由固定源码字节确定性构建，候选 ZIP 由逐文件哈希绑定，两者分别取证。
