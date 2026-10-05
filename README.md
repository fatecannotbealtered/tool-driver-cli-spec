# tool-driver-cli-spec

ai-native-cli-spec 的驱动扩展层：让 Agent 驱动真实应用、应用文件和设备时，状态说得清、授权管得住、失败能收敛。

规范版本：`1.0.2`；状态：`stable`；驱动结构版本：`2.0`；基线：ai-native-cli-spec `v1.6.3`。

本规范供驱动 CLI 的实现者、适配器作者和验收人员使用。读者应了解命令行、JSON，以及所驱动工具的基本操作。

## 定位

驱动 CLI 首先是一个 AI 原生 CLI：信封、错误码与退出码、`reference`/`context`/`doctor`/`changelog`、`--dry-run` → `--confirm`、`_untrusted`、风险分级、Skill 规范、分发与自更新，全部沿用 [ai-native-cli-spec](base/ai-native-cli-spec/AGENT_zh.md)，原文按固定标签保存在 `base/`。
本规范只补驱动场景特有的部分：

- 目标身份：实例、会话、文档、文件、设备，连接代际与所有权；
- 五个维度的回执：执行、变化、保存、交付、验证分别报告，`ok` 和错误码由回执推导；
- 任务范围授权：由人写的范围文件，范围内连续迭代，越界在派发前停下；
- 预先知道的操作身份、操作记录与 `operation show/list/resolve`，回复丢失后能查询、读回、登记；
- 长任务、依赖工作流、模态框与许可窗口、单位与坐标、设备动作；
- 真实操作、产物读回与独立判定的验证要求。

和基线的逐项关系见[基线与驱动层](docs/LAYERING.md)。

规范按 `file`、`session`、`device` 模式和命令声明的效果组织，不以行业、品牌或文件格式划定支持范围。公共要求是目标与依赖身份、授权、计划、执行、保存/交付、验证及恢复；内存状态、单位/坐标、呈现和物理效果等附加要求按实际能力适用。没有某种状态可以说明不适用；声明支持但尚未观测或验证的状态不能借此豁免。
正文编号条款中的「必须」「不得」是规范性要求；标为参考实现、建议任务或案例附录的内容用于说明和取证，不新增特定产品的支持义务。领域规则在公共契约之外补充，并说明检查范围。

## 阅读入口

| 文档 | 用途 |
|---|---|
| [基线与驱动层](docs/LAYERING.md) | 继承什么、收紧什么、新增什么；驱动扩展错误码 |
| [核心协议](docs/CORE-SPEC.md) | 信封中驱动对象的位置、回执推导、错误详情、发现、计划与操作身份 |
| [应用与设备操作](docs/DRIVER-SPEC.md) | 目标身份、任务范围、阶段、漂移、批量与工作流、长任务、设备 |
| [验证](docs/VERIFICATION-SPEC.md) | 契约、真实操作、产物、Skill 评测和发布验收 |
| [结构化验证结果](docs/VERIFICATION-RESULTS.md) | 可选 expected/observed profile、来源与快照绑定，以及 SDK 结果推导的边界 |
| [交付](docs/DELIVERY-SPEC.md) | Release、渠道、安装与升级、Skill 配套、版本与规范包 |
| [驱动 Skill 增补](docs/SKILL-ADDENDUM.md) | 驱动 Skill 在基线 SKILL-SPEC 之上必须写的内容 |
| [实施与迁移](docs/ADOPTION-GUIDE.md) | 新建工具、从基线驱动 CLI 和 1.0 迁移、试点 |
| [工具工程](docs/DEVELOPMENT-GUIDE.md) | 产品注册表、生成器、Python SDK 与种子工程 |
| [命令树设计](docs/COMMAND-DESIGN.md) | 应用能力调查、任务映射、范围分母与可执行开发设计契约 |
| [能力验收与规范毕业](docs/ENGINEERING-ACCEPTANCE.md) | 按模式和能力选择任务，区分规范准入与具体工具验收 |
| [驱动契约](contract/driver-contract.json) | 扩展错误码、回执推导规则、错误详情、效果与范围的机器形式 |
| [机器结构](schemas/) | 计划、回执、操作状态、工作流、批量、列表、reference、context、doctor、scope 等 Schema |
| [示例索引](examples/index.json) | 应通过与应拒绝的正反例 |

## 软件规范对照

