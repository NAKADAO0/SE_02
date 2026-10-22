# 脱敏真实验收证据

这些目录来自本项目公开样例任务的真实 DeepSeek V4.1 Flash 调用，不是本地 HTTP fixture。模型配置使用官方别名 deepseek-flash；当前证据中的生成代码均未自动执行。

- real-sum、real-brackets、real-unique：真实编码和审查，均成功。
- real-repair：明确的缺陷初稿由 KnownDefectCoder fixture 提供，后续审查、修复和复审调用真实服务，成功修复空列表返回 None 的问题。
- real-cli.json：使用 CLI 读取 sum.txt 和 config.example.toml 调用真实服务，退出 0。
- real-model-smoke.json：最初的接口冒烟结果。

目录保留 task、state、代码元数据、审查、消息、节点与 HTTP 尝试事件，acceptance.json 说明来源和结果。没有复制环境变量、HTTP 鉴权头、用户密钥或私密用户文件。重复执行例行测试不会调用这些外部服务。

显式复测真实服务可使用 examples/live_acceptance.py，需要 SE02_BASE_URL、SE02_MODEL、SE02_API_KEY，将消耗服务额度。详见 docs/FINAL_ACCEPTANCE.md。
