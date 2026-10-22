# CLI 使用说明

安装：`python -m pip install -e .`。模块入口 `python -m se02` 与 `se02` 等价，需要 Python 3.11+。

离线固定求和样例：`python -m se02 demo --scenario repair_pass`。四种场景为 direct_pass、repair_pass、always_reject、call_failure；Mock 仅演示固定求和样例。

将任务描述保存为 UTF-8 文本，然后运行：

```powershell
$credential = Read-Host 'DeepSeek API key' -AsSecureString
$env:SE02_API_KEY = [System.Net.NetworkCredential]::new('', $credential).Password
python -m se02 run --task examples/tasks/sum.txt --config config.example.toml
```

示例配置指定 DeepSeek 的 `https://api.deepseek.com` 与 `deepseek-flash`。run 默认 http，必须配置 base_url、model 和环境密钥；不会回退 Mock。离线运行任意输入需显式 `--provider mock`，输出仍是固定样例。

配置优先级：命令行 > SE02_ 环境变量 > `--config` TOML > 默认。支持 provider、base_url、model、timeout、max_retries、retry_delay、max_repairs、output_dir；命令行字段用连字符。默认超时60秒、传输重试1次、重试间隔0.5秒、修复2轮、输出runs。环境变量如 SE02_MODEL、SE02_OUTPUT_DIR。密钥只接受 SE02_API_KEY，禁止在配置或命令行提供 api_key；未知配置字段报错。

`--json` 将终态 JSON 写 stdout；实时节点和 HTTP 尝试进度写 stderr，`--quiet` 关闭进度。人类输出包含状态、运行目录、修复次数、最终源码和报告。产物只保存，不执行生成代码。

退出码：成功0、工作流失败1、输入/配置错误2、修复预算耗尽需介入3。run目录保存task、状态、事件、消息、版本化代码及报告；phase=node表示逻辑节点，phase=provider表示HTTP尝试。传输重试次数与修复轮次独立。

运行失败时，人类输出还会在 stderr 逐条显示脱敏的持久化诊断（例如失败快照无法保存）；即使启用 --quiet 也保留这些错误。JSON 输出的 persistence_errors 字段提供相同诊断。
