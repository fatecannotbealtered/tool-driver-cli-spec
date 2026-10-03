# Python 原生 CLI 种子

此目录是可实例化的开发模板，供 CLI 实现者接入明确的应用或设备回调。产品初始版本为 `0.1.0`，原生能力初始状态为 `draft`。

从本地规范源码或已核实的规范包根目录执行：

```powershell
python scripts/instantiate_starter.py --name sample-native-cli --profile file --output D:/personalSpace/sample-native-cli
```

`--profile` 可选 `file`、`session` 或 `device`。输出必须是新目录；初始化不创建远端仓库、不联网、不安装依赖，也不启动原软件。
可用 `--registry` 提供调用方控制的产品命令声明。注册表中的自由文本和示例不会被执行。

新目录包含 SDK、公共 Schema、生成模块和校验模块的受控副本，来源和实际文件 SHA-256 记录在 `.agent/starter-lock.json`。
副本漂移检查只覆盖列出的供应文件，不锁死产品自己的回调、注册表和业务代码。可信固定记录与发布者来源认证是不同职责。

接入方式见生成目录的 README。初始化成功、协议测试通过和真实原生能力验证分别验收；原生 stub 不生成假的工程、设备测量或保存回执。
