# 可执行 SVG 文件适配器

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

dry-run 不修改目标；confirm 重新核实文件指纹、授权与参数。独立读取测试保护几何及单位；此例不验证制造可行性、原生 CAD/PCB 语义或分发安装，不是三个原生工具的迁移完成证明。文件系统的原子替换不能提供跨应用事务，也不能阻止外部程序在最后一次核实后并发写入；SDK 操作租约只能协调采用本协议的调用方。