已按 ai-native-cli-spec 当前固定提交逐项核对开发入口、机器契约、FCC、真实 Agent eval、版本同步、审计与签名；实现、适用性调整与待验项见 [软件规范对照](docs/SOFTWARE-SPEC-MAPPING.md)。CLI 子进程回归与真实多模型 Agent eval 分别取证。

## 直接使用与毕业入口

从 [种子工程](starter/README.md) 按模式实例化新工具，或先运行 [SVG 文件模式参考实现](examples/engineering/README.md)。规范与具体能力的验收边界、品牌无关的任务选择，见 [能力验收与规范毕业](docs/ENGINEERING-ACCEPTANCE.md)；既有工程工具材料另列在[非规范性案例附录](docs/ENGINEERING-CASE-STUDIES.md)。
三个模式都有开发脚手架和协议支持；仓库的真实产物参考试验使用 SVG。它不要求采用方支持 SVG，也不能证明任意文件格式、会话应用或设备已经可用。原生适配器尚未实现时明确拒绝，模板自检不能代替真实任务完成。

```powershell
python scripts/instantiate_starter.py --name sample-driver --profile file --output D:/work/sample-driver
python examples/engineering/svg_title_driver.py reference --index
python scripts/check_graduation.py --browser "C:/Program Files/Google/Chrome/Application/chrome.exe" --output D:/work/spec-acceptance-new
```

版本 1.0.2 沿用 1.0.1 的驱动结构 2.0 和运行时信封，无需再次迁移公共协议，与已有 Release 1.0.0 的结构 1.0 不兼容；迁移见[实施与迁移指南](docs/ADOPTION-GUIDE.md#从已发布的驱动结构-10-迁移)。采用方必须同时固定规范版本、结构、来源与哈希。发布使用新标签 `v1.0.2`，旧标签和资产保持原样。

## 实施顺序

1. 调查实际应用的能力、接口、版本、许可和证据，从用户任务设计命令树、范围分母与读回判据，固定基线标签与驱动规范版本。
2. 先满足基线：信封、错误码、自描述命令、`--dry-run`/`--confirm`、`_untrusted`。
3. 加上驱动层：reference 的 driver 块、范围文件、操作记录、回执与读回。
4. 按命令补齐命令级测试、真实读回和产物验收，记录失败路径与未覆盖项。
5. 从版本化的包验证安装、升级和实际组件身份，再按成熟度交付。

简单的文件工具只实现适用的部分；长期会话、设备动作和工作流的附加条件按命令声明验收。

## 设计原则

- 先符合基线，再谈驱动；不重定义基线已有的字段、错误码和命令。
- 授权按任务范围表达，由人授予；范围内的连续迭代不要求每一步重新人工确认，确认令牌只是 Agent 自己完成的计划绑定。
- 执行、变化、保存、交付和验证分别报告；调用成功不能代替领域正确。
- 结果未知时先查询、读回、登记，绝不盲目重发。
- 查询、修改和产物都绑定明确的实例、对象、版本和必要依赖。

## 发布与分发

驱动 CLI 产品在 GitHub Release 形成版本化产物，通过 SkillHub 分发；必须有验证过的 Agent 安装和升级路径。SkillHub 原生多文件包支持仍由产品实际验收，不把平台注册当作能力完成。
本仓库的规范包包含文档、基线副本、驱动契约、Schema、示例、校验入口、SDK 与种子工程，只通过 GitHub Release 交付，不作为 CLI 产品登记。

## 本地校验

校验脚本需要 Python 3.11+。依赖只用于规范仓库的校验和 Python SDK，不要求每个 CLI 使用 Python。

```powershell
python -m pip install -r requirements-dev.txt
python scripts/check_spec.py
python -m unittest discover -s tests -v
python scripts/build_spec_bundle.py
```

`check_spec` 检查基线锁定、驱动契约、结构、正反例、条款编号、本地链接，以及正文里重复的表格是否与机器契约一致；单元测试运行实际的命令边界、SDK、生成器、种子工程与交付工具。
构建命令只在工作树干净时，从该提交的文件生成规范 ZIP、manifest 和校验清单，写入 `dist/`，不发布 Release。

## 适用边界

身份映射、领域判定器、来源证明方式和分发平台的原生包支持，需要在声明的环境中继续验证。
具体实现可以增加领域规则，但必须说明适用条件、检查范围和未覆盖项，不得扩大既有授权。
