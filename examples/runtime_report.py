"""Run the actual CLI and create a read-only HTML report; no web app or model call."""

import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "runs/readme-preview"
    output.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith("SE02_")}
    env["PYTHONPATH"] = str(root / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable, "-m", "se02", "demo", "--scenario", "repair_pass",
               "--output-dir", str(output / "runs")]
    completed = subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError("CLI demo failed; report was not generated")
    match = re.search(r"^Run directory: (.+)$", completed.stdout, re.MULTILINE)
    if match is None:
        raise RuntimeError("CLI did not report its artifact directory")
    run_dir = Path(match.group(1).strip())
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    nodes = [event for event in events if event["phase"] == "node" and event["status"] == "completed"]
    code_ref = next(ref for ref in reversed(state["artifact_refs"]) if ref.endswith(".py"))
    review_ref = next(ref for ref in reversed(state["artifact_refs"]) if ref.startswith("reviews/"))
    source = (run_dir / code_ref).read_text(encoding="utf-8")
    review = json.loads((run_dir / review_ref).read_text(encoding="utf-8"))
    rows = "".join(f'<div class="step"><span class="check">✓</span><b>{html.escape(e["node"])}</b>'
                   f'<span>v{e["artifact_version"]}</span><small>completed</small></div>' for e in nodes)
    captured = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S UTC+08:00")
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>SE_02 · 实际 CLI 运行报告</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f5fa;color:#17213b;font:16px "Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:1160px;margin:auto;padding:40px 32px}header{display:flex;align-items:center;justify-content:space-between}
.eyebrow{font-size:13px;letter-spacing:2px;color:#64748b}h1{font-size:34px;margin:8px 0}p{color:#64748b;line-height:1.8}
.badge{background:#ddf6eb;color:#087a54;padding:10px 16px;border-radius:24px}.notice{background:#e8efff;border-left:4px solid #4664dc;padding:14px 18px;margin:24px 0;color:#344679}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.card{background:white;border:1px solid #e0e5ef;border-radius:12px;padding:22px}
.number{font-size:28px;font-weight:700;margin-top:8px}.label,small{color:#64748b;font-size:13px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:20px 0}h2{font-size:18px;margin:0 0 18px}
.step{display:grid;grid-template-columns:28px 1fr 40px 90px;align-items:center;gap:8px;margin:10px 0;padding:11px 0;border-bottom:1px solid #edf0f6}.check{color:#138b67;font-size:21px}
pre{background:#10182b;color:#d8e5f8;padding:22px;border-radius:10px;overflow:auto;white-space:pre-wrap;word-break:break-word;font:14px/1.7 Consolas,"Microsoft YaHei",monospace;margin:0}
code{font-family:Consolas,monospace}.footer{font-size:12px;color:#7a8498;margin-top:16px}.terminal{margin-top:40px;scroll-margin-top:24px}a{color:#4465d2}nav{margin:12px 0}#terminal pre{font-size:13px;line-height:1.5}
</style><main><header><div><div class="eyebrow">SOFTWARE ENGINEERING · SE_02</div><h1>三 Agent 代码审查工作流</h1><p>实际 CLI 运行报告 · 编码 → 审查 → 修复 → 复审</p></div><span class="badge">__STATUS__</span></header>
<div class="notice">这是本机实际执行的 Mock 演示记录，不是交互式 Web 产品界面。真实模型验收另见 release/ 与文档。</div>
<nav><a href="#overview">运行总览</a>　<a href="#terminal">完整 CLI 输出</a></nav>
<section id="overview"><div class="metrics"><div class="card"><span class="label">运行结果</span><div class="number">__STATUS__</div></div><div class="card"><span class="label">已开始修复轮次 / 上限</span><div class="number">__REPAIRS__ / 2</div></div><div class="card"><span class="label">最新审查判定</span><div class="number">__VERDICT__ · v2</div></div></div>
<div class="grid"><div class="card"><h2>实际完成的节点</h2>__ROWS__</div><div class="card"><h2>最终源码 · __CODE_REF__</h2><pre>__SOURCE__</pre><p>初稿空列表返回 None；审查指出问题，修复后返回 0。</p><span class="label">代码仅保存，未自动执行。</span></div></div>
<div class="card"><h2>结果可追溯</h2><p>run_id：<code>__RUN_ID__</code><br>报告：<code>__REVIEW_REF__</code><br>记录：state.json / events.jsonl / messages.jsonl</p></div></section>
<section id="terminal" class="terminal"><h2>完整 CLI 输出 · 实际进程退出码 0</h2><pre>__TRANSCRIPT__</pre></section>
<div class="footer">运行于 __CAPTURED__ · 此页面只读，刷新不会重新调用模型。重新运行 examples/runtime_report.py 可生成新记录。</div></main></html>'''
    values = {"STATUS": state["status"], "REPAIRS": str(state["repair_count"]), "VERDICT": review["verdict"],
              "ROWS": rows, "CODE_REF": code_ref, "SOURCE": source, "RUN_ID": state["run_id"],
              "REVIEW_REF": review_ref, "TRANSCRIPT": "$ python -m se02 demo --scenario repair_pass\n" + completed.stdout,
              "CAPTURED": captured}
    for key, value in values.items():
        page = page.replace(f"__{key}__", value if key == "ROWS" else html.escape(value))
    (output / "index.html").write_text(page, encoding="utf-8")
    (output / "transcript.txt").write_text(completed.stdout, encoding="utf-8")
    print(output / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
