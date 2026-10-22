# SE_02：三 Agent 代码审查工作流

本项目拟构建一个可演示、可追踪的多 Agent 协作 MVP：接收编程任务，经编码、审查、修复和复审，输出代码候选稿、审查报告及执行记录。

**当前阶段：已实现 M1—M4，离线三 Agent 工作流可以完整运行。** 包括领域契约、Mock、仓储日志、编码/审查/修复角色及最多两轮修复的编排引擎。真实模型与通用任务 CLI 尚未实现。

## 开发位置

- 本地工作目录：`E:\python_project\SE\SE_02`
- 远程仓库：https://github.com/NAKADAO0/SE_02
- 所有新增源代码、测试和文档均放在本仓库中。
- 相邻目录的旧作业仅作为背景参考；尚未复制或验证其中模块。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [项目目标](docs/PROJECT_GOALS.md) | 产品定位、范围、成功标准、作业要求映射 |
| [产品需求](docs/PRD.md) | 用户流程、功能优先级、异常规则、验收标准 |
| [架构设计](Design.md) | 模块边界、数据契约、状态机、流程图 |
| [模块化开发流程](docs/DEVELOPMENT_WORKFLOW.md) | 开发顺序、模块任务、依赖、提交与集成方式 |
| [验收与交付](docs/ACCEPTANCE.md) | 验收场景、评分映射、交付检查 |
| [模块详细说明](docs/MODULE_GUIDE.md) | 安装、数据契约、Mock 场景、仓储接口、日志及异常 |
| [M1/M2 实现报告](docs/IMPLEMENTATION_REPORT.md) | 领域契约和基础设施的历史验证证据 |
| [Agent 与编排说明](docs/WORKFLOW_GUIDE.md) | 角色接口、执行顺序、分支、两轮修复、失败处理与扩展 |
| [M3/M4 验证报告](docs/WORKFLOW_REPORT.md) | 本轮新增功能、55 项测试及后续范围 |

## 快速验证（PowerShell）

要求 Python 3.11+；本次在 Windows、Python 3.12.0 验证。运行模块和测试仅使用标准库。安装构建工具时可能需要联网。

```powershell
Set-Location E:\python_project\SE\SE_02
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe examples/workflow_demo.py --scenario repair_pass
```

示例默认跑通“编码 → 审查拒绝 → 修复 → 复审通过”，在 `runs/<run_id>/` 保存历史代码、报告、消息和终态。可选场景为 direct_pass、repair_pass、always_reject、call_failure；退出码分别为 0、0、3、1。`--max-repairs` 可设为 0、1、2，默认 2。详细接口见 Agent 与编排说明。

Mock 使用固定求和样例，不需要密钥或网络，真实模型能力尚未验证。旧的 `infrastructure_demo.py` 仍只演示基础设施检查点，完整流程请使用 `workflow_demo.py`。

完全离线、不安装包也可使用：先运行 `$env:PYTHONPATH = 'src'`，再用 `python -m unittest discover -s tests -v` 和 `python examples/workflow_demo.py --scenario direct_pass`。

## 作业背景

依据用户提供的三张课程截图整理：至少两个 Agent 协作、消息传递或共享状态、基本顺序控制；评分包括流程完整性 40%、Agent 协作 30%、可扩展性 20%、文档 10%。截图中的两周是课程项目周期；本仓库当前安排按 2026-10-25 24:00 截止时间倒排，见开发流程文档。以上为作业背景，具体设计选择与课程硬性要求在文档中分别标注。
