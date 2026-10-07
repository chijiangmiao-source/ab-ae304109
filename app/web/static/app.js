/* 控制表达式代数重写复核页面逻辑（原生 JS，无依赖）。 */

const resultPanel = document.getElementById("resultPanel");
const summaryEl = document.getElementById("summary");
const verdictEl = document.getElementById("verdict");
const issuesEl = document.getElementById("issues");
const limitEl = document.getElementById("limit");
const proofWrap = document.getElementById("proofWrap");
const proofEl = document.getElementById("proof");
const classesWrap = document.getElementById("classesWrap");
const classesEl = document.getElementById("classes");
const statsEl = document.getElementById("stats");
const requestState = document.getElementById("requestState");

function esc(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

function renderSummary(summary) {
  const rows = [];
  rows.push(`<tr><th>左式</th><td><code>${esc(summary.left)}</code></td></tr>`);
  rows.push(`<tr><th>右式</th><td><code>${esc(summary.right)}</code></td></tr>`);
  rows.push(`<tr><th>规则</th><td>${summary.rule_count} 条（双向应用）</td></tr>`);
  rows.push(
    `<tr><th>资源上限</th><td>单式 ≤ ${summary.max_nodes} 节点 ·
     规则有效应用 ≤ ${summary.max_applications} 次</td></tr>`
  );
  if (summary.rules.length) {
    const ruleBits = summary.rules.map(
      (r) => `<li>${r.index}. <code>${esc(r.text)}</code></li>`
    );
    rows.push(`<tr><th>规则清单</th><td><ol style="margin:0;padding-left:18px">
      ${ruleBits.join("")}</ol></td></tr>`);
  }
  summaryEl.innerHTML = `<table>${rows.join("")}</table>`;
}

function renderProof(proof) {
  if (!proof || !proof.length) {
    proofWrap.hidden = true;
    proofEl.innerHTML = "";
    return;
  }
  proofWrap.hidden = false;

  const renderSteps = (steps, level) => {
    return steps
      .map((step) => {
        const sub = step.by.substitution || {};
        const substStr = Object.keys(sub)
          .map((k) => `${esc(k)} ↦ ${esc(sub[k])}`)
          .join(", ");
        const kindLabel = step.by.kind === "rule" ? "规则实例" : "同余依据";
        const nested = step.premise_proofs
          ? `<ul class="subproof" style="margin:6px 0 0;padding-left:18px">
               ${step.premise_proofs
                 .map(
                   (p) => `<li>参数等价 <span class="expr">${esc(p.from)} ⇒ ${esc(
                     p.to
                   )}</span> 的依据：${renderSteps(p.steps, level + 1)}</li>`
                 )
                 .join("")}
             </ul>`
          : "";
        return `<li style="${level ? "margin-bottom:4px" : ""}">
          <span class="expr">${esc(step.from)} ⇒ ${esc(step.to)}</span>
          <span class="by">
            ${kindLabel}
            ${step.by.rule_text ? `：<code>${esc(step.by.rule_text)}</code>` : ""}
            ${step.by.direction ? `方向 ${esc(step.by.direction)}` : ""}
            ${substStr ? `· <span class="subst">替换：${substStr}</span>` : ""}
          </span>
          ${nested}
        </li>`;
      })
      .join("");
  };

  proofEl.innerHTML = renderSteps(proof, 0);
}

function renderClasses(classes) {
  if (!classes) {
    classesWrap.hidden = true;
    classesEl.innerHTML = "";
    return;
  }
  classesWrap.hidden = false;
  classesEl.innerHTML = classes
    .map(
      (c) => `<div class="class-card">
        <header>
          <span>代表元：<code>${esc(c.representative)}</code></span>
          <span>digest: ${esc(c.digest)}</span>
        </header>
        <div class="members">
          ${c.members.map((m) => esc(m)).join(" &nbsp;≈&nbsp; ")}
        </div>
        <footer><small>成员数 ${c.size}</small></footer>
      </div>`
    )
    .join("");
}

function clearStaleEvidence(data) {
  // 服务端已按结论清空相应字段；前端再兜底，确保不展示上一次的旧证据。
  if (data.status !== "equivalent") {
    data.proof = null;
  }
  if (data.status === "unknown" || data.status === "invalid") {
    data.classes = null;
  }
  // not_equivalent：已饱和，保留稳定等价类摘要，但不保留证据。
  return data;
}

function renderResult(data) {
  data = clearStaleEvidence(data);
  resultPanel.hidden = false;
  renderSummary(data.summary);

  verdictEl.className = `verdict ${data.status}`;
  verdictEl.textContent = `${data.status_text}（${data.status}）`;

  issuesEl.className = "issues";
  if (data.issues && data.issues.length) {
    issuesEl.innerHTML = `<h2>问题清单（旧结论已清除）</h2>
      <ul>${data.issues
        .map((i) => `<li>[${i.field || "-"}] ${esc(i.message)}</li>`)
        .join("")}</ul>`;
  } else {
    issuesEl.innerHTML = "";
  }

  if (data.limit_reason) {
    limitEl.className = "limit";
    limitEl.innerHTML = `<strong>资源边界：</strong>${esc(data.limit_reason)}
      因此结论为“未完成”，不作等价判断。`;
  } else {
    limitEl.className = "";
    limitEl.innerHTML = "";
  }

  renderProof(data.proof);
  renderClasses(data.classes);

  if (data.stats) {
    statsEl.className = "stats";
    statsEl.innerHTML = `统计：${data.stats.terms} 个登记项 ·
      ${data.stats.rule_applications} 次规则有效应用 ·
      ${data.stats.rounds} 轮扫描 · ${data.stats.merge_events} 次合并
      ${"classes" in data.stats ? ` · ${data.stats.classes} 个等价类` : ""}`;
  } else {
    statsEl.className = "";
    statsEl.innerHTML = "";
  }
}

function collectRules() {
  return Array.from(document.querySelectorAll("#ruleList input"))
    .map((input) => input.value.trim())
    .filter((v) => v.length);
}

async function submit() {
  const payload = {
    left: document.getElementById("leftExpr").value,
    right: document.getElementById("rightExpr").value,
    rules: collectRules(),
    max_nodes: Number(document.getElementById("maxNodes").value) || 80,
    max_applications: Number(document.getElementById("maxApps").value) || 5000,
  };
  requestState.textContent = "复核中…";
  try {
    const resp = await fetch("/api/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    renderResult(data);
    requestState.textContent = `已更新（${new Date().toLocaleTimeString()}）`;
  } catch (err) {
    requestState.textContent = `请求失败：${err}`;
  }
}

document.getElementById("submit").addEventListener("click", submit);

const ruleList = document.getElementById("ruleList");
function addRule(value = "") {
  const li = document.createElement("li");
  li.innerHTML = `<input type="text" placeholder="例如 add(x,y) = add(y,x)"
    spellcheck="false" />
    <button type="button" class="del">删除</button>`;
  li.querySelector(".del").addEventListener("click", () => li.remove());
  li.querySelector("input").value = value;
  ruleList.appendChild(li);
}
document.getElementById("addRule").addEventListener("click", () => addRule());

const EXAMPLE_RULES = ["add(x,y) = add(y,x)"];
document.getElementById("loadExample").addEventListener("click", () => {
  ruleList.innerHTML = "";
  EXAMPLE_RULES.forEach((r) => addRule(r));
});

// 初始载入交换律示例。
EXAMPLE_RULES.forEach((r) => addRule(r));
