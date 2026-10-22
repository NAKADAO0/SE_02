# 真实模型适配与错误处理

日期：2026-10-22。当前实现位于 `src/se02/providers/http.py`，无第三方运行依赖。

## 1. 连接协议

适配 OpenAI 风格的非流式 Chat Completions：在 base_url 后追加 `/chat/completions`，也支持 base_url 自带 `/v1`。请求使用 Bearer 鉴权，发送 model、system/user messages、`response_format={"type":"json_object"}` 和 `stream=false`。

system 消息来自对应角色的独立提示。user 消息为 JSON，包含 role、task、当前 code 和 review；不把密钥加入消息。读取响应 `choices[0].message.content`，要求 finish_reason 为 stop，不接受工具调用、拒绝、空内容和截断结果。业务 JSON 的字段和版本仍由 Agent 严格检查。

当前用户选定 DeepSeek V4.1 Flash。官方配置为 `https://api.deepseek.com` 和模型别名 `deepseek-flash`；该别名当前服务 V4.1 Flash 系列，具体服务端修订由服务商决定。来源：[DeepSeek 首次调用](https://api-docs.deepseek.com/)、[V4.1 Flash 发布说明](https://api-docs.deepseek.com/news/news260910/)、[Chat Completions 参数](https://api-docs.deepseek.com/api/create-chat-completion/)。本实现也参考 [OpenAI Chat 接口](https://developers.openai.com/api/reference/resources/chat)。

## 2. API

```python
import os
from se02.providers import HttpProvider

provider = HttpProvider(
    base_url="https://api.deepseek.com",
    model="deepseek-flash",
    api_key=os.environ["SE02_API_KEY"],
    timeout=60,
    max_retries=1,
    retry_delay=0.5,
)
```

timeout 为大于 0 且不超过 600 秒的有限数；max_retries 为 0—3 的整数；retry_delay 为 0—30 秒。默认最多两次传输尝试：首次调用加一次重试。

Python API 还支持可选 reasoning_effort=None/none/low/high/max；None 不发送额外字段，由服务端选择。CLI 使用通用协议，不强加某家厂商的思考参数；显式真实验收脚本使用 low。其他兼容服务可能不支持全部参数，应按其官方协议配置并验收。

## 3. 重试分类

| 错误 | 是否可重试 | 行为 |
| --- | --- | --- |
| Socket 超时、连接失败或传输中断 | 是 | 默认再尝试一次 |
| HTTP 408、429、500、502、503、504 | 是 | 同上 |
| HTTP 400、401、402、403、404 等其他状态 | 否 | 立即失败 |
| TLS 证书/握手失败 | 否 | 立即失败 |
| 非 JSON、空 content、截断、工具调用、响应过大 | 否 | 立即失败 |
| Agent 的字段、类型或版本校验错误 | 否 | 编排失败，不重新收费调用 |

重试等待为 `min(30, retry_delay * 2**(attempt-1))` 秒，不解析服务端 Retry-After。每次尝试独立编号，失败后是否进入下一次由错误分类和预算共同决定。传输重试与修复轮次无关。

timeout 传给标准库 HTTP/socket 操作，是网络阻塞超时，**不代表整个工作流的总墙钟上限**；多次请求、重试等待、DNS 解析和持续分段响应的总耗时可能更长。本期未实现跨线程强制中止或总预算调度。

## 4. 记录和进度

HTTP 通过 ContextVar 范围内的 observer 发送 ProviderAttempt，不依赖 Workflow；独立调用时没有日志副作用。编排器把它记录为 ExecutionEvent：

- phase=node：逻辑节点开始、完成、失败或跳过。
- phase=provider：每次 HTTP 尝试的开始、完成或失败，attempt 从 1 重新计数。

phase 字段默认为 node，对既有事件构造保持兼容。事件先保存，再通知 CLI 的 on_event 回调；JSON 结果保持 stdout 独占，进度写 stderr。外部回调异常会作为运行失败处理，不把损坏的观测过程伪报成功。

## 5. 凭据与输出边界

CLI 仅从 SE02_API_KEY 取密钥；拒绝在 TOML 和命令行放明文 api_key，不回显错误参数值。HttpProvider 的 repr 不显示密钥；错误只报告状态码或错误类别，不包括响应体、鉴权头或原始网络异常。

外部 URL 要求 HTTPS，仅允许 localhost/127.0.0.1/::1 使用 HTTP 供本地验收。拒绝 URL 内凭据、query 和 fragment，禁止跟随重定向，避免把 Bearer 头转发到其他站点。

响应读取上限为 2 MiB。返回模型内容前，检查原始内容及 JSON 解码后的所有字符串键和值是否出现当前凭据；包含时立即拒绝，不写入产物。回归测试覆盖 Unicode 转义后的凭据。任务和自定义日志并非通用秘密管理系统，调用者仍不应把秘密写进任务文本。

## 6. 验证层次

1. Provider 本地 HTTP 测试：状态码、超时、重试次数、重定向、畸形响应及脱敏。
2. 本地 HTTP 端到端：真实 CLI → HTTP 服务器 → 三角色 → 修复 → 仓储，包含首次 429 后恢复和 401 失败。
3. 外部 DeepSeek：真实编码/审查、已知缺陷的真实审查/修复，以及真实 CLI 调用。见 [最终验收报告](FINAL_ACCEPTANCE.md)。

例行 `unittest` 不访问外部服务；运行 `examples/live_acceptance.py` 必须显式提供环境凭据，会使用服务额度。真实生成代码只保存和静态检查，不自动执行。
