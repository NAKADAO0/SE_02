# M3/M4 实现与验证报告

日期：2026-10-22；开发目录：`E:\python_project\SE\SE_02`。

本文是 M3/M4 阶段的历史记录。CLI、真实模型与交付现已另行完成，最新状态及测试数量见 [最终报告](FINAL_ACCEPTANCE.md)。

## 1. 本轮交付

- 三个独立 Agent：CodingAgent、ReviewAgent、RepairAgent；统一 AgentInput/Agent Protocol。
- 独立角色提示和严格 JSON 解析；输出类型、初始版本、报告关联及修复映射校验。
- Workflow、WorkflowConfig、RunResult；默认最多两轮修复，可降低至 0 或 1。
- 顺序调用、通过分支、修复与复审循环、超限人工介入、统一错误终态。
- 各节点事件、消息、代码历史、审查报告、修复映射及运行状态落盘。
- 支持替换现有角色，替换后的输出仍需接受编排层校验。
- workflow_demo.py 可运行离线完整流程；之前的 infrastructure_demo.py 保留为模块检查点示例。

本轮没有实现真实网络 Provider、用户任务 CLI、UI、生产沙箱或崩溃续跑。

## 2. 测试结果

环境为 Windows、Python 3.12.0。运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

共 55 项，54 项通过、1 项跳过、0 失败。跳过仍是 M2 中的真实符号链接测试，当前 Windows 账户无创建权限；其余路径检查已执行。

本轮新增 26 项：Agent 7 项、Workflow 17 项、工作流示例 2 项。既有 29 项回归保持通过（包含上述跳过）。

| 行为 | 证据 |
| --- | --- |
| 独立角色与上下文 | 捕获请求，确认三个 system_prompt 不同，task/code/review 原样传递 |
| 严格输出 | 畸形 JSON、围栏、重复键、NaN/Infinity、类型和版本错误被拒绝 |
| 直接通过 | 只有编码和审查调用，repair_count=0，记录修复 skipped |
| 一轮修复通过 | 精确调用 coder/reviewer/fixer/reviewer，复审消费 v2 |
| 第二轮通过 | 两次修复后 review_2 通过，终态 succeeded |
| 持续失败 | 最多一次编码、三次审查、两次修复，needs_attention，无 v4 |
| 配置边界 | 0/1 修复上限有效，3、负数、布尔和字符串被拒绝 |
| 上游错误 | 错版本报告不触发修复，坏响应和意外调用异常进入 failed |
| 注册角色 | 自定义审查角色生效，但不能绕过版本校验 |
| 保存失败 | 代码、完成事件、成功快照保存失败均不返回成功 |
| 二次持久化故障 | 错误事件或错误快照无法保存时，返回 persistence_errors |
| 新版本复审失败 | final_review_ref 清空，旧报告留在历史，不错误绑定 |
| 独立运行 | 同一 Workflow 两次调用的目录、消息 run_id、计数均隔离 |
| 脚本使用 | 四场景真实子进程返回预期 JSON、退出码和磁盘终态 |

## 3. 开发与审查

本轮先加入 Agent 测试并观察缺少模块导致失败，再实现角色；Workflow 和示例使用相同测试先行流程。通过独立只读代码审查，未发现可复现的重要缺陷。

已实际运行四种场景，结果与上表一致；执行 `python -m compileall -q src tests examples`、两份模块指南的全部 Python 代码块和本地文档链接检查。示例子进程经独立复查，输出与磁盘终态一致。

详细接口、执行图、次数语义、异常与文件位置见 [Agent 与编排说明](WORKFLOW_GUIDE.md)。真实模型质量仍未验证；Mock 全流程通过仅验证协议与编排行为。

## 4. 后续范围

M5：用户任务输入、配置和进度显示；M6：真实 HTTP Provider、超时与重试；M7：真实模型样例、干净环境验证及课程交付。现有离线工作流可作为上述模块的稳定集成入口。
