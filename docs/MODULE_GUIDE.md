# 领域契约与基础设施：详细开发说明

版本 0.1.0；日期 2026-10-22。开发目录为 `E:\python_project\SE\SE_02`。

## 1. 这次交付了什么

M1 提供严格、不可变且可 JSON 编解码的数据契约；M2 提供无网络 Mock 模型、独立运行目录、版本化产物仓储、结构化消息和执行事件。模块之间没有模型 SDK 依赖。

三个 Agent、自动流程调度、修复次数调度、真实模型调用、调用超时和重试尚未实现。ProviderError 已预留 retryable 标识；本轮 Mock 的调用失败不可重试。RunState 中修复计数只能是 0—2，何时增加由后续编排器负责。

## 2. 安装和验证

在 PowerShell 执行：

```powershell
Set-Location E:\python_project\SE\SE_02
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe examples/infrastructure_demo.py --scenario direct_pass
```

Python 要求为 3.11+，当前实际验证环境为 3.12.0。源码和测试均只用标准库。`pip install -e .` 会通过构建隔离安装 setuptools，首次可能需要联网；没有网络时可跳过安装，设置 `$env:PYTHONPATH = 'src'` 后运行系统 Python。虚拟环境和运行目录均已加入忽略规则。

## 3. 文件结构和依赖

| 文件 | 责任 |
| --- | --- |
| `src/se02/domain/base.py` | 严格类型检查、不可变集合、JSON 编解码、路径和标识检查 |
| `src/se02/domain/models.py` | 业务字段、不变量和对象关系 |
| `src/se02/domain/errors.py` | 分层异常类型 |
| `src/se02/providers/base.py` | Provider Protocol 和请求上下文契约 |
| `src/se02/providers/mock.py` | 四种确定性求和样例场景 |
| `src/se02/storage/filesystem.py` | 运行目录、历史保护、快照和日志 |
| `examples/infrastructure_demo.py` | 展示公开 API 的人工固定调用示例 |
| `tests/test_domain.py` | 输入边界、对象关系和状态测试 |
| `tests/test_infrastructure.py` | 模型场景、仓储集成、故障注入测试 |
| `tests/test_example.py` | 以子进程运行示例并检查真实落盘结果 |

依赖方向为 providers → domain，storage → domain，example → 三个模块。domain 不访问文件、环境变量或网络。

## 4. 数据契约

所有对象均使用关键字参数创建。`to_dict()` 返回独立的 JSON 兼容字典，`from_dict()` 恢复嵌套类型和日期；不接受未知字段和缺失的必填字段，不将字符串数字转换为整数，也不将布尔值当作整数。

| 对象 | 字段和规则 |
| --- | --- |
| Task | `task_id`、`description`、`language="python"`；正文非空白且不超过 10,000 字符 |
| CodeArtifact | `artifact_id`、`version`、`source`、`explanation`、`language="python"`、`parent_version=None`；代码和说明非空；v1 无父版本，vN 的父版本必须为 N−1 |
| ReviewIssue | `issue_id`、`severity`、`description`、`suggestion`；严重度仅 blocker/major/minor |
| ReviewReport | `artifact_version`、`verdict`、`issues`、`summary`；fail 至少一个问题；问题 ID 不重复；pass 不允许 blocker/major |
| FixResult | `code_artifact`、`changes`；changes 为问题 ID 到修改说明的只读映射 |
| Message | `message_id`、`run_id`、`sender`、`receiver`、`kind`、`payload_ref`、`created_at`、`schema_version=1` |
| RunState | `run_id`、`status="pending"`、`current_node=None`、`repair_count=0`、`artifact_refs=()`、`message_refs=()`、`started_at=None`、`ended_at=None`、`error=None`、`schema_version=1` |
| ExecutionEvent | `run_id`、`node`、`status`、`attempt=1`、`artifact_version=None`、`elapsed_ms=None`、`detail=None`、`created_at`、`schema_version=1` |

ID 采用 1—128 个 ASCII 字符：首字符为字母或数字，其余可含字母、数字、下划线和连字符。Message.kind 为 task/code/review/fix/error。节点状态为 pending/running/completed/failed/skipped；attempt 为正整数；耗时必须有限且非负。

