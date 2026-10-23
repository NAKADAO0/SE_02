"use strict";
const $ = id => document.getElementById(id);
const labels = {pending:"等待执行",running:"协作中",succeeded:"审查通过",failed:"执行失败",needs_attention:"需要人工处理",completed:"已完成",skipped:"已跳过"};
const roles = {code:"编码 Agent",coder:"编码 Agent",coding:"编码 Agent",review:"审查 Agent",repair:"修复 Agent",fix:"修复 Agent"};
function timelineRole(node) {
  const review = /^review_(\d+)$/.exec(node);
  if (review) return Number(review[1]) === 0 ? "审查 Agent · 第1次" : `复审 Agent · 第${Number(review[1])}轮`;
  const repair = /^repair_(\d+)$/.exec(node);
  if (repair) return `修复 Agent · 第${Number(repair[1])}轮`;
  return roles[node] || node;
}
const fixedTask = "实现 total(values)，接收数值列表并返回总和；空列表返回 0。";
const examples = {unique:"实现 Python 函数 unique(values)，稳定去重并保留元素首次出现的顺序，空列表返回空列表。",brackets:"实现 Python 函数 is_balanced(text)，检查圆括号、方括号和花括号是否正确匹配，支持嵌套，忽略其他字符，空字符串返回 True。"};
let settings = null, current = null, selectedId = null, selectedTab = "code";
let sequence = 0, historySequence = 0, pollTimer = null, controller = null, submitting = false, toastTimer = null;
let httpDraft = "", chosenVersion = null;
const active = state => state && ["pending","running"].includes(state.status);
function el(tag, className = "", text = "") {const node = document.createElement(tag); node.className = className; node.textContent = text; return node;}
function showError(message) {$("error-banner").textContent = message; $("error-banner").hidden = !message;}
function toast(message) {clearTimeout(toastTimer); $("toast").textContent = message; $("toast").hidden = false; toastTimer = setTimeout(() => $("toast").hidden = true, 3000);}
async function api(path, options = {}) {
  const response = await fetch(path, {cache:"no-store", ...options});
  let data;
  try {data = await response.json();} catch {throw new Error("服务返回了无法读取的数据，请检查本地服务。");}
  if (!response.ok) throw new Error(typeof data.error === "string" ? data.error : `请求失败（${response.status}）`);
  return data;
}
function invalidateSelection() {sequence++; clearTimeout(pollTimer); controller?.abort(); controller = null; submitting = false;}
function closeSidebar() {$("sidebar").classList.remove("visible"); $("sidebar-backdrop").hidden = true; $("sidebar-open").setAttribute("aria-expanded","false");}
function updateControls() {
  const busy = submitting || active(current);
  $("mode").disabled = busy || !settings;
  $("max-repairs").disabled = busy || !settings;
  $("requirement").disabled = busy || !settings;
  $("send-task").disabled = busy || !settings || ($("mode").value === "http" && !settings.live_available);
  $("send-task").textContent = submitting ? "正在创建…" : active(current) ? "协作进行中…" : "开始协作 ↑";
  $("composer").setAttribute("aria-busy",String(Boolean(busy)));
}
function setMode() {
  const mock = $("mode").value === "mock";
  $("requirement").readOnly = mock;
  if (mock) $("requirement").value = fixedTask;
  $("mode-note").textContent = mock ? "离线固定求和样例 · 输入只读 · 演示编码、审查、修复与复审。" : settings?.live_available ? "真实模型 · 点击开始后会调用已配置的服务，可能产生费用。" : "真实模型尚未配置。请在服务端配置模型与 API 密钥后重启，或选择离线固定样例。";
  updateControls();
}
function selectVersion() {const versions = current?.versions || []; return versions.find(v => String(v.version) === String(chosenVersion)) || versions[versions.length - 1];}
function newTask() {
  invalidateSelection(); selectedId = null; current = null; chosenVersion = null; selectedTab = "code";
  $("welcome").hidden = false; $("task-content").hidden = true; $("task-title").textContent = "新建任务";
  $("mode").value = settings?.live_available ? "http" : "mock"; $("requirement").value = httpDraft;
  showError(""); setMode(); renderArtifact(); renderTabSelection(); closeSidebar();
  document.querySelectorAll(".history-item").forEach(button => button.setAttribute("aria-current","false"));
  $("requirement").focus();
}
async function refreshHistory() {
  const own = ++historySequence;
  try {
    const data = await api("/api/runs"); if (own !== historySequence) return;
    $("history").replaceChildren();
    if (!data.runs?.length) $("history").append(el("p","muted","还没有任务，从一个需求开始。"));
    for (const run of data.runs || []) {
      const button = el("button","history-item"); button.type = "button"; button.dataset.runId = run.id;
      button.setAttribute("aria-current",String(run.id === selectedId));
      const detail = el("small"); detail.append(el("span","",labels[run.status] || run.status),el("span","",run.mode === "mock" ? "离线样例" : "真实模型"));
      button.append(el("strong","",run.title || "未命名任务"),detail); button.onclick = () => selectRun(run.id); $("history").append(button);
    }
  } catch (error) {if (own === historySequence) showError(`无法读取任务历史：${error.message}`);}
}
async function selectRun(id) {
  invalidateSelection(); selectedId = id; current = null; chosenVersion = null; const own = sequence;
  closeSidebar(); showError(""); $("task-title").textContent = "正在读取任务…"; updateControls();
  await poll(id, own); refreshHistory();
}
async function poll(id, own) {
  controller = new AbortController();
  try {
    const snapshot = await api(`/api/runs/${encodeURIComponent(id)}`,{signal:controller.signal});
    if (own !== sequence || id !== selectedId) return;
    const previousLatest = current?.versions?.at(-1)?.version;
    const wasLatest = chosenVersion === null || String(chosenVersion) === String(previousLatest);
    current = snapshot;
    if (wasLatest) chosenVersion = snapshot.versions?.at(-1)?.version ?? null;
    showError(""); renderRun();
    if (active(current)) pollTimer = setTimeout(() => poll(id, own), 900);
    else refreshHistory();
  } catch (error) {
    if (own !== sequence || error.name === "AbortError") return;
    showError(`读取任务失败：${error.message} 正在重试；可选择历史任务或新建任务。`);
    pollTimer = setTimeout(() => poll(id, own), 2500);
  }
}
function renderRun() {
  const state = current;
  $("welcome").hidden = true; $("task-content").hidden = false;
  $("task-title").textContent = state.title || "协作任务"; $("run-heading").textContent = state.title || "协作任务";
  $("user-message").textContent = typeof state.task === "string" ? state.task : JSON.stringify(state.task,null,2);
  $("run-status").textContent = labels[state.status] || state.status;
  $("mode").value = state.mode; $("requirement").value = state.mode === "mock" ? fixedTask : (typeof state.task === "string" ? state.task : "");
  setMode();
  const timeline = $("agent-timeline"); timeline.replaceChildren();
  const stages = [];
  for (const event of state.events || []) {
    if (event.phase === "provider") continue;
    const key = `${event.node}:${event.attempt ?? 1}`;
    let stage = stages.find(item => item.key === key);
    if (!stage) {stage = {key,...event}; stages.push(stage);} else Object.assign(stage,event);
  }
  for (const stage of stages) {
    const card = el("article","agent-card"), info = el("div","agent-info"), title = el("div","agent-title");
    title.append(el("strong","",timelineRole(stage.node)),el("span","",labels[stage.status] || stage.status));
    info.append(title,el("div","agent-description",stage.detail || (stage.status === "running" ? "正在处理任务…" : `第 ${stage.attempt ?? 1} 次 · ${stage.elapsed_ms == null ? "已记录执行状态" : `${Math.round(stage.elapsed_ms)} ms`}`)));
    card.append(el("div","agent-icon",["completed","succeeded"].includes(stage.status) ? "✓" : "·"),info); timeline.append(card);
  }
  if (!stages.length) timeline.append(el("p","muted","任务已接收，等待 Agent 开始协作…"));
  const result = $("result-message"); result.replaceChildren();
  const summary = state.status === "succeeded" ? "✓ 审查已通过，可下载最终代码。" : state.status === "needs_attention" ? "已达到修复上限，请查看审查意见并人工处理。" : state.status === "failed" ? state.error || "任务执行失败，请查看日志。" : "Agent 正在协作，代码和审查结果将持续更新。";
  result.append(el("div","",summary),el("small","",`修复 ${state.repair_count ?? 0} 次 · ${state.versions?.length ?? 0} 个代码版本 · 代码未自动执行`));
  renderArtifact();
}
function renderTabSelection() {
  document.querySelectorAll("[data-tab]").forEach(button => {const selected = button.dataset.tab === selectedTab; button.setAttribute("aria-selected",String(selected)); button.tabIndex = selected ? 0 : -1;});
  $("artifact-content").setAttribute("aria-labelledby",`tab-${selectedTab}`);
}
function renderArtifact() {
  const target = $("artifact-content"), versions = current?.versions || [], version = selectVersion();
  $("version-select").replaceChildren();
  if (!versions.length) $("version-select").append(el("option","","暂无版本"));
  for (const item of versions) {const option = el("option","",`版本 ${item.version}${item === versions.at(-1) ? " · 最新" : ""}`); option.value = String(item.version); $("version-select").append(option);}
  if (version) $("version-select").value = String(version.version);
  $("version-select").disabled = !versions.length;
  $("copy-code").disabled = !version?.source;
  $("download-code").disabled = !versions.length || current?.status !== "succeeded";
  target.replaceChildren();
  if (!current) {const empty = el("div","artifact-empty"); empty.append(el("div","","〈/〉"),el("h3","","代码将在这里呈现"),el("p","","查看每次编码与修复的版本，\n以及 Agent 的审查意见。"),el("pre","","# your next idea\n# starts here.")); target.append(empty); return;}
  if (selectedTab === "code") {
    if (!version) {target.append(el("div","tab-empty","等待编码 Agent 生成初始版本…")); return;}
    const view = el("div","code-view"); String(version.source).split("\n").forEach((line,index) => {const row = el("div","code-line"); row.append(el("span","line-number",String(index+1).padStart(2,"0")),el("span","line-content",line || " ")); view.append(row);}); target.append(view);
  } else if (selectedTab === "diff") {
    if (!current.diff) {target.append(el("div","tab-empty","首版与最新版暂无差异。\n修复后的改动将在这里显示。")); return;}
    const view = el("div","diff-view"); String(current.diff).split("\n").forEach(line => view.append(el("div",`diff-line ${/^(---|\+\+\+|@@)/.test(line) ? "meta" : line.startsWith("+") ? "addition" : line.startsWith("-") ? "deletion" : ""}`,line || " "))); target.append(view);
  } else if (selectedTab === "review") {
    const reports = current.reviews?.length ? current.reviews : current.review ? [current.review] : [];
    if (!reports.length) target.append(el("div","tab-empty","等待审查 Agent 给出意见…"));
    for (const report of reports) {const card = el("article","review-card"); card.append(el("h3","",`版本 ${report.artifact_version ?? "—"} · ${report.verdict === "pass" ? "审查通过" : "需要修复"}`),el("div","",report.summary || "")); for (const issue of report.issues || []) {const row = el("div","review-issue"); row.append(el("strong","",issue.severity || "审查意见"),el("p","",issue.description || ""),el("div","",issue.suggestion || "")); card.append(row);} target.append(card);}
  } else {
    if (!current.events?.length) target.append(el("div","tab-empty","暂时没有执行日志。"));
    for (const event of current.events || []) {const row = el("article","log-row"); row.append(el("time","",event.created_at || ""),el("p","",`${event.phase === "provider" ? "模型请求" : "工作流节点"} · ${event.node} · ${labels[event.status] || event.status} · 第 ${event.attempt ?? 1} 次`)); if (event.detail) row.append(el("p","",event.detail)); target.append(row);}
  }
}
$("composer").onsubmit = async event => {
  event.preventDefault(); if (submitting || active(current) || !settings) return;
  const mode = $("mode").value, task = mode === "mock" ? fixedTask : $("requirement").value.trim();
  if (mode === "http" && !settings.live_available) {showError("真实模型尚未配置，请选择离线固定样例。"); return;}
  if (!task) {showError("请先描述代码需求。"); $("requirement").focus(); return;}
  if (mode === "http") httpDraft = task;
  const own = sequence; submitting = true; updateControls(); showError("");
  try {
    const data = await api("/api/runs",{method:"POST",headers:{"Content-Type":"application/json","X-SE02-Request":"1"},body:JSON.stringify({task,mode,scenario:"repair_pass",max_repairs:Number($("max-repairs").value)})});
    if (own === sequence) await selectRun(data.id); else refreshHistory();
  } catch (error) {if (own === sequence) {submitting = false; updateControls(); showError(error.message);}}
};
$("new-task").onclick = newTask; $("refresh-history").onclick = refreshHistory;
$("requirement").oninput = () => {if ($("mode").value === "http") httpDraft = $("requirement").value;};
$("mode").onchange = () => {if ($("mode").value === "http") $("requirement").value = httpDraft; setMode();};
document.querySelectorAll("[data-example]").forEach(button => button.onclick = () => {
  if (active(current) || submitting) return;
  const example = button.dataset.example; $("mode").value = example === "demo" ? "mock" : "http";
  if (example !== "demo") {httpDraft = examples[example]; $("requirement").value = httpDraft;}
  setMode(); $("requirement").focus();
});
document.querySelectorAll("[data-tab]").forEach(button => {
  button.onclick = () => {selectedTab = button.dataset.tab; renderTabSelection(); renderArtifact();};
  button.onkeydown = event => {if (!["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return; event.preventDefault(); const tabs = [...document.querySelectorAll("[data-tab]")], index = tabs.indexOf(button); const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length-1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length; tabs[next].click(); tabs[next].focus();};
});
$("version-select").onchange = () => {chosenVersion = $("version-select").value; renderArtifact();};
$("copy-code").onclick = async () => {try {await navigator.clipboard.writeText(selectVersion().source); toast("代码已复制");} catch {toast("无法访问剪贴板，请选择代码复制或下载最终代码。");}};
$("download-code").onclick = () => {if (current?.status !== "succeeded") return; const link = el("a"); link.href = `/api/runs/${encodeURIComponent(current.id)}/download`; link.download = "final_code.py"; document.body.append(link); link.click(); link.remove();};
$("sidebar-open").onclick = () => {$("sidebar").classList.add("visible"); $("sidebar-backdrop").hidden = false; $("sidebar-open").setAttribute("aria-expanded","true"); $("sidebar-close").focus();};
$("sidebar-close").onclick = () => {closeSidebar(); $("sidebar-open").focus();}; $("sidebar-backdrop").onclick = closeSidebar;
function syncInspector() {const shown = innerWidth <= 760 ? document.body.classList.contains("mobile-inspector") : !document.body.classList.contains("hide-inspector"); $("toggle-inspector").setAttribute("aria-expanded",String(shown));}
$("toggle-inspector").onclick = () => {document.body.classList.toggle(innerWidth <= 760 ? "mobile-inspector" : "hide-inspector"); syncInspector();};
window.addEventListener("resize",syncInspector);
document.addEventListener("keydown",event => {if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {event.preventDefault(); if (!$("send-task").disabled) $("composer").requestSubmit();} if (event.key === "Escape") {closeSidebar(); document.body.classList.remove("mobile-inspector"); syncInspector();}});
async function init() {
  updateControls(); syncInspector(); renderTabSelection();
  try {settings = await api("/api/config"); $("connection-text").textContent = settings.live_available ? "真实模型已配置" : "离线演示可用"; $("model-label").textContent = `SE_02 · ${settings.live_available ? settings.model : "离线固定样例"}`; $("max-repairs").value = String(settings.max_repairs ?? 2); newTask(); await refreshHistory();} catch (error) {showError(`无法连接本地服务：${error.message} 请刷新页面重试。`); $("connection-text").textContent = "本地服务连接失败";}
}
init();
