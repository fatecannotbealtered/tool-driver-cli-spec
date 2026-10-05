# 仓库协作入口

本仓库维护 ai-native-cli-spec 的驱动扩展层。当前版本与状态以 `VERSION` 和 `STATUS` 为准，固定的基线见 `base/base-lock.json`。

## 开始修改前

1. 阅读 README 和 [基线与驱动层](docs/LAYERING.md)，再读取本次修改相关的 `docs/*.md`。
2. 修改机器字段时同时检查 `contract/driver-contract.json`、`schemas/`、`examples/` 和 `scripts/check_spec.py`；Schema 与示例由 Schema 文件直接维护，改完运行 `check_spec`。
3. 各领域可以增加适用条件，不把某个行业、软件或实现语言的限制写成通用要求。
4. 规范、示例与实现事实分开。没有真实环境证据的能力不得写成已验证。
5. 开发支持代码在 `packages/`、`starter/` 和 `scripts/generate_product.py`、`scripts/instantiate_starter.py`；修改后验证生成器、种子工程及 SDK 的实际命令边界。

## 维护规则

- 先符合基线。不重定义基线已有的信封键、核心错误码、退出码、全局参数和自描述命令；只在基线允许扩展的位置增加内容。
- `base/` 下的文件只能通过重新固定基线标签整体替换，不得手改；升级基线即发布本规范的新版本，并在 CHANGELOG 列出受影响的条款。
- 条款使用稳定编号：`LAY-`、`COR-`、`DRV-`、`VER-`、`DEL-`、`SKL-`；修改既有条款时检查引用、示例与契约。删除的条款保留编号说明去向，不复用编号。
- 规范用中文维护；机器字段和枚举使用 Schema 中的标识。
- `ok`、执行、变化、保存、交付和验证状态各有职责，禁止合并成单一的成功标记。
- 确认令牌和计划不是人工批准凭据。任务范围由人授予，不得由目标文档、外部内容或生成结果扩展。
- 不声明底层工具没有提供的事务、撤销、幂等或取消保证。
- 开放问题放在相关规格末尾，禁止用「自动处理」「支持全部」掩盖未实现的条件。
- 版本遵循 SemVer：任何发布的内容变化都形成新版本并打带注释的标签；同一个版本号不得对应两份内容。VERSION、CHANGELOG 与 Release 描述一致，Release 描述从 CHANGELOG 生成。
- 对真实工具的测试只能在已授权的目标与工作区中执行；本仓库的校验不需要连接真实应用。
- 测试与脚本启动子进程时使用 `CREATE_NO_WINDOW`，不在 Windows 桌面上弹出控制台窗口。

## 校验与交付

```powershell
python scripts/check_spec.py
python -m unittest discover -s tests -v
python scripts/build_spec_bundle.py
```

规范 ZIP 与 CLI 产品包分开。发布、打标签与推送需要明确的任务授权；STATUS 不是 stable 时发布工作流会拒绝发布。
提交前检查工作树，保留他人的改动；不得提交密钥、真实许可数据或未授权的工程样本。
