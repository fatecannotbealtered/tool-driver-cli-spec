# 工程工具案例附录（非规范性）

这些案例用于帮助适配器作者选择领域任务，不是支持清单，也不是规范的毕业门槛。表中任务与判定点是建议；具体工具声明能力后，仍须按公共条款及自身领域规则取得真实证据。规范的通用任务与准入见[能力验收与规范毕业](ENGINEERING-ACCEPTANCE.md)。

下面保留原 ENGINEERING-ACCEPTANCE 在提交 `af030e5c1dab1258e5a73fb1b8e7bb1572890b4a` 中的案例表及审查边界。源码引用、旧审查结论和版本身份原样迁移；其中「本次阅读」「本次检查」指当时的审查，不是本轮通用化调整。部分提交未推送，GitHub 链接可能无法访问；本附录没有重新运行原生软件或核实其最新版本。

| 工具与建议的首批任务 | 必须核实的工程结果 | 关键失败场景 | 可借鉴的现有材料及边界 |
|---|---|---|---|
| Xpedition：在授权工程副本放置 R1、C1 并连网，保存、关闭、重开，再导出一组制造文件 | 工程和库版本一致；部件、符号、封装与引脚映射正确；网连接正确；重开后的对象与网相同；导出的所有文件及其来源清单齐全且可消费 | 库不存在或占位件；部分放置/部分保存；一次导出只产生部分文件；许可/模态窗口 | [E2E](https://github.com/fatecannotbealtered/xpedition-cli/blob/0d10d933484a567171f512bb03e2c9103d8ade0b/docs/E2E.md)有真实许可环境记录，但自制占位库不能作为生产元件；单个安装版本不能推广到所有版本 |
| KiCad：在工程副本修改一个器件布局，保存并运行上游 kicad-cli DRC，再导出制造文件 | 输入 PCB、项目与自定义规则共同固定；保护网络/器件不变；原生 DRC 的配置、排除项、规则判断范围保留；退出 0 只代表检查运行完；制造文件由独立消费者打开 | 项目配置漂移；DRC 报告失败/不完整；保存后校验失败；把自写分析器当上游 DRC | [DRC 边界](https://github.com/fatecannotbealtered/kicad-cli/blob/3ec1892926e3c29778d3527ead634506d81b8052/docs/DRC_BOUNDARY.md)及[发布准入](https://github.com/fatecannotbealtered/kicad-cli/blob/3ec1892926e3c29778d3527ead634506d81b8052/docs/RELEASE_ADMISSION.md)；新远端修复不能借旧证据升级为已验证 |
| Creo：明确选择运行实例和模型，在指定单位下改一个尺寸，读回几何，再按授权保存并导出 STEP | 客户端、磁盘服务与实际加载服务分别识别；未保存状态保留；尺寸、单位、体积/拓扑变化与保护特征独立断言；重开模型和独立 STEP 消费成功 | OTK 主线程忙；旧服务仍加载；confirm 前人工改模型；已派发后失回复时查记录而不重发；保存失败 | [README](https://github.com/fatecannotbealtered/creo-cli/blob/0e3302cb104084626d5475af1f3989da7cee1357/README.md)与[历史实机记录](https://github.com/fatecannotbealtered/creo-cli/blob/0e3302cb104084626d5475af1f3989da7cee1357/docs/evidence/live-creo.json)；历史实测的源指纹与当前变更不一致时，不能证明当前版本 |

上述引用是本次阅读的本地提交位置，包含未推送提交；它们不是远端当前版本的验收。对应远端 main 在本次检查中为 Xpedition `d6ff2f38c19f4cdc605c2e5ea9597371538f53f7`、KiCad `ec3ef6f0a4a676130fcaf065077d1ea19084880f`、Creo `d57081b41f4ac0ee9fe2a7e802ac81ce082d2f4a`。本规范没有运行这三个原生软件，也没有改动它们的源码。
