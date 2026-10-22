# 领域契约与基础设施 Implementation Plan

**Goal:** 交付可独立使用的领域对象、离线 Provider、产物仓储和事件日志。

**Architecture:** 标准库 dataclass 表示不可变对象；显式校验和 JSON 编解码维护协议；文件仓储负责路径约束、不可覆盖的历史及可替换状态快照。Mock 提供预置求和任务的四种场景，不实现工作流调度。

**Tech Stack:** Python 3.11+，标准库 unittest、dataclasses、json、pathlib；无第三方运行依赖。

## Global Constraints

- 工作目录固定为 `E:\python_project\SE\SE_02`。
- 协议版本 1，任务语言 python，任务正文不超过 10,000 Unicode 字符。
- 修复次数最多 2；终态不可再次迁移；所有时间带时区。
- 本轮不实现 Agent、编排器、真实 HTTP 模型和用户任务 CLI。

## Task 1：领域契约

文件：`src/se02/domain/{base,models,errors}.py`、`tests/test_domain.py`。

输出：Task、Message、CodeArtifact、ReviewIssue、ReviewReport、FixResult、RunState、ExecutionEvent；`to_dict/from_dict`；`ReviewReport.validate_for(code)`；`FixResult.validate_for(code, report)`；`RunState.transition(status, ...)`。

- [x] 先写边界输入、报告矛盾、版本错配、嵌套 JSON 往返、不可变快照和状态回退测试。
- [x] 运行 `python -m unittest discover -s tests -p test_domain.py -v`，确认因缺少模块失败。
- [x] 实现 dataclass 契约、类型校验、跨对象关系校验及状态迁移。
- [x] 同一命令确认通过后提交领域模块。

测试用例核心：`ReviewReport(artifact_version=1, verdict="pass", issues=(major_issue,), summary="检查")` 必须拒绝；`running.transition("pending")` 必须拒绝。

## Task 2：基础设施

文件：`src/se02/providers/{base,mock}.py`、`src/se02/storage/filesystem.py`、两个包的导出及 `tests/test_infrastructure.py`。

消费 Task、CodeArtifact、ReviewReport、RunState、Message、ExecutionEvent。输出 `ProviderRequest`、`Provider.complete(request) -> str`、`MockProvider` 和 `ArtifactStore`。

- [x] 先写四种场景、请求版本错配、隔离运行、历史冲突、路径越界、消息引用、日志 JSONL 和写入故障测试。
- [x] 执行 `python -m unittest discover -s tests -p test_infrastructure.py -v`，确认缺少实现。
- [x] 实现无网络 Mock；save_task/save_code/save_review/save_fix/save_state/append_message/append_event，磁盘故障统一 StorageError，契约错误保持 ValidationError。
- [x] 执行上述测试和全部测试后提交。

测试用例核心：重复 `store.save_code(code_v1)` 必须失败且原内容保留；`store.resolve_ref("../outside.json")` 必须拒绝。

## Task 3：可复现示例、说明与交付

文件：`examples/infrastructure_demo.py`、`docs/MODULE_GUIDE.md`、README、Design、开发流程及验收记录。

- [x] 示例只展示请求调用与仓储 API，清楚标注不含自动编排，不执行代码。
- [x] 文档给出 PowerShell 安装、测试、示例命令，字段、异常、目录和限制。
- [x] 运行全部测试、四种示例、编译检查和 `git diff --check`。
- [x] 完成接口自审、独立代码审查和修复回归；Git 集成结果以仓库提交历史为准。

## 执行方式

本次按用户指定目录在功能分支内顺序实现，不另建工作区。按以上顺序执行红绿测试；进度与最终证据记录在 `docs/IMPLEMENTATION_REPORT.md`。