不可变不仅限于 dataclass 属性：输入列表复制为 tuple，changes 复制为只读 MappingProxyType，外部修改原字典不会影响快照。需要新快照时用 `dataclasses.replace()`，会重新执行校验。

### 跨对象校验

`report.validate_for(code)` 检查报告版本等于代码版本；`fix.validate_for(previous, report)` 要求报告针对 previous 且判定 fail、新代码版本恰好加一、changes 精确覆盖所有问题 ID。它们不证明修复内容的语义正确性。

构造 FixResult 只能检查自身字段；调用上述跨对象方法后才算完成上下文校验。ProviderRequest 与仓储 save_fix 会自动执行这一步。

### 时间和状态迁移

自动时间戳使用 UTC，序列化为带偏移的 ISO 8601；调用者可传入任意带时区 datetime。界面未来按 Asia/Shanghai 展示，当前示例输出原始协议时间。

```python
from se02.domain import RunState

pending = RunState(run_id="example-run")
running = pending.transition("running", current_node="coder")
failed = running.transition("failed", current_node="coder", error="模型调用失败")
assert pending.status == "pending"  # 原对象不变
assert failed.ended_at is not None
```

允许 pending → running/failed；running → succeeded/failed/needs_attention。pending → failed 用于启动前错误。终态不能再次迁移，running 必须有开始时间而无结束时间，终态必须有结束时间，failed 必须有非空错误。成功与需人工处理还要求存在开始时间；结束时间不得早于开始时间。

领域层只验证状态结构；审查通过、产物保存完成或达到修复上限等业务证据由后续编排器决定，本轮不把合法状态对象等同于工作流已完成。

## 5. Mock 模型与 Provider 接口

公开接口是 `Provider.complete(request: ProviderRequest) -> str`。返回文本为 JSON；调用方选择 CodeArtifact、ReviewReport 或 FixResult 解析。不自动执行返回的代码。

ProviderRequest 含 role、task、code、review、system_prompt、output_format。role 为 coder/reviewer/fixer；coder 只接受任务，reviewer 要求代码且不接受既有报告，fixer 要求代码和匹配版本的 fail 报告。output_format 当前仅 json。

| 场景 | 编码响应 | 审查响应 | 修复响应 |
| --- | --- | --- | --- |
| direct_pass | `sum(values)` | 代码等于正确样例则 pass | 对合法失败报告返回下一版正确样例 |
| repair_pass | 空列表错误返回 None | 初稿 fail，正确样例 pass | 返回下一版正确样例并映射问题 ID |
| always_reject | 错误求和样例 | 始终 fail | 返回新版本错误样例，供后续超限测试 |
| call_failure | 抛 ProviderError | 同左 | 同左 |

Mock 根据请求内容响应，不以全局调用次数改变结果；报告版本来自请求 code，修复版本为 code.version+1。任务文字和 system_prompt 不会驱动通用代码生成，示例始终是 total(values) 求和。always_reject 是故障样例，不代表真实审查结论；Mock 本身没有两轮上限调度。

下列代码展示完整的接口数据传递，但不是可复用的编排引擎：

```python
import json
from se02.domain import Task, CodeArtifact, ReviewReport, FixResult
from se02.providers import MockProvider, ProviderRequest
from se02.storage import ArtifactStore

task = Task(task_id="sum", description="实现 total(values)，空列表返回 0")
provider = MockProvider("repair_pass")
code = CodeArtifact.from_dict(json.loads(provider.complete(
    ProviderRequest(role="coder", task=task))))
report = ReviewReport.from_dict(json.loads(provider.complete(
    ProviderRequest(role="reviewer", task=task, code=code))))
fix = FixResult.from_dict(json.loads(provider.complete(
    ProviderRequest(role="fixer", task=task, code=code, review=report))))
fix.validate_for(code, report)
store = ArtifactStore.create("runs")
store.save_task(task)
store.save_code(code)
store.save_review(report, code, review_index=0)
store.save_fix(fix, code, report)
print(store.run_dir)
```

## 6. 产物仓储 API

