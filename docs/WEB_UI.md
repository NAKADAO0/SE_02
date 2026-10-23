# 本地工作区 UI

在 SE_02 目录安装后运行：

```powershell
python -m se02.web --port 8763 --config config.example.toml
```

打开 `http://127.0.0.1:8763`。仅绑定本机回环地址，需要 Python 3.11+，无需第三方运行依赖。终端 Ctrl+C 停止服务。

没有 SE02_API_KEY 时可运行离线 Mock，明确显示真实模型不可用；不会将真实请求降级到 Mock。真实模式需要启动进程已有 base_url、model 和环境密钥配置。浏览器不接收或保存密钥，也不提供修改模型配置的接口。服务启动后更改环境需重启。

Mock 始终使用固定求和任务，场景为 direct_pass、repair_pass、always_reject、call_failure。真实模式接受非空、最多10000字符的需求。修复预算0到2，单个工作流在后台执行，并发新任务返回409。生成代码只展示和保存，不执行。

历史只来自 `runs/web/ui_metadata` 登记的任务，工作流产物位于 `runs/web/artifacts`。不会扫描其他CLI运行或私密目录。进度事件先由核心工作流落盘，浏览器再轮询读取真实日志、源码、审查与差异。历史不支持恢复执行；重启前未完成的任务标记失败。损坏的元数据忽略，损坏产物显示错误并禁止下载。只有成功且产物和对应审查完整的运行可下载Python文件。

## HTTP 接口

所有错误为 `{error: message}`。写请求必须同源、`Content-Type: application/json` 和 `X-SE02-Request: 1`，正文不超过64KiB；未知字段拒绝。Host 必须是当前端口的127.0.0.1或localhost，POST Origin必须与Host完全相同。任务ID仅32位小写十六进制。

- `GET /api/config`：model、live_available、max_repairs、version。
- `GET /api/runs`：`{runs:[{id,title,status,mode,created_at,repair_count}]}`，最近优先。
- `POST /api/runs`：接受task、mode(mock/http)、scenario、max_repairs，返回202 `{id}`。
- `GET /api/runs/<id>`：id、title、task、mode、scenario、status、created_at、repair_count、current_node、events、versions、review、reviews、diff、error、result。
- `GET /api/runs/<id>/download`：仅完整成功终态，返回附件Python源码；其他状态409。

versions为真实落盘的`[{version,source}]`；events含phase=node/provider；reviews含真实ReviewReport；review是匹配最新版代码的最新报告；diff为首版与最新版的unified diff。result在本次完成时包含status、final_code_ref、final_review_ref、persistence_errors，运行中及历史恢复可为null。不会返回绝对运行路径、原始服务响应或密钥。错误详情使用安全固定文本，诊断可结合服务端本地工作流产物查看。

测试接口可注入`JobManager(root=临时目录, provider_factory=lambda: provider)`，通过`make_server('127.0.0.1', 0, manager)`启动随机端口；完成后关闭HTTP服务及manager。生产入口固定使用runs/web专用目录。
