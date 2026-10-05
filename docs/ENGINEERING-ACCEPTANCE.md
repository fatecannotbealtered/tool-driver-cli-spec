# 工程任务验收与规范毕业

规范版本：`1.0.0`；驱动结构版本：`2.0`；基线：ai-native-cli-spec `v1.6.3`。

目标是让 Agent 在授权范围内完成可独立核实的工程任务。命令数量、JSON 返回成功和静态合同通过，都不能代替工程结果。这里把仓库已有 VER-024、DEL-025 的规范准入整理成可执行入口，并为三个工具提出首批任务；这些任务是适配建议，不表示原生适配已经完成。

## 规范怎样毕业

规范的最小准入沿用 VER-024：正文、基线和机器合同一致；正反例与有意义的边界回归通过；本次交付 ZIP 具备完整必需文件且重新消费成功；至少一种真实文件产物经过独立消费者。SDK 和种子工程必须能实例化、运行自描述与协议测试；未实现原生命令明确拒绝。无需把每个 CAD、PCB 工具、物理设备、GUI 会话和所有未来命令做完。

本地运行（Python、浏览器和可选审计工具已具备时）：

```powershell
python scripts/check_graduation.py --audit --browser "C:/Program Files/Google/Chrome/Application/chrome.exe" --output D:/work/spec-acceptance-new
```

输出 `acceptance.json`、实际 stdout/stderr、依赖审计 JSON 和消费者产物。`--audit` 使用已有 pip-audit，不解析/安装依赖或修复环境；不带该选项仍可执行离线回归与消费，但不能取得 release_ready。它记录当前提交、未提交状态及全部规范/实现/测试文件哈希，区分 `local_passed` 与 `release_ready`；缺少交付包时后者为 false。FIFO、符号链接等平台跳过项保留在测试日志，不能写成已测。

冻结到获授权的干净提交后，用既有构建器生成规范 ZIP；取得独立预期校验值，再执行：

```powershell
python scripts/check_graduation.py --audit --browser "C:/Program Files/Google/Chrome/Application/chrome.exe" --output D:/work/spec-package-acceptance-new --bundle dist/tool-driver-cli-spec-1.0.0.zip --expected-sha256 <trusted-sha256>
```

该入口拒绝覆盖证据目录，重新校验和解包 ZIP，在包目录运行静态检查、全套测试和真实浏览器消费，而非只检查开发目录。`release_ready` 还要求包字节与干净源码逐项一致、提交相同、STATUS 为 stable；它表示本地发布材料具备条件，不证明发布者身份、GitHub 实际资产或 SkillHub 安装。

本次保持规范工作版本 1.0.0。已有 Release 1.0.0 的驱动结构是 1.0，本地扩展结构为 2.0；调用方必须同时固定结构标识、来源和文件哈希，不能只看版本号。已有标签和资产不得替换；正式发布本次不同内容时采用新标签和版本，例如 1.0.1，并明确迁移结构及来源。结构版本独立于规范工作版本，绝不能把两套不同字节当成同一个发布包。

## 工具怎样验收

建议每个工具先冻结一条真正有用的任务，再按能力和环境提高成熟度。每个场景至少留下：目标与依赖指纹、单位/坐标系、保护对象；原样 argv、退出码和响应；计划与范围；五维回执；保存后重新打开或独立检查结果；失败与未知路径，以及没测什么。模拟故障只证明协议恢复，不证明原生服务已经抗故障。

| 工具与建议的首批任务 | 必须核实的工程结果 | 关键失败场景 | 可借鉴的现有材料及边界 |
|---|---|---|---|
| Xpedition：在授权工程副本放置 R1、C1 并连网，保存、关闭、重开，再导出一组制造文件 | 工程和库版本一致；部件、符号、封装与引脚映射正确；网连接正确；重开后的对象与网相同；导出的所有文件及其来源清单齐全且可消费 | 库不存在或占位件；部分放置/部分保存；一次导出只产生部分文件；许可/模态窗口 | [E2E](https://github.com/fatecannotbealtered/xpedition-cli/blob/0d10d933484a567171f512bb03e2c9103d8ade0b/docs/E2E.md)有真实许可环境记录，但自制占位库不能作为生产元件；单个安装版本不能推广到所有版本 |
| KiCad：在工程副本修改一个器件布局，保存并运行上游 kicad-cli DRC，再导出制造文件 | 输入 PCB、项目与自定义规则共同固定；保护网络/器件不变；原生 DRC 的配置、排除项、规则判断范围保留；退出 0 只代表检查运行完；制造文件由独立消费者打开 | 项目配置漂移；DRC 报告失败/不完整；保存后校验失败；把自写分析器当上游 DRC | [DRC 边界](https://github.com/fatecannotbealtered/kicad-cli/blob/3ec1892926e3c29778d3527ead634506d81b8052/docs/DRC_BOUNDARY.md)及[发布准入](https://github.com/fatecannotbealtered/kicad-cli/blob/3ec1892926e3c29778d3527ead634506d81b8052/docs/RELEASE_ADMISSION.md)；新远端修复不能借旧证据升级为已验证 |
| Creo：明确选择运行实例和模型，在指定单位下改一个尺寸，读回几何，再按授权保存并导出 STEP | 客户端、磁盘服务与实际加载服务分别识别；未保存状态保留；尺寸、单位、体积/拓扑变化与保护特征独立断言；重开模型和独立 STEP 消费成功 | OTK 主线程忙；旧服务仍加载；confirm 前人工改模型；已派发后失回复时查记录而不重发；保存失败 | [README](https://github.com/fatecannotbealtered/creo-cli/blob/0e3302cb104084626d5475af1f3989da7cee1357/README.md)与[历史实机记录](https://github.com/fatecannotbealtered/creo-cli/blob/0e3302cb104084626d5475af1f3989da7cee1357/docs/evidence/live-creo.json)；历史实测的源指纹与当前变更不一致时，不能证明当前版本 |

上述引用是本次阅读的本地提交位置，包含未推送提交；它们不是远端当前版本的验收。对应远端 main 在本次检查中为 Xpedition `d6ff2f38c19f4cdc605c2e5ea9597371538f53f7`、KiCad `ec3ef6f0a4a676130fcaf065077d1ea19084880f`、Creo `d57081b41f4ac0ee9fe2a7e802ac81ce082d2f4a`。本规范没有运行这三个原生软件，也没有改动它们的源码。

## 一个已实现的起点

[SVG 标题适配器](../examples/engineering/svg_title_driver.py)是真实文件模式的最小完整实现，配套[注册表](../examples/engineering/registry.json)和[CLI 边界测试](../tests/test_engineering_example.py)。它读取已有 SVG，计划修改标题，在授权范围内确认保存，保护标题以外的所有字节，并持久化可跨进程查询的操作记录；无范围、文件漂移和非法 XML 都有实际拒绝测试。测试还在独立 Python 进程重开文件并核实标题、几何与尺寸单位。

这证明公共流程有可用实现，不证明电子或机械设计正确。真实浏览器实验进一步检验几何、毫米单位、保存重开、失败判定和本地失回复恢复；它也不是原生 CAD 的替代验收。新工具先由种子生成可执行工程，再实现对应原生适配器及以上最小任务，已有工具可逐命令迁移。
