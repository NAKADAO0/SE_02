# 运行截图来源

日期：2026-10-23（北京时间）。

`examples/runtime_report.py` 实际启动 `python -m se02 demo --scenario repair_pass`，合并捕获该进程的 stdout/stderr，然后读取它保存的 state、events、最终代码和报告生成只读 HTML。输出目录为 runs/readme-preview，不提交 Git。

- runtime-overview.png：同一次运行的节点、状态、修复次数、代码与运行 ID。
- runtime-cli.png：该进程原始输出、结果路径、源码和审查判定。

PNG 由本机浏览器渲染上述报告后直接截图，未经图片修改，不包含 API 密钥。这是 Mock 演示，不是实时交互式 Web 客户端，也不表示本次再次调用了真实模型。此前真实验收单独保存在 release 目录。

截图中的运行 ID 与本地报告对应，重新执行报告脚本会创建新运行 ID；README 截图保持本次已检查的版本。截图生成需要浏览器，项目运行本身不依赖 Playwright 或浏览器。
