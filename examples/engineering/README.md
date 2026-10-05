# SVG 文件模式参考实现

这是非规范性参考实现，展示一个真实文件能力及其独立消费方法；SVG、图纸对象和浏览器都不是采用本规范的通用必备能力。此目录的工程命名保留现有路径，不表示规范只适用于工程图形。其他文件格式、运行实例和设备仍须分别接入与验收。

此例提供 `drawing inspect` 与 `drawing set-title`，以及 SDK 的 reference、context、doctor、changelog 和 operation 命令。它使用仓库内 SDK，无需安装或连接 CAD；适用于一个已有、无 DTD/实体声明、UTF-8 编码、至多 1 MiB 的常规 SVG 文件，根下有一个纯文本 title。标题外的字节原样保留，包括几何、单位和备注。

```powershell
python examples/engineering/svg_title_driver.py reference --index
python examples/engineering/svg_title_driver.py drawing inspect --file D:/work/copy/part.svg
```

写操作先由用户授予 `sample-driver` 的范围文件；设置 `SAMPLE_DRIVER_SCOPE_FILE` 和 `SAMPLE_DRIVER_STATE_DIR` 可使用独立目录。范围格式参见 [scope Schema](../../schemas/scope.schema.json)，只授予任务所需的 `observe/change/persist`、工程根目录和保存位置。

```powershell
python examples/engineering/svg_title_driver.py drawing set-title --file D:/work/copy/part.svg --title "Bracket" --dry-run
python examples/engineering/svg_title_driver.py drawing set-title --file D:/work/copy/part.svg --title "Bracket" --confirm <data.confirm_token>
python examples/engineering/svg_title_driver.py operation show --id <receipt.operation_id>
python -m unittest discover -s tests -p test_engineering_example.py -v
```

dry-run 不修改目标；confirm 重新核实文件指纹、授权与参数。独立读取测试保护几何及单位；此例的证据限于声明的标题修改、保护不变量和文件消费，不验证制造可行性、其他格式的领域语义或分发安装。文件系统的原子替换不能提供跨应用事务，也不能阻止外部程序在最后一次核实后并发写入；SDK 操作租约只能协调采用本协议的调用方。
