# tool-driver-cli-spec

一套开发「驱动工具」的规范。驱动工具是让 AI Agent 操作专业桌面软件和设备的命令行工具。

[![Check](https://github.com/fatecannotbealtered/tool-driver-cli-spec/actions/workflows/check.yml/badge.svg)](https://github.com/fatecannotbealtered/tool-driver-cli-spec/actions/workflows/check.yml)
![Spec](https://img.shields.io/badge/spec-1.0.0--rc.1-blue)
![Status](https://img.shields.io/badge/status-in%20development-orange)
![License](https://img.shields.io/badge/license-Apache--2.0-green)

[English](README.md) | 中文

## 这是什么

人划范围，Agent 动手，工具保证每一步做得对、说得清。

新工具本来要自己拿主意的事，规范都替它定好了：项目骨架、文档、内置命令、自更新、驱动模型、写操作流程、适配层边界和一致性测试。工具作者只写领域命令和适配层。所有工具做法一致，Agent 会用一个，就会用全部。

| 要求 | 含义 |
|---|---|
| 看得清 | Agent 随时知道开着哪些实例和文档、有没有未保存的修改、软件是不是忙或被弹窗挡住。 |
| 改得准 | 每次修改都落到明确的实例、文档和对象上，单位明确，改完读回来核实。 |
| 说得实 | 改了没有、存了没有、核实了没有，分开报告；不知道就说不知道。 |
| 不添乱、不拖累 | 人授权能改什么；风险越高确认越严；输出精简，调用次数少。 |

## 五份规范

| 规范 | 编号前缀 | 内容 | 文件 |
|---|---|---|---|
| DRIVER-CLI-SPEC | `DCLI` | 输出与错误、命令、驱动模型、写操作、自更新、适配层与运行时、宿主协议 | [English](spec/DRIVER-CLI-SPEC.md) · [中文](spec/DRIVER-CLI-SPEC_zh.md) |
| DRIVER-SEC-SPEC | `DSEC` | 风险等级、授权范围、不可信内容、状态目录、机密与对外连接、宿主组件、物理动作、供应链 | [English](spec/DRIVER-SEC-SPEC.md) · [中文](spec/DRIVER-SEC-SPEC_zh.md) |
| DRIVER-SKILL-SPEC | `DSKL` | Agent Skill、一个工具多个 Skill、评测、知识库 | [English](spec/DRIVER-SKILL-SPEC.md) · [中文](spec/DRIVER-SKILL-SPEC_zh.md) |
| DRIVER-VERIFY-SPEC | `DVER` | 一致性测试、模拟宿主、行为矩阵、成熟度与证据、真实软件验收 | [English](spec/DRIVER-VERIFY-SPEC.md) · [中文](spec/DRIVER-VERIFY-SPEC_zh.md) |
| DRIVER-REPO-SPEC | `DREPO` | 项目骨架、文档、徽章与标签、固定方式、版本与 CI、npm 分发、能力调查 | [English](spec/DRIVER-REPO-SPEC.md) · [中文](spec/DRIVER-REPO-SPEC_zh.md) |

## 机器契约

工具或测试能当作数据读取的值，都放在 [`contract/driver-contract.json`](contract/driver-contract.json) 里：错误码和退出码、参数、效果和确认级别、回执规则、状态、标准命令、单位、宿主协议和知识库格式。[`contract/schemas/`](contract/schemas/) 是 JSON Schema，[`contract/examples/`](contract/examples/) 是必须通过或必须不通过的示例。规范里的表格由检查脚本与契约核对，两边不会走样。

## 状态

1.0.0-rc.1 正在开发，还没有发布。驱动运行时做出来之前，工具还不能采用本规范。

| 阶段 | 内容 | 状态 |
|---|---|---|
| 1 | 设计 | 完成 |
| 2 | 五份规范、契约、Schema、检查脚本 | 完成 |
| 3 | 模拟宿主，也是宿主协议的参考实现 | 进行中 |
| 4 | Python 驱动运行时、两组一致性测试和项目模板 | 计划中 |
| 5 | Skill 与知识库模板、开发用 Skill、接入指南 | 计划中 |
| 6 | 发布 1.0.0-rc.1，然后发布 1.0.0 | 计划中 |

## 仓库结构

```text
tool-driver-cli-spec/
├── spec/        五份规范，中英文各一份
├── contract/    driver-contract.json、schemas/、examples/
├── conformance/ fakehost/，模拟宿主（DVER-020）
├── scripts/     check_spec.py、build_spec_bundle.py
├── docs/        OPEN-QUESTIONS.md
└── tests/       脚本和模拟宿主的单元测试
```

后续阶段会加上一致性测试、`sdk/`、`template/` 和 `skills/`。

## 检查

```bash
python -m pip install --require-hashes --no-deps -r requirements-dev.txt
python scripts/check_spec.py
python -m unittest discover -s tests -v
python scripts/build_spec_bundle.py
```

## 许可证

Apache-2.0。见 [LICENSE](LICENSE) 和 [NOTICE.md](NOTICE.md)。
