# CLI、真实模型与交付实现计划

日期：2026-10-22；目标：完成 M5—M7 并推送远端。

## 架构和边界

- CLI：`python -m se02 run --task FILE` 与 `se02` console script；支持 `demo` 固定样例。run 默认 http，Mock 必须显式指定。任务输入 UTF-8，配置优先级 CLI > SE02 环境变量 > TOML > 默认值，密钥只接受 SE02_API_KEY。
- HTTP：标准库适配 Chat Completions；公开 `HttpProvider(base_url, model, api_key, timeout=60, max_retries=1, retry_delay=0.5)`。发送结构化 task/code/review，解析 choices[0].message.content；真实服务协议以其官方文档确认。
- 重试：仅超时、连接故障、429 和临时 5xx，默认一次；鉴权、其他 4xx 和响应格式错误不重试。响应体有大小限制，禁止重定向泄露鉴权头，错误不包含服务响应体或密钥。
- 观测：ProviderAttempt + context-local observer，HTTP 每次尝试写入 ExecutionEvent（phase=provider），逻辑节点事件 phase=node。Workflow 的 on_event 回调给 CLI 输出进度，不混淆修复与传输尝试。
- 交付：确定性白名单源码 ZIP 与 SHA256，排除密钥、缓存和 runs；包含安装说明、验收结果及离线样例。包小于 200MB，解压后独立运行测试和 CLI。

## 开发任务

1. HTTP 适配（主任务）：先写本地 HTTP 服务器测试，覆盖请求、401、429、500、超时、重试、格式错误、响应限制及密钥不泄露，再实现 Provider 与 telemetry。
2. CLI（独立任务）：实现 config.py、cli.py、__main__.py、console entry；为 Workflow 添加 on_event 和 Provider telemetry 转发。先写输入/配置/退出码/进度测试。
3. 打包（独立任务）：实现 scripts/build_release.py、test_packaging.py 和 PACKAGING 文档；白名单和哈希验收。
4. 集成：HTTP 本地协议服务器贯穿 CLI→三角色→仓储；如服务可用，实际调用用户指定模型，保存脱敏运行证据。
5. 交付：全部回归、独立审查、文档校准、源码包解压验收、提交、推送并核对 SHA。

## 接口约定

`providers.telemetry.ProviderAttempt` 为 dataclass：attempt、status（running/completed/failed）、elapsed_ms、detail（不含密钥）。`attempt_scope(callback)` 为 context manager；`emit_attempt(event)` 无 observer 时无副作用。

ExecutionEvent 新增 `phase: Literal["node", "provider"] = "node"`，保持旧构造兼容。CLI 通过 Workflow(provider, root=..., on_event=callback) 显示阶段，不直接访问仓储内部。

真实外部测试依赖用户服务。不得将本地协议服务器或 Mock 验收称为外部模型实测；服务不可用时明确记录阻塞原因，同时完成其余交付。
