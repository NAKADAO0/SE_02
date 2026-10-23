# 本地工作区 UI

在 SE_02 目录安装后运行：

```powershell
python -m se02.web --port 8763 --config config.example.toml
```

打开 `http://127.0.0.1:8763`。仅绑定本机回环地址，需要 Python 3.11+，无需第三方运行依赖。终端 Ctrl+C 停止服务。

网页只接受待检查的 Python 文件：UTF-8、`.py`、非空、最大32 KiB。选择文件后上传并审查；原文直接保存为v1，再交给审查Agent，需要时最多修复两轮并复审。前端不再提供需求生成或Mock选择。上传文件不在本机执行；本系统提供模型静态审查，不执行pytest。

网页和CLI使用同一个load_config及HttpProvider，配置文件同为config.example.toml：base_url=https://api.deepseek.com，model=deepseek-flash；环境变量覆盖规则、SE02_API_KEY、超时和重试均与CLI相同。密钥只保留在服务端。缺失密钥会禁用提交，环境改变后需重启。

单个工作流在后台执行，并发新任务返回409。文件名只作展示，不作为保存路径；保留原文件内容及修复后的版本，可比较差异、查看报告、下载通过审查的代码。

历史只来自 `runs/web/ui_metadata` 登记的任务，工作流产物位于 `runs/web/artifacts`。不会扫描其他CLI运行或私密目录。进度事件先由核心工作流落盘，浏览器再轮询读取真实日志、源码、审查与差异。历史不支持恢复执行；重启前未完成的任务标记失败。损坏的元数据忽略，损坏产物显示错误并禁止下载。只有成功且产物和对应审查完整的运行可下载Python文件。

## HTTP 接口

所有错误为 `{error: message}`。写请求必须同源、`Content-Type: application/json` 和 `X-SE02-Request: 1`，正文不超过256KiB（容纳文件的JSON转义开销）；未知字段拒绝。Host 必须是当前端口的127.0.0.1或localhost，POST Origin必须与Host完全相同。任务ID仅32位小写十六进制。

- `GET /api/config`：model、live_available、max_repairs、version。
- `GET /api/runs`：`{runs:[{id,title,status,mode,created_at,repair_count,filename}]}`，最近优先。网页只显示filename存在的文件上传记录。
- `POST /api/runs`：网页发送 `{filename, source, mode:"http", max_repairs}`，返回202 `{id}`。filename为不含路径的.py文件名，source为UTF-8文本，模式只能http。为了兼容已有自动化，服务内部仍保留旧task/mode/scenario协议，网页不使用它。
- `GET /api/runs/<id>`：id、title、task、mode、scenario、status、created_at、repair_count、current_node、events、versions、review、reviews、diff、error、result。
- `GET /api/runs/<id>/download`：仅完整成功终态，返回附件Python源码；其他状态409。

versions为真实落盘的`[{version,source}]`；events含phase=node/provider；reviews含真实ReviewReport；review是匹配最新版代码的最新报告；diff为首版与最新版的unified diff。result在本次完成时包含status、final_code_ref、final_review_ref、persistence_errors，运行中及历史恢复可为null。不会返回绝对运行路径、原始服务响应或密钥。错误详情使用安全固定文本，诊断可结合服务端本地工作流产物查看。

测试接口可注入`JobManager(root=临时目录, provider_factory=lambda: provider)`，通过`make_server('127.0.0.1', 0, manager)`启动随机端口；完成后关闭HTTP服务及manager。生产入口固定使用runs/web专用目录。
