# M1/M2 实现与验证报告

日期：2026-10-22。实现目录：`E:\python_project\SE\SE_02`。

本文记录 M1/M2 阶段的历史交付与 29 项测试。当前 M3/M4 已另行实现，最新结果见 [M3/M4 报告](WORKFLOW_REPORT.md)，以下阶段范围不代表当前全部能力。

## 1. 交付范围

| 模块 | 交付内容 | 结果 |
| --- | --- | --- |
| M1 领域契约 | Task、CodeArtifact、ReviewIssue、ReviewReport、FixResult、Message、RunState、ExecutionEvent | 已实现 |
| 严格校验 | 类型、语言、字符上限、版本链、审查矛盾、问题映射、带时区时间、状态迁移 | 已实现 |
| 快照与协议 | frozen dataclass、tuple、只读映射、嵌套 JSON 往返、schema_version=1 | 已实现 |
| M2a Provider | Protocol、结构化请求、四类确定性 Mock 场景、调用失败异常 | 已实现 |
| M2b 仓储 | 独立目录、代码与元数据、报告、修复映射、消息、运行快照 | 已实现 |
| M2b 日志 | JSONL 消息、节点事件、尝试序号、耗时、版本与错误信息 | 已实现 |
| 可复现使用 | pyproject、标准库测试、模块示例、详细说明 | 已实现 |

未实现 Agent 角色、自动调度、网络请求、真实模型重试、完整任务 CLI、UI、课程压缩包和视频；未执行完整课程验收。

## 2. 测试证据

环境：Windows、Python 3.12.0；声明支持 3.11+，没有声称已对所有 Python 版本实测。

在本地虚拟环境成功执行 `python -m pip install -e .`，构建并安装 se02-workflow 0.1.0；程序无第三方运行依赖。

主测试命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

结果：共 29 项，28 项通过，1 项跳过，0 失败。跳过项为真实符号链接越界测试，原因是当前 Windows 账户无创建符号链接权限；普通路径越界、盘符和 Windows 名称校验已通过，不能将跳过项表述为已经验证。

还实际运行了四类场景示例、`python -m compileall -q src tests examples`，并执行模块说明中的全部 Python 代码块；结果符合预期。本地 Markdown 链接与 `git diff --check` 检查通过。示例后续复查未发现新的重要问题。

| 测试文件 | 项数 | 主要证据 |
| --- | --- | --- |
| test_domain.py | 10 | 输入边界、嵌套协议、不可变数据、审查与修复关系、终态保护 |
| test_infrastructure.py | 17 | 四类场景、版本与运行隔离、历史冲突、路径校验、状态原子替换、故障注入、CRLF |
| test_example.py | 2 | 子进程分别运行四个场景，检查退出码、真实文件、日志和检查点状态 |

开发过程中先加入测试，分别观察到领域包、基础设施包和示例缺失导致失败，再实现并重新运行测试。额外故障注入证明：state 替换失败仍保留之前快照；代码元数据发布失败保留已有源码并报错，拒绝覆盖或继续审查该不完整产物。

## 3. 代码审查与修复

已通过独立只读审查。审查发现 CRLF 源码保存后被文本读取自动转换为 LF，造成合法文件被误判为不匹配；先加入回归测试确认失败，再改为 UTF-8 字节比较，回归已通过。

边界检查还发现仓储公开方法接收非字符串路径或运行 ID 时会泄露 AttributeError/TypeError。已用测试复现并将公共校验统一为 ValidationError。

## 4. 使用入口

- 快速安装和运行：[README](../README.md)。
- 字段、接口、完整 API 代码示例、异常和原子性边界：[模块详细说明](MODULE_GUIDE.md)。
- 后续模块顺序：[模块化开发流程](DEVELOPMENT_WORKFLOW.md)。

示例会创建本地 runs 目录，已经加入 Git 忽略规则。普通场景停在 awaiting_workflow 检查点，不将一次 Mock 调用当作完整工作流成功；调用故障场景记录 failed。真实模型能力尚未验证。

## 5. 下一步

以本轮契约为固定接口开发 M3 三个角色，再实现 M4 有界编排。编排器需补齐开始/完成/失败事件、两轮修复上限、终态业务证据和状态一致性；不能仅凭 Mock 预置响应声称模型已具备审查能力。
