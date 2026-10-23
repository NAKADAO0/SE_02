# 文件上传工作区验证记录

日期：2026-10-23；版本：0.3.1。

## 实际模型与浏览器验收

Edge / Playwright 连接本地 Web 服务，通过文件选择器上传 test_total.py。后台使用与 CLI 相同的 config.example.toml、load_config、HttpProvider 和 SE02_API_KEY，API=https://api.deepseek.com，model=deepseek-flash。

- 原始文件逐字符保留为 v1；工作流从 upload → review_0 开始，未调用编码模型生成替代文件。
- 实际模型完成首次审查、一次修复和复审，终态 succeeded，最新报告 pass，共2个代码版本。
- 桌面1500×980与手机390×844均正常，无JavaScript异常和横向溢出；版本、差异、审查和日志标签可切换。
- 页面不提供需求输入、Mock或API切换；缺密钥时禁止上传提交，模型配置只由服务端读取。
- 截图来自此次真实模型运行；证据摘要见 release/upload-http-acceptance.json。

## 自动化回归

新增上传测试覆盖原文与CRLF保留、不调用coder、格式/大小/空文件/路径拒绝、重启历史及CLI配置一致性。完整测试数量与源码解压验证见 release/package-verification.json。

上传文件仅供模型静态审查，不在本机执行代码，不运行pytest。succeeded指当前代码版本通过模型审查。
