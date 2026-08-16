// Enterprise AI Research Agent -- frontend SPA (no build step required).
// Talks to the real backend at window.API_BASE via fetch(). Every view
// here calls a real endpoint from backend/app/api/*.py -- there is no
// mock data or hard-coded research content anywhere in this file.

const API = window.API_BASE;

async function api(path, opts) {
  const res = await fetch(`${API}${path}`, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

const NAV = [
  ["dashboard", "Dashboard"],
  ["research", "Research"],
  ["history", "Research History"],
  ["knowledge", "Knowledge Base"],
  ["entities", "Entities / Relationships"],
];

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function timeAgo(iso) {
  if (!iso) return "";
  const d = new Date(iso + (iso.endsWith("Z") ? "" : "Z"));
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return d.toLocaleDateString();
}

function render(route) {
  const app = document.getElementById("app");
  const [page, ...rest] = route.split("/").filter(Boolean);
  const activePage = page || "dashboard";

  app.innerHTML = "";
  app.appendChild(renderNav(activePage));
  const main = el(`<div class="main"></div>`);
  app.appendChild(main);

  if (activePage === "dashboard") renderDashboard(main);
  else if (activePage === "research" && rest[0]) renderResearchDetail(main, rest[0]);
  else if (activePage === "research") renderResearchWorkspace(main);
  else if (activePage === "history") renderHistory(main);
  else if (activePage === "knowledge") renderKnowledgeBase(main);
  else if (activePage === "entities") renderEntities(main);
  else if (activePage === "source" && rest[0]) renderSourceDetail(main, rest[0]);
  else if (activePage === "claim" && rest[0]) renderClaimDetail(main, rest[0]);
  else renderDashboard(main);
}

function renderNav(activePage) {
  const nav = el(`
    <div class="nav-rail">
      <div class="nav-brand">Research Agent
        <small>Enterprise AI · v1.0</small>
      </div>
    </div>
  `);
  NAV.forEach(([key, label]) => {
    const a = el(`<a class="nav-link ${key === activePage ? "active" : ""}">${label}</a>`);
    a.onclick = () => { location.hash = `#/${key}`; };
    nav.appendChild(a);
  });
  nav.appendChild(el(`<div class="nav-footer">Backend: ${escapeHtml(API)}<br/>Live FastAPI + SQLite</div>`));
  return nav;
}

// ---------------- Dashboard ----------------
async function renderDashboard(main) {
  main.appendChild(el(`
    <div class="page-header">
      <div class="page-title">Dashboard</div>
      <div class="page-sub">Live snapshot of the persistent research knowledge base.</div>
    </div>
  `));
  const loading = el(`<div class="loading">Loading…</div>`);
  main.appendChild(loading);
  try {
    const jobs = await api("/api/research?limit=100");
    loading.remove();
    const totalSources = new Set();
    let findings = 0, claims = 0, contradictions = 0;
    jobs.forEach(j => { findings += j.finding_count; claims += j.claim_count; contradictions += j.contradiction_count; });

    const stats = el(`<div class="stat-grid"></div>`);
    [["Research Jobs", jobs.length], ["Findings Extracted", findings], ["Claims", claims], ["Contradictions Found", contradictions]]
      .forEach(([label, num]) => stats.appendChild(el(`<div class="stat-box"><div class="stat-num">${num}</div><div class="stat-label">${label}</div></div>`)));
    main.appendChild(stats);

    const card = el(`<div class="card"><div class="card-title">Recent Research</div><div class="row-list"></div></div>`);
    const list = card.querySelector(".row-list");
    if (!jobs.length) list.appendChild(el(`<div class="empty-state">No research yet. Start one from the Research tab.</div>`));
    jobs.slice(0, 8).forEach(j => list.appendChild(jobRow(j)));
    main.appendChild(card);
  } catch (e) {
    loading.replaceWith(errorBox(e));
  }
}

function jobRow(j) {
  const row = el(`
    <div class="row-item">
      <div class="row-title">${escapeHtml(j.question)}</div>
      <div class="row-meta">${j.status} · ${j.source_count} sources · ${j.finding_count} findings · ${j.claim_count} claims · ${j.contradiction_count} contradictions · ${timeAgo(j.created_at)}</div>
    </div>
  `);
  row.onclick = () => { location.hash = `#/research/${j.id}`; };
  return row;
}

function errorBox(e) {
  return el(`<div class="card" style="border-color:var(--rust);color:var(--rust)">Error: ${escapeHtml(e.message)}. Is the backend running at ${escapeHtml(API)}?</div>`);
}

// ---------------- Research workspace (new research) ----------------
function renderResearchWorkspace(main) {
  main.appendChild(el(`
    <div class="page-header">
      <div class="page-title">New Research</div>
      <div class="page-sub">Enter any enterprise research question -- nothing here is hard-coded to a topic.</div>
    </div>
  `));
  const card = el(`
    <div class="card">
      <textarea id="q" rows="2" placeholder="e.g. What AI technologies are changing manufacturing?"></textarea>
      <div style="margin-top:10px"><button id="start">Start Research</button></div>
    </div>
  `);
  main.appendChild(card);
  card.querySelector("#start").onclick = async () => {
    const question = card.querySelector("#q").value.trim();
    if (question.length < 5) return;
    card.querySelector("#start").disabled = true;
    try {
      const job = await api("/api/research", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      location.hash = `#/research/${job.id}`;
    } catch (e) {
      main.appendChild(errorBox(e));
    }
  };
}

// ---------------- Research detail (pipeline progress + results) ----------------
const PIPELINE_STAGES = ["PLANNING", "SEARCHING", "COLLECTING", "PROCESSING", "EXTRACTING",
  "COMPARING", "ANALYZING", "STORING", "SYNTHESIZING", "VALIDATING", "COMPLETED"];

async function renderResearchDetail(main, jobId) {
  main.appendChild(el(`<div class="page-header"><div class="page-title">Research Job</div>
    <div class="page-sub"><span class="tag">${jobId}</span></div></div>`));
  const body = el(`<div></div>`);
  main.appendChild(body);

  async function tick() {
    let job, status;
    try {
      [job, status] = await Promise.all([api(`/api/research/${jobId}`), api(`/api/research/${jobId}/status`)]);
    } catch (e) {
      body.innerHTML = "";
      body.appendChild(errorBox(e));
      return;
    }
    body.innerHTML = "";
    body.appendChild(el(`<div class="card"><div class="card-title">${escapeHtml(job.question)}</div></div>`));

    const stats = el(`<div class="stat-grid"></div>`);
    [["Sources", job.source_count], ["Findings", job.finding_count], ["Claims", job.claim_count], ["Contradictions", job.contradiction_count]]
      .forEach(([label, num]) => stats.appendChild(el(`<div class="stat-box"><div class="stat-num">${num}</div><div class="stat-label">${label}</div></div>`)));
    body.appendChild(stats);

    const pipelineCard = el(`<div class="card"><div class="card-title">Research Pipeline</div><div class="pipeline-list"></div></div>`);
    const list = pipelineCard.querySelector(".pipeline-list");
    const doneStages = new Set(status.pipeline.map(s => s.stage));
    PIPELINE_STAGES.forEach(stage => {
      const run = status.pipeline.find(s => s.stage === stage);
      const cls = run ? (run.status === "failed" ? "failed" : "completed") : "pending";
      const dur = run && run.duration_ms != null ? `${run.duration_ms}ms` : "";
      list.appendChild(el(`<div class="pipeline-step ${cls}"><span class="dot"></span>${stage}<span class="dur">${dur}</span></div>`));
    });
    body.appendChild(pipelineCard);

    if (job.status === "COMPLETED" || job.status === "FAILED") {
      await renderReportSection(body, jobId, job);
    } else {
      body.appendChild(el(`<div class="loading">Pipeline running… refreshing automatically.</div>`));
      setTimeout(tick, 900);
    }
  }
  tick();
}

async function renderReportSection(body, jobId, job) {
  const [report, sources, claims, contradictions] = await Promise.all([
    api(`/api/research/${jobId}/report`).catch(() => null),
    api(`/api/research/${jobId}/sources`).catch(() => []),
    api(`/api/research/${jobId}/claims`).catch(() => []),
    api(`/api/research/${jobId}/contradictions`).catch(() => []),
  ]);
  if (!report) return;

  body.appendChild(el(`<div class="card"><div class="card-title">Executive Summary</div><div>${escapeHtml(report.executive_summary)}</div></div>`));

  const findingsCard = el(`<div class="card"><div class="card-title">Findings by Status</div><div class="row-list"></div></div>`);
  const flist = findingsCard.querySelector(".row-list");
  const groups = [["established", report.established_findings, "established"], ["emerging", report.emerging_findings, "emerging"],
    ["conflicting", report.conflicting_evidence, "conflicting"], ["evidence gap", report.evidence_gaps, "gap"]];
  let anyFindings = false;
  groups.forEach(([label, items, cls]) => {
    items.forEach(item => {
      anyFindings = true;
      flist.appendChild(el(`
        <div class="row-item" style="cursor:default">
          <span class="badge badge-${cls}">${label}</span>
          <div class="row-title" style="margin-top:6px">${escapeHtml(item.sub_question)}</div>
          <div class="row-meta">${escapeHtml(item.statement)}</div>
        </div>
      `));
    });
  });
  if (!anyFindings) flist.appendChild(el(`<div class="empty-state">No sub-questions produced findings.</div>`));
  body.appendChild(findingsCard);

  if (contradictions.length) {
    const cCard = el(`<div class="card"><div class="card-title">Contradictions Detected</div><div class="row-list"></div></div>`);
    const clist = cCard.querySelector(".row-list");
    contradictions.forEach(c => clist.appendChild(el(`
      <div class="row-item" style="cursor:default">
        <span class="badge badge-conflicting">${c.contradiction_type.replace(/_/g, " ")}</span>
        <span class="tag" style="margin-left:6px">confidence ${c.confidence}</span>
        <div class="row-meta" style="margin-top:6px">${escapeHtml(c.explanation)}</div>
        <div class="row-meta" style="margin-top:4px;font-style:italic">${escapeHtml(c.possible_reason)}</div>
      </div>
    `)));
    body.appendChild(cCard);
  }

  const srcCard = el(`<div class="card"><div class="card-title">Sources (${sources.length})</div><div class="row-list"></div></div>`);
  const slist = srcCard.querySelector(".row-list");
  if (!sources.length) slist.appendChild(el(`<div class="empty-state">No sources retrieved -- see evidence gaps above.</div>`));
  sources.forEach(s => {
    const row = el(`
      <div class="row-item">
        <span class="badge ${s.is_new_for_this_job ? "badge-new" : "badge-reused"}">${s.is_new_for_this_job ? "newly retrieved" : "reused knowledge"}</span>
        <div class="row-title" style="margin-top:6px">${escapeHtml(s.title)}</div>
        <div class="row-meta">${escapeHtml(s.publisher || "")} ${s.publication_date ? "· " + s.publication_date : ""} · quality ${s.quality_score}</div>
      </div>
    `);
    row.onclick = () => { location.hash = `#/source/${s.id}`; };
    slist.appendChild(row);
  });
  body.appendChild(srcCard);

  const claimsCard = el(`<div class="card"><div class="card-title">Claims (${claims.length}) -- click to trace evidence</div><div class="row-list"></div></div>`);
  const clist = claimsCard.querySelector(".row-list");
  claims.forEach(c => {
    const row = el(`
      <div class="row-item">
        <div class="row-title">${escapeHtml(c.statement)}</div>
        <div class="row-meta">${c.agreement_level.replace(/_/g, " ")} · ${c.distinct_source_count} source(s) · confidence ${c.confidence}</div>
        <div class="confidence-bar"><div class="confidence-fill" style="width:${Math.round(c.confidence * 100)}%"></div></div>
      </div>
    `);
    row.onclick = () => { location.hash = `#/claim/${c.id}`; };
    clist.appendChild(row);
  });
  body.appendChild(claimsCard);
}

// ---------------- History ----------------
async function renderHistory(main) {
  main.appendChild(el(`<div class="page-header"><div class="page-title">Research History</div>
    <div class="page-sub">Every research job ever run, reopenable at any time.</div></div>`));
  try {
    const jobs = await api("/api/research?limit=200");
    const card = el(`<div class="card"><div class="row-list"></div></div>`);
    const list = card.querySelector(".row-list");
    if (!jobs.length) list.appendChild(el(`<div class="empty-state">No research jobs yet.</div>`));
    jobs.forEach(j => list.appendChild(jobRow(j)));
    main.appendChild(card);
  } catch (e) { main.appendChild(errorBox(e)); }
}

// ---------------- Knowledge base search ----------------
function renderKnowledgeBase(main) {
  main.appendChild(el(`<div class="page-header"><div class="page-title">Knowledge Base</div>
    <div class="page-sub">Semantic search across every finding, claim, and source ever stored -- across all research jobs.</div></div>`));
  const card = el(`
    <div class="card">
      <input type="text" id="kbq" placeholder="Search the knowledge base, e.g. 'predictive maintenance downtime'" />
      <div id="results" style="margin-top:14px"></div>
    </div>
  `);
  main.appendChild(card);
  const input = card.querySelector("#kbq");
  const results = card.querySelector("#results");
  let t;
  input.oninput = () => {
    clearTimeout(t);
    t = setTimeout(async () => {
      const q = input.value.trim();
      if (q.length < 2) { results.innerHTML = ""; return; }
      results.innerHTML = `<div class="loading">Searching…</div>`;
      try {
        const data = await api(`/api/knowledge/search?q=${encodeURIComponent(q)}`);
        results.innerHTML = "";
        if (!data.results.length) { results.appendChild(el(`<div class="empty-state">No matches in the knowledge base.</div>`)); return; }
        data.results.forEach(r => results.appendChild(el(`
          <div class="row-item" style="cursor:default">
            <span class="tag">${r.object_type}</span> <span class="tag">similarity ${r.similarity}</span>
            <div class="row-title" style="margin-top:6px">${escapeHtml(r.text.slice(0, 220))}</div>
            ${r.url ? `<a class="source-link" href="${escapeHtml(r.url)}" target="_blank">${escapeHtml(r.url)}</a>` : ""}
          </div>
        `)));
      } catch (e) { results.innerHTML = ""; results.appendChild(errorBox(e)); }
    }, 250);
  };
}

// ---------------- Entities / relationships ----------------
async function renderEntities(main) {
  main.appendChild(el(`<div class="page-header"><div class="page-title">Entities &amp; Relationships</div>
    <div class="page-sub">Extracted via spaCy NER + a domain technology vocabulary, linked by co-occurring relation verbs.</div></div>`));
  try {
    const [entities, relationships] = await Promise.all([api("/api/entities?limit=100"), api("/api/relationships?limit=100")]);
    const byId = Object.fromEntries(entities.map(e => [e.id, e]));
    const eCard = el(`<div class="card"><div class="card-title">Entities (${entities.length})</div><div class="tag-row"></div></div>`);
    const tagRow = eCard.querySelector(".tag-row");
    entities.forEach(e => tagRow.appendChild(el(`<span class="tag">${escapeHtml(e.name)} · ${e.entity_type}</span>`)));
    main.appendChild(eCard);

    const rCard = el(`<div class="card"><div class="card-title">Relationships (${relationships.length})</div><div class="row-list"></div></div>`);
    const rlist = rCard.querySelector(".row-list");
    if (!relationships.length) rlist.appendChild(el(`<div class="empty-state">No relationships extracted yet -- run a research job first.</div>`));
    relationships.forEach(r => {
      const a = byId[r.source_entity_id], b = byId[r.target_entity_id];
      rlist.appendChild(el(`<div class="row-item" style="cursor:default">
        <span class="tag">${a ? escapeHtml(a.name) : "?"}</span> <b>${r.relation_type}</b> <span class="tag">${b ? escapeHtml(b.name) : "?"}</span>
      </div>`));
    });
    main.appendChild(rCard);
  } catch (e) { main.appendChild(errorBox(e)); }
}

// ---------------- Source detail ----------------
async function renderSourceDetail(main, sourceId) {
  main.appendChild(el(`<div class="page-header"><div class="page-title">Source Detail</div></div>`));
  try {
    const d = await api(`/api/sources/${sourceId}`);
    const s = d.source;
    main.appendChild(el(`
      <div class="card">
        <div class="card-title">${escapeHtml(s.title)}</div>
        <div class="row-meta">${escapeHtml(s.publisher || "")} · ${escapeHtml(s.author || "unattributed")} · ${s.publication_date || "date unknown"} · ${s.source_type}</div>
        <div style="margin-top:10px"><a class="source-link" href="${escapeHtml(s.url)}" target="_blank">Open Original Source ↗</a></div>
      </div>
    `));
    const passagesCard = el(`<div class="card"><div class="card-title">Extracted Passages (${d.extracted_passages.length})</div><div class="row-list"></div></div>`);
    d.extracted_passages.forEach(p => passagesCard.querySelector(".row-list").appendChild(el(`<div class="row-item" style="cursor:default">${escapeHtml(p)}</div>`)));
    main.appendChild(passagesCard);

    const claimsCard = el(`<div class="card"><div class="card-title">Claims Derived From This Source (${d.claims_derived.length})</div><div class="row-list"></div></div>`);
    d.claims_derived.forEach(c => {
      const row = el(`<div class="row-item">${escapeHtml(c.statement)}</div>`);
      row.onclick = () => { location.hash = `#/claim/${c.id}`; };
      claimsCard.querySelector(".row-list").appendChild(row);
    });
    main.appendChild(claimsCard);

    if (d.contradictions_involving_source.length) {
      const cCard = el(`<div class="card"><div class="card-title">Contradictions Involving This Source</div><div class="row-list"></div></div>`);
      d.contradictions_involving_source.forEach(c => cCard.querySelector(".row-list").appendChild(el(`<div class="row-item" style="cursor:default">${escapeHtml(c.explanation)}</div>`)));
      main.appendChild(cCard);
    }
  } catch (e) { main.appendChild(errorBox(e)); }
}

// ---------------- Claim detail: the traceability chain ----------------
async function renderClaimDetail(main, claimId) {
  main.appendChild(el(`<div class="page-header"><div class="page-title">Claim Detail</div>
    <div class="page-sub">Full evidence trail -- exactly why the system reached this claim.</div></div>`));
  try {
    const d = await api(`/api/claims/${claimId}`);
    const c = d.claim;
    main.appendChild(el(`
      <div class="card">
        <div class="card-title">Claim</div>
        <div style="font-size:15px">${escapeHtml(c.statement)}</div>
        <div class="tag-row">
          <span class="tag">confidence ${c.confidence}</span>
          <span class="tag">${c.evidence_strength}</span>
          <span class="tag">${c.agreement_level.replace(/_/g, " ")}</span>
          <span class="tag">${c.distinct_source_count} source(s)</span>
        </div>
      </div>
    `));

    function evidenceBlock(title, bundle, cls) {
      const card = el(`<div class="card"><div class="card-title">${title} (${bundle.evidence.length})</div><div class="row-list"></div></div>`);
      const list = card.querySelector(".row-list");
      if (!bundle.evidence.length) list.appendChild(el(`<div class="empty-state">None.</div>`));
      bundle.evidence.forEach((f, i) => {
        const src = bundle.sources[i] || bundle.sources.find(s => s.id === f.source_id);
        list.appendChild(el(`
          <div class="row-item" style="cursor:default">
            <span class="badge badge-${cls}">${f.evidence_strength}</span>
            <div class="row-title" style="margin-top:6px">${escapeHtml(f.evidence_text)}</div>
            ${src ? `<div class="row-meta">${escapeHtml(src.title)} · <a class="source-link" href="${escapeHtml(src.url)}" target="_blank">${escapeHtml(src.url)}</a></div>` : ""}
          </div>
        `));
      });
      return card;
    }
    main.appendChild(evidenceBlock("Supporting Evidence → Sources", d.supporting, "established"));
    main.appendChild(evidenceBlock("Contradicting Evidence → Sources", d.contradicting, "conflicting"));
  } catch (e) { main.appendChild(errorBox(e)); }
}

window.addEventListener("hashchange", () => render(location.hash.slice(2)));
render(location.hash.slice(2));
