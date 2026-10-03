# {{NAME}}

产品版本：`{{VERSION}}`；状态：`draft`；驱动模式：`{{PROFILE}}`。

这是原生应用或设备 CLI 的开发种子。初始化目录只复制契约、SDK 和代码，没有连接原软件，也没有执行任何设备动作。原生能力仍是拒绝执行的占位适配器。

## 离线启动

使用 Python 3.11+ 及 `requirements.txt` 中已经安装的依赖；初始化器和以下命令不下载依赖，不发布到 npm。

```powershell
python -I check_project.py
python -I cli.py reference
python -I cli.py reference --capability native-inspect
python -I cli.py context
python -I cli.py doctor
python -I cli.py native inspect --target-id example
```

`reference` 先返回轻量索引，详情按能力获取，完整契约使用 `reference --full`。最后一条命令应返回 `E_UNSUPPORTED`；这证明占位边界，不能代表真实应用可用。

`.agent/starter-lock.json` 记录来源提交、源码是否包含未提交修改及各份 vendored 文件的哈希。`check_project.py` 拒绝文件漂移和链接，不联网修复副本；它假设固定记录来自可信调用方，不认证发布者。
锁损坏或依赖不可用时，bootstrap 会在加载 SDK、解析业务调用及执行适配器之前拒绝。此时请求标识可能是新生成的 `bootstrap-*`，并明确报告 `dispatch_state=not_started`；它不是已派发原生操作的标识。

## 接入回调

1. 在 `registry.json` 中声明目标、参数、效果、阶段、私有请求和结果 Schema。它是产品命令的单一来源。
2. 在 `callbacks.py` 中显式接入适配器。模块导入和工厂只构造协议对象，不修改目标、保存或启动原软件；实际原生动作在 SDK 验证后的 `execute(invocation)` 中执行。不从目标内容、registry 的自由文本或原生消息中导入模块或执行命令。
3. 修改前核实任务授权、目标和基线；修改后读回实际状态，按请求决定是否保存，再验证持久化产物。
4. 失去回复时先查询已知操作，不盲目重发；设备真实动作不能冒充隔离试执行。
5. 取得独立真实证据后再提升对应能力的成熟度。SDK 通过和生成项目成功均不能提升原生能力。

文件模式按实际文件及独立消费者验收；会话模式补实例身份、连接代际、主线程和未保存状态；设备模式补真实动作、观测时效和适用前置条件。

CLI、Skill 和运行中的插件分别声明兼容关系。Skill 只写任务意图和配方，参数和结果以当前 reference 为准。
