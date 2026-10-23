# 简洁前端 UI 实现计划

日期：2026-10-23；目录：`E:\python_project\SE\SE_02`。

## 设计基线

参考第二次作业 CodeReviewWorkflow/web/static 的暖白、浅灰、绿色工作区风格：左侧项目与最近任务，中间需求输入和 Agent 时间线，右侧代码/差异/审查/日志。仅复用视觉方向，不复制旧项目身份信息、业务后端或密钥。

保留现有 Workflow、Agent 和 Provider 接口。新增本地 HTTP UI 适配层，后台单任务执行，浏览器轮询实际状态。无需第三方运行依赖，不支持上传初稿、失败恢复或任意文件浏览。

## 接口

- GET /api/config → model、live_available、max_repairs、version。
- GET /api/runs → {runs: [{id,title,status,mode,created_at,repair_count}]}。
- POST /api/runs 接受 task、mode(mock/http)、scenario、max_repairs，返回 202 {id}。
- GET /api/runs/<id> → id、title、task、mode、scenario、status、created_at、repair_count、current_node、events、versions([{version,source}])、review、reviews、diff、error、result。
- GET /api/runs/<id>/download 仅成功终态允许下载最终 Python 代码。
- 错误统一 {error: message}，不可回传密钥、任意路径和原始服务响应。

POST 仅接受同源 JSON，前端附带 X-SE02-Request: 1；服务绑定 127.0.0.1，校验 Host/Origin。密钥只来自服务进程环境，不进入浏览器。Mock 明确使用固定求和任务；真实任务仅在服务端配置完整时运行，不静默降级。

## 任务分工与验证

1. 后端：src/se02/web/*.py、test_web.py，先写 API/状态/安全测试，再实现管理器、后台执行、持久化历史、静态资源和 module 启动入口。
2. 前端：src/se02/web/static/{index.html,styles.css,app.js}，实现参考布局、空态、实时状态、产物、复制/下载和响应式布局；模型文本仅 textContent。
3. 集成：加入包内静态资源和源码白名单；Playwright 实际点击 Mock 流程、切换 tabs、历史、新建任务、下载、错误和窄屏检查；后端全套回归。
4. 交付：启动本地 UI，记录真实截图，更新 README/使用文档和源码包；审查后提交推送。

启动方式：`python -m se02.web --port 8763 --config config.example.toml`。未配置密钥时默认可用离线演示，明确显示真实模型未配置。
