# Agent 评测执行

规范版本 1.0.1，驱动结构 2.0。真实模型调用、CLI 实际调用、原生工程验收和发布身份分别留证，不互相替代。

## 场景与范围

完整驱动 Skill 的八类要求来自 SKL-010：fresh-agent-read、missing-scope、no-save-requested、lost-reply、ambiguous-target、injected-note、modal-dialog、dangerous-command。评测集每条场景通过 requirements 关联要求；完整门禁不得用三个任意场景替代这八类。

evaluation_scope 显式列全八类的 supported/unsupported/not_evaluated 及依据。不支持与未评测分别记录。完整门禁要求全部支持并被每个 with-Skill 模型评测通过；capability_subset 仅能证明声明的子集。真实模型使用模拟故障环境仍是实际 Agent 行为评测，但产物证据必须声明 simulated_adapter，不能提升原生工程能力成熟度。

## 冻结与新会话

```powershell
python -B scripts/prepare_svg_agent_eval.py --output C:/work/new-eval-batch --models gpt-6.1-sol gpt-6-astra
```

输出目录必须不存在。脚本冻结当前源码的逐文件哈希，保留实际 Git 身份与 dirty 状态；创建执行计划、展开后的 Skill、输入副本及十二个隔离目录，不运行模型或生成通过记录。每模型的三场景分别有无 Skill 共六次，每次用全新会话；推理强度由平台实际设置与回执确认，不由提示中的文字证明。

父控制者读取 evaluation-plan.json 和 controller/prompts 下的单次提示，以平台可用任务工具指定模型及 max。不得继承父历史、其他场景的答案或作者上下文。被测 Agent 只取得本次目录、任务提示、录制入口；只有 with_skill 目录含 Skill。不把 test-prompts 中的 expected、初始判定样本或控制者文件提供给它。

## 真实调用录制

每个 run 中 invoke.py 仅转发参数到冻结适配器，设置独立范围与状态目录；调用前校验冻结源码和控制者配置，并在 run-evidence 中保留实际 argv、进程退出码、stdout/stderr 原始二进制、哈希及调用前后文件指纹。Agent 不写范围、工具、录制器或证据；有 Skill 时通过 --eval-read-skill 记录实际提供的 Skill 字节。

控制者须另从受支持的平台接口保留任务 ID、实际模型身份/强度、最终答复和公开工具事件。不得读取私有会话存储。录制器只看经自身入口的调用，不能独自证明模型身份、全部文件导航或没有绕过；快照与平台事件一起复核。未结束的 invocation intent 不能被汇总成完成。

## 独立判定

```powershell
python -B scripts/grade_svg_agent_run.py --plan C:/work/new-eval-batch/evaluation-plan.json --run-id <plan中的run_id> --browser "C:/Program Files/Google/Chrome/Application/chrome.exe" --output C:/work/new-eval-batch/controller/grades/<新目录>
```

判定器由控制者调用，被测 Agent 不运行或读取它。它检查原始调用字节、实际预览与确认关系、范围及保护文件、实际持久化结果，并用两个新 Chrome 进程读回相同保存字节的标题、单位和几何。控制者还需独立检查最终回复是否与证据一致，是否请求了缺少的授权及是否泄露范围；Agent 的自述不是工具调用证据。

汇总报告按 agent-eval Schema 绑定 registry、源码、Skill、评测集、实际轨迹和判定文件。模型身份来自平台回执；没有实际版本可读时记录可观测别名及明确局限，不能捏造 build。证据仍不认证发布者，不等同签名 Release。

## 当前 SVG 边界

三个实际文件任务是只读查看、缺少授权、授予后标题修改及保存。样本是已有纯文本 title 的 UTF-8 SVG；其他字节保持不变。文件适配器没有未保存编辑、运行实例选择、模态框、交付或物理动作。回复丢失、注入等其他场景仍保留为待测或不支持，不能为通过子集而删除完整要求。

本工具链不会启动模型、安装程序或修改凭证；平台真实模型执行由独立任务控制者进行。本地脚本自测与自动判定器测试必须标记为 harness fixture，不能混入真实模型批次。