| 方法 | 返回相对路径 | 关键行为 |
| --- | --- | --- |
| `ArtifactStore.create(root, run_id=None)` | 返回仓储对象 | 默认 UUID；同名目录存在即失败 |
| `resolve_ref(ref)` | 返回 Path | 只接受运行目录以内的安全相对 POSIX 路径 |
| `save_task(task)` | `task.json` | 一次写入，不能覆盖 |
| `save_code(code)` | `code/vN.py` | 同时保存 vN.json 元数据；新版本要求父版本元数据存在 |
| `save_review(report, code, review_index=N)` | `reviews/review_N.json` | 验证版本和已保存源码的精确 UTF-8 字节及元数据 |
| `save_fix(fix, previous, report)` | `fixes/fix_vN.json` | 要求上游代码和匹配报告已保存；创建新代码及修复映射 |
| `save_state(state)` | `state.json` | 原子替换；校验运行 ID、引用存在、迁移、开始时间不变及计数不减 |
| `append_message(message)` | `messages/<message_id>.json` | 先保存唯一消息文件，再追加 messages.jsonl；载荷必须存在 |
| `append_event(event)` | `events.jsonl` | 单行 JSON 追加；记录节点、尝试序号、版本、时间、耗时和详情 |

状态终态只能保存相同快照，不能修改。未保存过 state 时仓储允许合法的初始快照，调用方应按 pending → running 顺序记录过程。事件追加不是状态机，仓储不会自行推导下一节点或 retry。

典型产物如下：

```text
runs/<run_id>/
├── task.json
├── state.json
├── code/
│   ├── v1.py
│   ├── v1.json
│   ├── v2.py
│   └── v2.json
├── reviews/review_0.json
├── fixes/fix_v2.json
├── messages/<message_id>.json
├── messages.jsonl
└── events.jsonl
```

代码按原始 UTF-8 字节保存，不统一 CRLF/LF；JSON 采用 UTF-8，保留中文。路径拒绝绝对路径、盘符、反斜杠、空段、`.`、`..`、Windows 保留名、控制字符及非法字符；解析后再检查符号链接目标没有逃出运行目录。

### 原子性与故障边界

文件先写同目录临时文件并 flush/fsync。历史文件用硬链接发布，目标已存在时失败；state 用 os.replace 替换。需要支持硬链接的本地文件系统，本次在 Windows 本地盘验证。临时文件在正常完成或已处理失败时清理；断电后的临时文件不自动恢复。

单个 JSON/代码文件发布是原子的；save_code、save_fix、append_message 涉及多个文件，**不是整批事务**。例如源码写入成功而元数据失败时，保留源码并抛 StorageError，该版本不能重写，应保留失败目录并新建运行。日志追加也不保证断电后无截断尾行，不提供自动重试或崩溃续跑。

采用每次运行一个写入者的模式，不支持多个进程并发修改同一运行目录；UUID 隔离正常运行，不防御其他进程在校验后恶意替换目录。事件和任务数据不自动脱敏，调用方不要把密钥放入任务或日志 detail；runs 不入 Git。

## 7. 异常处理与示例行为

- ValidationError：类型、不变量、版本关系、运行关联和路径违反契约。
- StorageError：目录冲突、历史已存在、引用缺失或磁盘读写失败。
- ProviderError：调用失败；retryable 为未来重试策略提供分类。
- DomainError：上述异常的共同基类，可在应用入口统一捕获。

`infrastructure_demo.py` 成功写入一次编码和审查交换时退出 0，表示示例产物已保存，不表示完整工作流成功。它显式保存 running/awaiting_workflow；repair_pass 在这里的报告为 fail，没有自动修复。修复调用由上面的 API 示例和集成测试展示。call_failure 场景退出 1，保存失败事件及 failed 状态。用例 `--scenario` 只选择样例，不支持用户编程任务。

## 8. 后续接入点

新增 Agent 负责提示构造与解析；直接使用 ProviderRequest 和上述契约，不写磁盘。新增编排器负责角色顺序、修复上限、终态业务判断、消息关联和异常落盘；使用 ArtifactStore 保存所有结果。真实 Provider 实现相同 complete 方法，在自己的层内处理网络超时和重试，不修改领域协议。
