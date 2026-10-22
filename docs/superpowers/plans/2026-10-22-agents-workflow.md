# Agent 与编排引擎实现计划

日期：2026-10-22；工作目录：`E:\python_project\SE\SE_02`。

目标：在既有领域协议和仓储上交付编码、审查、修复三个角色与有界顺序编排，提供可运行的离线工作流示例。

架构：AgentInput 作为统一输入；Agent.run 返回各角色对应的领域对象。每个角色构造独立 system_prompt，经 Provider 获取严格 JSON，执行结构与上下文校验，不写文件。Workflow 每次运行创建独立执行上下文，持久化消息、节点事件和状态，最多两轮修复。网络和重试留给后续 Provider 实现。

## 约束

- 继续使用标准库与 Python 3.11+；本轮不实现真实模型、任意任务 CLI 或 UI。
- 默认修复上限 2，可显式配置为 0 或 1，不允许超过 2。
- 报告必须绑定当前代码，修复必须是下一版本且逐项对应问题 ID。
- succeeded 只能在通过报告、消息、完成事件与最终状态全部写入后返回。
- 节点异常进入 failed；保存失败记录也失败时，在返回值中列出 persistence_errors，不伪称已完整落盘。

## Task 1：三个角色

文件：`src/se02/agents/{base,roles,__init__}.py`，`tests/test_agents.py`。

接口：`AgentInput(task, code=None, review=None)`；`CodingAgent(provider).run(input) -> CodeArtifact`；ReviewAgent 返回 ReviewReport；RepairAgent 返回 FixResult。`Agent` Protocol 定义 role 和 run，可被外部角色实现替换。

- [ ] 测试先行：独立提示、请求上下文、v1 约束、畸形 JSON、重复字段、NaN、版本错配及修复映射错误。
- [ ] 观察新测试因缺少 agents 包失败，再实现严格解析和角色校验。
- [ ] 验证测试通过并提交独立 Agent 模块。

## Task 2：编排引擎

文件：`src/se02/workflow/{models,engine,__init__}.py`，`tests/test_workflow.py`。

接口：`Workflow(provider, root="runs", agents=None).run(task, config=None) -> RunResult`；WorkflowConfig.max_repairs 默认 2；RunResult 含终态、路径、最终产物引用、持久化错误及 exit_code。

- [ ] 测试先行：直接通过、修复通过、第二轮通过、持续拒绝、0/1 上限、调用异常、畸形/错配响应、独立运行及角色替换。
- [ ] 注入节点完成日志、代码保存、终态保存故障，确认 failed 和诊断信息。
- [ ] 观察新测试因缺少 workflow 包失败，再实现顺序编排与统一异常收口。
- [ ] 检查真实磁盘文件和节点顺序，验证全部测试并提交引擎。

## Task 3：演示、说明、审查与交付

文件：`examples/workflow_demo.py`、`tests/test_workflow_example.py`、`docs/WORKFLOW_GUIDE.md`，更新 README、Design、开发流程、验收及实现报告。

- [ ] 先测试四场景脚本的退出码和终态，再实现示例；示例仅暴露离线样例选择。
- [ ] 写明 Agent/Workflow 接口、消息关系、节点状态、计数语义、失败落盘和扩展方法。
- [ ] 运行全部测试、四种演示、文档代码、编译及 diff 检查；完成独立审查和回归。
- [ ] 按用户已授权的 Git 流程集成 main、推送并核对本地与远程提交。
