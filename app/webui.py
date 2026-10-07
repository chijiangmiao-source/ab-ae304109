"""单文件页面（内联 CSS/JS，无外部依赖）。"""

from __future__ import annotations

PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>受限表达式等价复核</title>
<style>
  :root {
    --bg: #f5f6f8; --panel: #ffffff; --ink: #1f2430; --muted: #6b7280;
    --line: #d9dde3; --accent: #2456d6;
    --ok: #117a37; --okbg: #e7f6ec;
    --no: #b3261e; --nobg: #fdecea;
    --warn: #92590a; --warnbg: #fdf3df;
    --bad: #b3261e; --badbg: #fdecea;
  }
  * { box-sizing: border-box; }
  body { margin:0; font: 14px/1.55 -apple-system, "Segoe UI", "PingFang SC",
         "Microsoft YaHei", sans-serif; background:var(--bg); color:var(--ink); }
  header { padding:20px 28px 12px; }
  header h1 { font-size:19px; margin:0 0 4px; }
  header p { margin:0; color:var(--muted); font-size:13px; }
  main { display:grid; grid-template-columns: 380px 1fr; gap:18px; padding:12px 28px 32px; }
  @media (max-width: 900px){ main{grid-template-columns:1fr;} }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:10px;
           padding:16px 18px; }
  label { display:block; font-weight:600; margin:10px 0 4px; }
  input[type=text], textarea { width:100%; padding:8px 10px; border:1px solid var(--line);
           border-radius:7px; font:13px ui-monospace, Menlo, Consolas, monospace; }
  textarea { resize:vertical; min-height:150px; }
  .row { display:flex; gap:10px; }
  .row > div { flex:1; }
  .hint { color:var(--muted); font-size:12px; margin-top:3px; }
  button { margin-top:14px; background:var(--accent); color:#fff; border:0;
           border-radius:7px; padding:9px 18px; font-size:14px; cursor:pointer; }
  button.secondary { background:#eef1f6; color:var(--ink); border:1px solid var(--line); }
  button:hover { filter:brightness(1.05); }
  h2 { font-size:15px; margin:2px 0 10px; }
  .verdict { border-radius:9px; padding:12px 14px; font-weight:700; font-size:15px;
             display:flex; align-items:center; gap:10px; margin-bottom:14px; }
  .verdict small { font-weight:400; }
  .v-equivalent { background:var(--okbg); color:var(--ok); border:1px solid #bfe3cb; }
  .v-inequivalent { background:var(--nobg); color:var(--no); border:1px solid #f3c6c2; }
  .v-incomplete { background:var(--warnbg); color:var(--warn); border:1px solid #f0dcae; }
  .v-invalid { background:var(--badbg); color:var(--bad); border:1px solid #f3c6c2; }
  .errors li { margin-bottom:4px; }
  .summary { font-size:13px; }
  .summary table { border-collapse:collapse; width:100%; margin-top:6px; }
  .summary td, .summary th { border:1px solid var(--line); padding:5px 8px;
             text-align:left; vertical-align:top; }
  .summary th { background:#f0f2f6; font-weight:600; }
  code, .mono { font-family:ui-monospace, Menlo, Consolas, monospace; }
  .step { border:1px solid var(--line); border-radius:8px; padding:9px 12px;
          margin:8px 0; background:#fbfcfe; }
  .step .head { font-weight:600; margin-bottom:3px; }
  .step .trans { font-family:ui-monospace, Menlo, Consolas, monospace; font-size:13px; }
  .step .meta { color:var(--muted); font-size:12px; margin-top:4px; }
  .tag { display:inline-block; border-radius:5px; padding:0 7px; font-size:11px;
         font-weight:700; margin-right:6px; }
  .tag-rule { background:#e5edff; color:#2456d6; }
  .tag-cong { background:#efeaf9; color:#6a3fb5; }
  .classes { margin-top:6px; }
  .class-box { border:1px solid var(--line); border-radius:7px; padding:7px 10px;
               margin:6px 0; font-family:ui-monospace, Menlo, Consolas, monospace;
               font-size:13px; background:#fbfcfe; overflow-x:auto; }
  .basis { margin-top:4px; }
  .basis-item { margin:4px 0 4px 10px; }
  .substeps { margin:5px 0 2px 14px; padding-left:10px;
              border-left:2px solid #d9dde3; }
  .substep { margin:4px 0; font-size:12px; }
  .substep .trans { font-family:ui-monospace, Menlo, Consolas, monospace; }
  .substep .meta { color:var(--muted); font-size:11px; }
  .muted { color:var(--muted); font-size:12px; }
  .fp { letter-spacing:.5px; }
</style>
</head>
<body>
<header>
  <h1>受限代数表达式等价复核</h1>
  <p>仅依据已批准的等式规则做饱和重写与同余闭包；规则饱和后才作等价判断。
     变量以 <code>?</code> 前缀书写（如 <code>?x</code>），其余标识符为具名常量。</p>
</header>
<main>
  <section class="panel">
    <h2>复核录入</h2>
    <label for="left">左式</label>
    <input id="left" type="text" placeholder="例如 add(a, b)">
    <label for="right">右式</label>
    <input id="right" type="text" placeholder="例如 add(b, a)">
    <label for="rules">等式规则（每行一条，至多 20 条）</label>
    <textarea id="rules" spellcheck="false"
      placeholder="add(?x, ?y) = add(?y, ?x)"></textarea>
    <div class="hint">右侧不得引入左侧未出现的变量；函数调用限一元或二元。</div>
    <div class="row">
      <div>
        <label for="nlimit">推导项节点上限</label>
        <input id="nlimit" type="text" value="80">
      </div>
      <div>
        <label for="alimit">规则应用次数上限</label>
        <input id="alimit" type="text" value="5000">
      </div>
    </div>
    <div class="row">
      <button id="submit">提交复核</button>
      <button id="clear" class="secondary">清空结论</button>
    </div>
  </section>

  <section class="panel" id="result">
    <h2>复核结论</h2>
    <p class="muted" id="placeholder">尚未提交。提交后此处展示规范摘要与等价 / 不等价 / 未完成 / 无效结论。</p>
    <div id="content" hidden></div>
  </section>
</main>

<script>
"use strict";
const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

function verdictHtml(status) {
  const map = {
    equivalent: ["v-equivalent", "等价", "两式在规则饱和后同属一个等价类"],
    inequivalent: ["v-inequivalent", "不等价", "已饱和，两式分属不同等价类"],
    incomplete: ["v-incomplete", "未完成", "达到资源上限前尚未饱和，不能判定等价"],
    invalid: ["v-invalid", "无效", "录入不合法，旧结论已清除"],
  };
  const [cls, title, sub] = map[status] || ["v-invalid", status, ""];
  return `<div class="verdict ${cls}"><span>${title}</span><small>${sub}</small></div>`;
}

function summaryHtml(s) {
  const rows = [];
  rows.push(`<tr><th>左式</th><td class="mono">${esc(s.left)}</td></tr>`);
  rows.push(`<tr><th>右式</th><td class="mono">${esc(s.right)}</td></tr>`);
  rows.push(`<tr><th>有效规则</th><td>${s.rule_count} / ${s.max_rules}</td></tr>`);
  (s.rules || []).forEach((r, i) =>
    rows.push(`<tr><th>规则 ${i+1}</th><td class="mono">${esc(r)}</td></tr>`));
  rows.push(`<tr><th>资源上限</th><td>推导项 ${esc(s.node_limit)} 节点 ·
      规则应用 ${esc(s.application_limit)} 次（声明节点上限 ${s.spec_node_limit}）</td></tr>`);
  return `<div class="summary"><table>${rows.join("")}</table></div>`;
}

function subStepsHtml(subs) {
  if (!subs || !subs.length) return "";
  return `<div class="substeps">` + subs.map(st => {
    const d = st.detail || {};
    if (st.kind === "rule") {
      const binds = (d.bindings || []).map(b => `${esc(b.var)} ↦ ${esc(b.term)}`).join("，") || "（无变量）";
      return `<div class="substep">
        <span class="tag tag-rule">规则 ${d.rule_index}</span>
        <span class="trans">${esc(st.before)} ⟹ ${esc(st.after)}</span>
        <div class="meta">实例 <code>${esc(d.rule_text)}</code>（${esc(d.applied_direction)}，${esc(d.path)}）；
        绑定 ${binds}</div></div>`;
    }
    return `<div class="substep"><span class="tag tag-cong">同余</span>
      <span class="trans">${esc(st.before)} ⟹ ${esc(st.after)}</span>${subStepsHtml(
        (d.child_basis||[]).flatMap(cb => cb.derivation || []))}</div>`;
  }).join("") + `</div>`;
}

function stepHtml(st, i) {
  const d = st.detail || {};
  const tag = st.kind === "rule"
    ? `<span class="tag tag-rule">规则 ${d.rule_index}</span>`
    : `<span class="tag tag-cong">同余</span>`;
  let meta = "";
  if (st.kind === "rule") {
    const binds = (d.bindings || []).map(b => `${esc(b.var)} ↦ ${esc(b.term)}`).join("，") || "（无变量）";
    meta = `<div>实例：<code>${esc(d.rule_text)}</code>（${esc(d.applied_direction)}，${esc(d.path)}）</div>
            <div>绑定：${binds}</div>
            <div> redex：<code>${esc(d.redex_before)}</code> ⇒ <code>${esc(d.redex_after)}</code></div>`;
  } else {
    const basis = (d.child_basis || [])
      .map(b => `<div class="basis-item">第 ${b.position} 个参数
        <code>${esc(b.left)}</code> ≡ <code>${esc(b.right)}</code>
        ${subStepsHtml(b.derivation)}</div>`)
      .join("") || "参数完全相同";
    meta = `<div>${esc(d.path)}</div><div class="basis">同余依据：${basis}</div>`;
  }
  return `<div class="step">
    <div class="head">第 ${i+1} 步 ${tag}</div>
    <div class="trans">${esc(st.before)} &nbsp;⟹&nbsp; ${esc(st.after)}</div>
    <div class="meta">${meta}</div>
  </div>`;
}

function classesHtml(classes, fp) {
  return `<div class="classes">
    <div class="muted">饱和等价类稳定摘要 · 指纹 <span class="fp mono">${esc(fp)}</span>
      （按规范顺序排序，重复运行哈希一致）</div>
    ${classes.map(c => `<div class="class-box">${c.members.map(esc).join(" &nbsp;≡&nbsp; ")}</div>`).join("")}
  </div>`;
}

function render(data) {
  const box = $("content");
  $("placeholder").hidden = true;
  box.hidden = false;
  let html = verdictHtml(data.status) + summaryHtml(data.summary || {});

  if (data.status === "invalid") {
    html += `<h2>错误明细</h2><ul class="errors">` +
      (data.errors || []).map(e => {
        const where = e.scope === "rule" && e.index !== undefined
          ? `规则 ${e.index+1}` : ({left:"左式",right:"右式",rules:"规则集",limits:"上限",request:"请求"}[e.scope] || e.scope);
        return `<li><b>${esc(where)}</b>：${esc(e.message)}</li>`;
      }).join("") + `</ul>`;
    html += `<p class="muted">无效请求不产生任何等价类或证据，页面上此前的结论已清除。</p>`;
  } else if (data.status === "equivalent") {
    html += `<h2>逐步推导（左式 ⟹ 右式）</h2>` +
      (data.derivation || []).map(stepHtml).join("");
    html += classesHtml(data.classes || [], data.fingerprint);
  } else if (data.status === "inequivalent") {
    html += `<p>两式分属下列不同等价类；旧的逐步证据已清除。</p>`;
    html += classesHtml(data.classes || [], data.fingerprint);
  } else if (data.status === "incomplete") {
    html += `<p>${esc(data.message)}</p>
      <p class="muted">原因：${esc(data.reason)}；已入林推导项 ${data.nodes} 个、
      规则应用 ${data.applications} 次。未饱和时不允许作等价判断。</p>`;
  }
  html += `<p class="muted">统计：推导项 ${data.nodes ?? "—"} 个节点 ·
      规则应用 ${data.applications ?? "—"} 次</p>`;
  box.innerHTML = html;
}

function clearResult() {
  $("content").innerHTML = "";
  $("content").hidden = true;
  $("placeholder").hidden = false;
}

$("clear").addEventListener("click", clearResult);
$("submit").addEventListener("click", async () => {
  const payload = {
    left: $("left").value,
    right: $("right").value,
    rules: $("rules").value,
    node_limit: Number($("nlimit").value),
    application_limit: Number($("alimit").value),
  };
  try {
    const resp = await fetch("/api/verify", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    render(await resp.json());
  } catch (e) {
    // 网络/服务异常同样视为旧结论不再可信
    render({status: "invalid",
      errors: [{scope:"request", message: "无法联系验证服务：" + e}],
      summary: {left: payload.left, right: payload.right, rules: [],
                rule_count:0, max_rules:20,
                node_limit: payload.node_limit,
                application_limit: payload.application_limit,
                spec_node_limit: 80}});
  }
});
</script>
</body>
</html>
"""
