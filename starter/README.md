# 驱动 CLI 种子工程

`common/` 是可实例化的工程模板，供驱动 CLI 的作者接入真实应用、应用文件或设备。生成的产品版本为 `0.1.0`，命令的成熟度从 `draft` 开始。

在本规范的源码目录或已核实的规范包根目录执行：

```powershell
python scripts/instantiate_starter.py --name sample-native-cli --profile file --output D:/work/sample-native-cli
```

`--profile` 可选 `file`、`session` 或 `device`。输出必须是新目录。实例化不创建远端仓库、不联网、不安装依赖、不启动原软件；它复制模板、规范与基线副本和 SDK，生成运行时契约，并在临时状态目录里自检 `reference`、`context`、`doctor`。

生成的工程包含 Agent 入口（`AGENTS.md`、`.agent/AGENT.md`）、固定的规范与基线副本（`.agent/driver/`）、SDK（`.agent/vendor/sdk/`）、副本锁定记录、注册表、CLI 入口与未实现的适配器、命令级测试与 FCC 守卫、CI、CHANGELOG、`pyproject.toml` 以及对齐 SKILL-SPEC 的 Skill 和评测场景。

模板中的占位符：`{{NAME}}`（产品名）、`{{PACKAGE}}`（Python 包名）、`{{VERSION}}`、`{{PROFILE}}`、`{{DATE}}`、`{{ENV_PREFIX}}`（环境变量前缀）。实例化时全部替换。

初始化成功、协议测试通过和真实原生能力的验证分别验收；未实现的适配器只返回 `E_UNSUPPORTED`，不生成假的工程、设备测量或保存回执。使用方法见[工具工程指南](../docs/DEVELOPMENT-GUIDE.md)。
