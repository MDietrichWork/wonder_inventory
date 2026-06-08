/* Variant C — app logic: view switching, charts, drill-down, drawer. */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const D = DATA;

  // palette for chart categories
  const PAL = ["#5b8cff","#7c5cff","#2dd4bf","#f5b54a","#34d399","#f472b6","#f76d6d","#9aa7c4"];
  const SEV_COLOR = { Critical:"#f76d6d", High:"#f5b54a", Medium:"#5b8cff", Low:"#9aa7c4" };
  const SYS_COLOR = { "Pantry":"#5b8cff", "Ship Hero":"#7c5cff", "Fishbowl":"#2dd4bf" };

  const TITLES = {
    dashboard: ["Reporting", "Reporting Dashboard"],
    exceptions: ["Operations", "Exception List"],
    sla: ["Performance", "Ticket Turnaround / SLA"],
    admin: ["Configuration", "Rule & Routing Admin"]
  };

  // active drill-down filter applied to the exceptions view
  let activeFilter = null; // {field, value, label}

  function statusClass(s) { return "st st-" + s.replace(/[\s-]/g, ""); }
  function esc(s) { return String(s).replace(/[&<>]/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;" }[c])); }

  // ---------- View routing ----------
  function go(view) {
    $$(".view").forEach(v => v.classList.remove("active"));
    $("#view-" + view).classList.add("active");
    $$(".nav-item").forEach(n => n.classList.toggle("active", n.dataset.view === view));
    $("#crumb").textContent = TITLES[view][0];
    $("#pageTitle").textContent = TITLES[view][1];
    $(".scroll").scrollTop = 0;
    if (view === "exceptions") renderExceptions();
  }
  $$(".nav-item").forEach(n => n.addEventListener("click", () => go(n.dataset.view)));

  function drillTo(field, value, label) {
    activeFilter = { field, value, label };
    go("exceptions");
  }

  // ============================================================
  //  DASHBOARD
  // ============================================================
  function renderDashboard() {
    const k = D.kpis;
    const el = $("#view-dashboard");
    el.innerHTML = `
      <div class="intro">
        <h2>Wonder Inventory Data-Quality Console</h2>
        <p>Wonder Group has no central ERP, so a synthetic <b>unified inventory ledger</b> + <b>purchase-order table</b> in BigQuery serves as the sub-ledger Accounting uses to book the general ledger at month-end. Each day a batch job validates the <b>prior day's</b> data, flags errors, auto-creates JIRA tickets routed to the right team, tracks turnaround against SLA, spots recurring errors, and <b>auto-closes</b> tickets once Data Engineering fixes the underlying table. This dashboard gives managers the health picture first — then click any tile or chart segment to drill into the underlying exceptions.</p>
      </div>

      <div class="kpi-grid">
        ${kpiCard("Open Exceptions", k.openExceptions, "across all teams", "bad", "+3 vs prior run", "#f76d6d", "open")}
        ${kpiCard("New Today", k.newToday, "from run_date 2026-06-07", "bad", "new flags", "#f5b54a", "new")}
        ${kpiCardAuto("Auto-Closed Today", k.autoClosedToday)}
        ${kpiCard("Avg Turnaround", k.avgTurnaround + "d", "across resolved tickets", "good", "-0.4d vs prior", "#7c5cff", null)}
        ${kpiCard("% Within SLA", k.withinSlaPct + "%", k.slaWithin + " of " + k.total + " on target", k.withinSlaPct>=80?"good":"bad", k.withinSlaPct>=80?"healthy":"watch", "#34d399", "sla")}
        ${kpiGauge("Data-Quality Score", k.dqScore)}
      </div>

      <div class="grid cols-2" style="margin-bottom:18px">
        <div class="card">
          <div class="card-h"><h3>Error Trend — last 21 days</h3><span class="hint">daily flagged errors &amp; auto-closed</span></div>
          ${trendChart()}
          <div class="legend">
            <span><i style="background:#5b8cff"></i>Errors flagged</span>
            <span><i style="background:#2dd4bf"></i>Auto-closed</span>
          </div>
        </div>
        <div class="card">
          <div class="card-h"><h3>Errors by System of Origin</h3><span class="hint">click to drill</span></div>
          ${systemDonut()}
        </div>
      </div>

      <div class="grid cols-2b" style="margin-bottom:18px">
        <div class="card">
          <div class="card-h"><h3>Errors by Type</h3><span class="hint">click a bar to drill</span></div>
          ${typeBars()}
        </div>
        <div class="card">
          <div class="card-h"><h3>Errors by Facility</h3><span class="hint">click a bar to drill</span></div>
          ${facilityBars()}
        </div>
      </div>

      <div class="card">
        <div class="card-h"><h3>Recurring-Error Leaderboard</h3><span class="hint">last 30 days · click to drill</span></div>
        <div class="card-sub">Where the same defect keeps coming back — prime candidates for an upstream fix.</div>
        ${recurringLeaderboard()}
      </div>
    `;
    wireDashboard();
  }

  function kpiCard(label, val, sub, dir, chip, color, drill) {
    const cls = drill ? "kpi clickable" : "kpi";
    return `<div class="${cls}" ${drill?`data-drill="${drill}"`:""}>
      <div class="accent" style="background:${color}"></div>
      <div class="k-label">${label}</div>
      <div class="k-val">${val}</div>
      <div class="k-sub"><span class="chip-trend ${dir==="good"?"good":"bad"}">${chip}</span>${sub}</div>
    </div>`;
  }
  function kpiCardAuto(label, val) {
    return `<div class="kpi clickable" data-drill="autoclosed">
      <div class="accent" style="background:#2dd4bf"></div>
      <div class="k-label">${label}</div>
      <div class="k-val">${val}</div>
      <div class="k-sub"><span class="chip-trend good">flagship</span>issue no longer reproduced</div>
    </div>`;
  }
  function kpiGauge(label, score) {
    const r = 26, c = 2 * Math.PI * r, off = c * (1 - score / 100);
    const col = score >= 80 ? "#34d399" : score >= 60 ? "#f5b54a" : "#f76d6d";
    return `<div class="kpi">
      <div class="accent" style="background:${col}"></div>
      <div class="k-label">${label}</div>
      <div class="gauge" style="margin-top:8px">
        <svg width="64" height="64" viewBox="0 0 64 64">
          <circle cx="32" cy="32" r="${r}" fill="none" stroke="#1f2a44" stroke-width="7"/>
          <circle cx="32" cy="32" r="${r}" fill="none" stroke="${col}" stroke-width="7"
            stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${off}"
            transform="rotate(-90 32 32)"/>
          <text x="32" y="37" text-anchor="middle" fill="#e7ecf6" font-size="16" font-weight="800">${score}</text>
        </svg>
        <div class="k-sub" style="margin:0">composite of open<br>severity-weighted defects</div>
      </div>
    </div>`;
  }

  // ---- Trend line chart (SVG) ----
  function trendChart() {
    const data = D.TREND;
    const W = 560, H = 220, padL = 36, padR = 12, padT = 14, padB = 28;
    const iw = W - padL - padR, ih = H - padT - padB;
    const maxV = Math.max(...data.map(d => d.errors)) + 2;
    const x = i => padL + (iw * i) / (data.length - 1);
    const y = v => padT + ih - (ih * v) / maxV;

    const linePts = data.map((d, i) => `${x(i)},${y(d.errors)}`).join(" ");
    const areaPts = `${padL},${padT+ih} ${linePts} ${x(data.length-1)},${padT+ih}`;
    const autoPts = data.map((d, i) => `${x(i)},${y(d.autoClosed)}`).join(" ");

    // y gridlines
    let grid = "";
    const steps = 4;
    for (let s = 0; s <= steps; s++) {
      const v = Math.round((maxV * s) / steps);
      const yy = y(v);
      grid += `<line class="grid-line" x1="${padL}" y1="${yy}" x2="${W-padR}" y2="${yy}"/>
               <text class="axis-label" x="${padL-8}" y="${yy+3}" text-anchor="end">${v}</text>`;
    }
    // x labels (every 4th)
    let xlab = "";
    data.forEach((d, i) => {
      if (i % 4 === 0 || i === data.length - 1) {
        xlab += `<text class="axis-label" x="${x(i)}" y="${H-8}" text-anchor="middle">${d.date.slice(5)}</text>`;
      }
    });
    let dots = "";
    data.forEach((d, i) => {
      dots += `<circle class="dot-pt" cx="${x(i)}" cy="${y(d.errors)}" r="3" fill="#5b8cff"><title>${d.date}: ${d.errors} errors</title></circle>`;
    });

    return `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Error trend chart">
      <defs>
        <linearGradient id="areaG" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#5b8cff" stop-opacity="0.5"/>
          <stop offset="100%" stop-color="#5b8cff" stop-opacity="0"/>
        </linearGradient>
      </defs>
      ${grid}
      <line class="axis-line" x1="${padL}" y1="${padT+ih}" x2="${W-padR}" y2="${padT+ih}"/>
      <polygon class="area-fill" points="${areaPts}" fill="url(#areaG)"/>
      <polyline class="line-path" points="${linePts}" stroke="#5b8cff"/>
      <polyline class="line-path" points="${autoPts}" stroke="#2dd4bf" stroke-dasharray="5 4" stroke-width="2"/>
      ${dots}
      ${xlab}
    </svg>`;
  }

  // ---- Type bars ----
  function typeBars() {
    const entries = Object.entries(D.byType).sort((a, b) => b[1] - a[1]);
    const max = Math.max(...entries.map(e => e[1]));
    return `<div class="hbars">` + entries.map(([t, n], i) => {
      const w = (n / max) * 100;
      return `<div class="hbar" data-drill-type="${t}">
        <div class="hb-label" title="${t}">${t.replace(/_/g," ")}</div>
        <div class="hb-track"><div class="hb-fill" style="width:${w}%;background:${PAL[i % PAL.length]}"></div></div>
        <div class="hb-val">${n}</div>
      </div>`;
    }).join("") + `</div>`;
  }

  // ---- Facility bars ----
  function facilityBars() {
    const entries = Object.entries(D.byFacility).sort((a, b) => b[1] - a[1]);
    const max = Math.max(...entries.map(e => e[1]));
    return `<div class="hbars">` + entries.map(([f, n], i) => {
      const w = (n / max) * 100;
      return `<div class="hbar" data-drill-fac="${f}">
        <div class="hb-label">${f}</div>
        <div class="hb-track"><div class="hb-fill" style="width:${w}%;background:${PAL[(i+2) % PAL.length]}"></div></div>
        <div class="hb-val">${n}</div>
      </div>`;
    }).join("") + `</div>`;
  }

  // ---- System donut ----
  function systemDonut() {
    const entries = Object.entries(D.bySystem);
    const total = entries.reduce((s, e) => s + e[1], 0);
    const r = 56, cx = 70, cy = 70, sw = 22;
    const circ = 2 * Math.PI * r;
    let offset = 0, arcs = "";
    entries.forEach(([sys, n]) => {
      const frac = n / total;
      const len = circ * frac;
      arcs += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${SYS_COLOR[sys]}"
        stroke-width="${sw}" stroke-dasharray="${len} ${circ - len}" stroke-dashoffset="${-offset}"
        transform="rotate(-90 ${cx} ${cy})"><title>${sys}: ${n}</title></circle>`;
      offset += len;
    });
    const legend = entries.map(([sys, n]) =>
      `<div class="row" data-drill-sys="${sys}">
        <span class="sw" style="background:${SYS_COLOR[sys]}"></span>${sys}
        <span class="lv">${n} · ${Math.round(100*n/total)}%</span>
      </div>`).join("");
    return `<div class="donut-wrap">
      <svg width="140" height="140" viewBox="0 0 140 140" role="img" aria-label="Errors by system">
        ${arcs}
        <text x="${cx}" y="${cy-2}" text-anchor="middle" fill="#e7ecf6" font-size="22" font-weight="800">${total}</text>
        <text x="${cx}" y="${cy+15}" text-anchor="middle" fill="#6b7795" font-size="10">errors</text>
      </svg>
      <div class="donut-legend">${legend}</div>
    </div>`;
  }

  // ---- Recurring leaderboard ----
  function recurringLeaderboard() {
    const max = Math.max(...D.RECURRING.map(r => r.count30d));
    return `<div class="lb">` + D.RECURRING.map((r, i) => {
      const trCls = r.trend === "up" ? "tr-up" : r.trend === "down" ? "tr-down" : "tr-flat";
      const trIco = r.trend === "up" ? "▲ rising" : r.trend === "down" ? "▼ falling" : "— flat";
      return `<div class="lb-row" data-drill-type="${r.type}" data-drill-fac="${r.facility}">
        <div class="lb-rank">${i + 1}</div>
        <div>
          <div class="lb-title">${r.type.replace(/_/g," ")}</div>
          <div class="lb-sub">${r.facility} · recurred ${r.count30d}× / 30d</div>
        </div>
        <div class="tr-ico ${trCls}">${trIco}</div>
        <div class="lb-count" style="color:${PAL[i%PAL.length]}">${r.count30d}</div>
      </div>`;
    }).join("") + `</div>`;
  }

  function wireDashboard() {
    $$("#view-dashboard [data-drill]").forEach(el => el.addEventListener("click", () => {
      const d = el.dataset.drill;
      if (d === "open") drillTo("status", "open", "Open exceptions");
      else if (d === "new") drillTo("new", true, "New today (run 06-07)");
      else if (d === "autoclosed") drillTo("status", "Auto-Closed", "Auto-Closed tickets");
      else if (d === "sla") drillTo("sla", "breach", "Breaching SLA");
    }));
    $$("#view-dashboard [data-drill-type]").forEach(el => el.addEventListener("click", () => {
      const t = el.dataset.drillType, f = el.dataset.drillFac;
      if (f) drillTo("typefac", { type: t, fac: f }, t.replace(/_/g," ") + " @ " + f);
      else drillTo("type", t, "Type: " + t.replace(/_/g," "));
    }));
    $$("#view-dashboard [data-drill-fac]:not([data-drill-type])").forEach(el => el.addEventListener("click", () => {
      drillTo("facility", el.dataset.drillFac, "Facility: " + el.dataset.drillFac);
    }));
    $$("#view-dashboard [data-drill-sys]").forEach(el => el.addEventListener("click", () => {
      drillTo("system", el.dataset.drillSys, "System: " + el.dataset.drillSys);
    }));
  }

  // ============================================================
  //  EXCEPTIONS LIST
  // ============================================================
  let sortKey = "ageDays", sortDir = -1;

  function bucketRange(b, v) {
    if (b === "0-1d") return v <= 1;
    if (b === "1-3d") return v > 1 && v <= 3;
    if (b === "3-7d") return v > 3 && v <= 7;
    return v > 7;
  }

  function passesFilter(e) {
    if (!activeFilter) return true;
    const f = activeFilter;
    switch (f.field) {
      case "bucket": {
        const v = e.turnaround != null ? e.turnaround : e.ageDays;
        return bucketRange(f.value, v);
      }
      case "status":
        if (f.value === "open") return D.helpers.isOpen(e);
        return e.jiraStatus === f.value;
      case "new": return e.ageDays <= 1;
      case "sla": return f.value === "breach" ? !e.withinSla : e.withinSla;
      case "type": return e.type === f.value;
      case "facility": return e.facility === f.value;
      case "system": return e.system === f.value;
      case "team": return e.team === f.value;
      case "typefac": return e.type === f.value.type && e.facility === f.value.fac;
      default: return true;
    }
  }

  function renderExceptions() {
    const el = $("#view-exceptions");
    // dropdown filters
    const teamOpts = ["All teams", ...Object.keys(D.TEAMS)];
    const sevOpts = ["All severities", "Critical", "High", "Medium", "Low"];
    const sysOpts = ["All systems", ...D.SYSTEMS];

    el.innerHTML = `
      <div class="toolbar">
        <select id="fTeam">${teamOpts.map(o=>`<option>${o}</option>`).join("")}</select>
        <select id="fSev">${sevOpts.map(o=>`<option>${o}</option>`).join("")}</select>
        <select id="fSys">${sysOpts.map(o=>`<option>${o}</option>`).join("")}</select>
        <input id="fSearch" placeholder="Filter by ID, JIRA, assignee…" />
        <div class="spacer"></div>
        <span class="muted" id="exCount"></span>
      </div>
      <div class="filter-chips" id="chips"></div>
      <div class="tbl-wrap" style="margin-top:14px">
        <table>
          <thead><tr>
            ${th("Error ID","id")}${th("Type","type")}${th("Severity","severity")}
            ${th("Facility","facility")}${th("System","system")}${th("Assignee","assignee")}
            ${th("JIRA","jira")}${th("Status","jiraStatus")}${th("Age","ageDays")}${th("Recur","recurrence")}
          </tr></thead>
          <tbody id="exBody"></tbody>
        </table>
      </div>`;

    $$("#view-exceptions thead th").forEach(t => t.addEventListener("click", () => {
      const k = t.dataset.k;
      if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = 1; }
      drawRows();
    }));
    ["fTeam","fSev","fSys","fSearch"].forEach(id => {
      $("#"+id).addEventListener("input", drawRows);
    });
    drawChips();
    drawRows();
  }
  function th(label, k) { return `<th data-k="${k}">${label}</th>`; }

  function drawChips() {
    const c = $("#chips");
    if (!activeFilter) { c.innerHTML = `<span class="muted">No drill-down filter active. Click a tile or chart on the dashboard to drill in.</span>`; return; }
    c.innerHTML = `<span class="muted">Drilled from dashboard:</span>
      <span class="fchip">${esc(activeFilter.label)}<button id="clearChip" title="Clear">✕</button></span>`;
    $("#clearChip").addEventListener("click", () => { activeFilter = null; drawChips(); drawRows(); });
  }

  function drawRows() {
    const team = val("#fTeam"), sev = val("#fSev"), sys = val("#fSys"), q = (val("#fSearch")||"").toLowerCase();
    let rows = D.EXCEPTIONS.filter(passesFilter).filter(e => {
      if (team && !team.startsWith("All") && e.team !== team) return false;
      if (sev && !sev.startsWith("All") && e.severity !== sev) return false;
      if (sys && !sys.startsWith("All") && e.system !== sys) return false;
      if (q && !(`${e.id} ${e.jira} ${e.assignee} ${e.type}`.toLowerCase().includes(q))) return false;
      return true;
    });
    rows.sort((a, b) => {
      let x = a[sortKey], y = b[sortKey];
      if (typeof x === "string") return sortDir * x.localeCompare(y);
      return sortDir * ((x||0) - (y||0));
    });
    $("#exCount").textContent = rows.length + " of " + D.EXCEPTIONS.length + " exceptions";
    $("#exBody").innerHTML = rows.map(e => `
      <tr data-id="${e.id}">
        <td class="mono">${e.id}</td>
        <td>${e.type.replace(/_/g," ")}</td>
        <td><span class="badge sev-${e.severity}">${e.severity}</span></td>
        <td>${e.facility}</td>
        <td>${e.system}</td>
        <td>${e.assignee}</td>
        <td><span class="jira-link">${e.jira}</span></td>
        <td><span class="${statusClass(e.jiraStatus)}">${e.jiraStatus}</span></td>
        <td>${e.ageDays}d</td>
        <td>${e.recurrence>=3?`<span class="recur-tag">${e.recurrence}× /30d</span>`:`<span class="muted">${e.recurrence}×</span>`}</td>
      </tr>`).join("") || `<tr><td colspan="10" style="text-align:center;padding:30px" class="muted">No exceptions match the current filters.</td></tr>`;
    $$("#exBody tr[data-id]").forEach(r => r.addEventListener("click", () => openDrawer(r.dataset.id)));
  }
  function val(s){ const el=$(s); return el? el.value : ""; }

  // ============================================================
  //  DRAWER (exception detail)
  // ============================================================
  function snapHtml(snap) {
    return Object.entries(snap).map(([k, v]) => {
      let vs;
      if (v === null) vs = `<span class="null">null</span>`;
      else if (typeof v === "number" && (v < 0)) vs = `<span class="bad">${v}</span>`;
      else if (k === "result" && String(v).includes("NOT")) vs = `<span class="bad">"${v}"</span>`;
      else if (typeof v === "string") vs = `"${esc(v)}"`;
      else vs = esc(v);
      return `<div><span class="key">${esc(k)}</span>: ${vs}</div>`;
    }).join("");
  }

  function openDrawer(id) {
    const e = D.EXCEPTIONS.find(x => x.id === id);
    if (!e) return;
    const dr = $("#drawer");
    dr.innerHTML = `
      <div class="drawer-h">
        <div>
          <div class="d-eyebrow">${e.id} · ${e.rule} rule</div>
          <div class="d-title">${e.type.replace(/_/g," ")}</div>
          <div class="d-meta">
            <span class="badge sev-${e.severity}">${e.severity}</span>
            <span class="${statusClass(e.jiraStatus)}">${e.jiraStatus}</span>
            ${e.recurrence>=3?`<span class="recur-tag">${e.recurrence}× /30d recurring</span>`:""}
          </div>
        </div>
        <button class="x" id="drawerClose" aria-label="Close">✕</button>
      </div>
      <div class="drawer-body">
        <div class="d-section">
          <h4>Routing</h4>
          <div class="kv">
            <div class="k">Facility</div><div class="v">${e.facility}</div>
            <div class="k">System of origin</div><div class="v">${e.system}</div>
            <div class="k">Source table</div><div class="v mono">${e.table}</div>
            <div class="k">Team</div><div class="v">${e.team}</div>
            <div class="k">Assignee</div><div class="v">${e.assignee}</div>
            <div class="k">JIRA</div><div class="v"><span class="jira-link">${e.jira}</span> · ${D.meta.project} / ${e.component}</div>
            <div class="k">SLA target</div><div class="v">${e.sla}d · ${e.withinSla?'<span style="color:#34d399">within SLA</span>':'<span style="color:#f76d6d">breaching</span>'}</div>
          </div>
        </div>

        <div class="d-section">
          <h4>Rule that fired</h4>
          <div class="rule-box">
            <b>${e.type}</b> (<code>${e.rule}</code>) — ${D.RULES.find(r=>r.name===e.type).description}
          </div>
        </div>

        <div class="d-section">
          <h4>Offending ${e.table} snapshot</h4>
          <div class="snap">${snapHtml(e.snapshot)}</div>
        </div>

        <div class="d-section">
          <h4>JIRA status timeline</h4>
          <div class="timeline">
            ${e.timeline.map(t => {
              const isDone = ["Resolved","Closed"].includes(t.label);
              const isAuto = t.label === "Auto-Closed";
              return `<div class="tl-item ${isDone?'done':''} ${isAuto?'auto':''}">
                <div class="tl-dot"></div>
                <div class="tl-label">${t.label}</div>
                <div class="tl-meta">${t.at}</div>
                <div class="tl-note">${t.note}</div>
              </div>`;
            }).join("")}
          </div>
          ${e.turnaround!=null?`<div class="note">Resolved in ${e.turnaround}d (target ${e.sla}d).</div>`:`<div class="note">Open ${e.ageDays}d so far.</div>`}
        </div>

        <div class="d-section">
          <h4>Actions</h4>
          <div class="actions">
            <button class="btn" data-act="reassign">Reassign…</button>
            <button class="btn" data-act="note">Add note</button>
            <button class="btn primary" data-act="jira">Open ${e.jira} in JIRA ↗</button>
          </div>
          <div class="note">Mock actions — prototype only; no changes are persisted.</div>
        </div>
      </div>`;
    dr.classList.add("show"); dr.setAttribute("aria-hidden", "false");
    $("#drawerScrim").classList.add("show");
    $("#drawerClose").addEventListener("click", closeDrawer);
    $$("#drawer [data-act]").forEach(b => b.addEventListener("click", () => {
      const a = b.dataset.act;
      const msg = a === "reassign" ? "Reassign dialog (mock): pick a new team/assignee."
        : a === "note" ? "Add internal note (mock)."
        : "Would open " + e.jira + " in JIRA (mock).";
      alert(msg);
    }));
  }
  function closeDrawer() {
    $("#drawer").classList.remove("show");
    $("#drawer").setAttribute("aria-hidden", "true");
    $("#drawerScrim").classList.remove("show");
  }
  $("#drawerScrim").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

  // ============================================================
  //  SLA / TURNAROUND
  // ============================================================
  function renderSla() {
    const el = $("#view-sla");
    const k = D.kpis;
    const teams = D.turnaroundByTeam;
    const people = D.turnaroundByPerson;
    const buckets = D.agingBuckets;

    el.innerHTML = `
      <div class="intro">
        <h2>Where we're losing time</h2>
        <p>Turnaround = days from auto-created JIRA ticket to resolution. SLA targets vary by severity (Critical 1d · High 3d · Medium 5d · Low 10d). Use this view to spot the slowest team and the people who are behind, then act before month-end close.</p>
      </div>

      <div class="grid cols-2b" style="margin-bottom:18px">
        <div class="card">
          <div class="card-h"><h3>SLA Compliance</h3><span class="hint">${k.slaWithin} within · ${k.slaBreach} breaching</span></div>
          <div class="split-bar">
            <div class="seg" style="width:${k.withinSlaPct}%;background:#34d399">${k.withinSlaPct}% within</div>
            <div class="seg" style="width:${100-k.withinSlaPct}%;background:#f76d6d">${100-k.withinSlaPct}% breach</div>
          </div>
          <div class="legend"><span><i class="sq" style="background:#34d399"></i>Within SLA</span><span><i class="sq" style="background:#f76d6d"></i>Breaching SLA</span></div>
        </div>
        <div class="card">
          <div class="card-h"><h3>Avg Turnaround Trend</h3><span class="hint">last 21 days (days)</span></div>
          ${turnaroundTrend()}
        </div>
      </div>

      <div class="card" style="margin-bottom:18px">
        <div class="card-h"><h3>Aging Buckets</h3><span class="hint">click to drill into the list</span></div>
        <div class="bucket-grid">
          ${bucketCard("0-1d", buckets["0-1d"], "#34d399")}
          ${bucketCard("1-3d", buckets["1-3d"], "#5b8cff")}
          ${bucketCard("3-7d", buckets["3-7d"], "#f5b54a")}
          ${bucketCard("7d+", buckets["7d+"], "#f76d6d")}
        </div>
      </div>

      <div class="grid cols-2b" style="margin-bottom:18px">
        <div class="card">
          <div class="card-h"><h3>Turnaround by Team</h3><span class="hint">avg days · click to drill</span></div>
          <div class="card-sub">Procurement is the clear bottleneck this cycle.</div>
          ${teamBars(teams)}
        </div>
        <div class="card">
          <div class="card-h"><h3>SLA % by Team</h3><span class="hint">share resolved within target</span></div>
          ${slaByTeamBars(teams)}
        </div>
      </div>

      <div class="card">
        <div class="card-h"><h3>Who's Behind — Person Ranking</h3><span class="hint">slowest avg turnaround first</span></div>
        ${personRanking(people)}
      </div>
    `;
    wireSla();
  }

  function bucketCard(range, val, color) {
    const total = Object.values(D.agingBuckets).reduce((a,b)=>a+b,0);
    const w = total ? (val/total*100) : 0;
    return `<div class="bucket" data-bucket="${range}">
      <div class="b-range">Age ${range}</div>
      <div class="b-val" style="color:${color}">${val}</div>
      <div class="b-bar" style="width:${w}%;background:${color}"></div>
    </div>`;
  }

  function teamBars(teams) {
    const max = Math.max(...teams.map(t => t.avg));
    return `<div class="hbars">` + teams.map(t => {
      const w = (t.avg / max) * 100;
      const col = t.avg > 5 ? "#f76d6d" : t.avg > 3 ? "#f5b54a" : "#34d399";
      return `<div class="hbar" data-team="${t.team}">
        <div class="hb-label">${t.team}</div>
        <div class="hb-track"><div class="hb-fill" style="width:${w}%;background:${col}"></div></div>
        <div class="hb-val">${t.avg}d</div>
      </div>`;
    }).join("") + `</div>`;
  }

  function slaByTeamBars(teams) {
    const sorted = [...teams].sort((a,b)=>a.sla-b.sla);
    return `<div class="hbars">` + sorted.map(t => {
      const col = t.sla >= 80 ? "#34d399" : t.sla >= 60 ? "#f5b54a" : "#f76d6d";
      return `<div class="hbar" data-team="${t.team}">
        <div class="hb-label">${t.team}</div>
        <div class="hb-track"><div class="hb-fill" style="width:${t.sla}%;background:${col}"></div></div>
        <div class="hb-val">${t.sla}%</div>
      </div>`;
    }).join("") + `</div>`;
  }

  function personRanking(people) {
    const max = Math.max(...people.map(p => p.avg));
    return `<div class="lb">` + people.map((p, i) => {
      const col = p.avg > 5 ? "#f76d6d" : p.avg > 3 ? "#f5b54a" : "#34d399";
      const w = (p.avg/max)*100;
      return `<div class="lb-row" style="grid-template-columns:26px 1fr 120px 50px">
        <div class="lb-rank">${i+1}</div>
        <div><div class="lb-title">${p.person}</div><div class="lb-sub">${p.team} · ${p.count} ticket${p.count>1?"s":""}</div></div>
        <div class="hb-track" style="height:14px"><div class="hb-fill" style="width:${w}%;background:${col}"></div></div>
        <div class="lb-count" style="color:${col};text-align:right">${p.avg}d</div>
      </div>`;
    }).join("") + `</div>`;
  }

  function turnaroundTrend() {
    const data = D.TREND;
    const W = 480, H = 180, padL = 30, padR = 12, padT = 12, padB = 26;
    const iw = W - padL - padR, ih = H - padT - padB;
    const maxV = Math.max(...data.map(d => d.avgTurnaround)) + 1;
    const x = i => padL + (iw * i) / (data.length - 1);
    const y = v => padT + ih - (ih * v) / maxV;
    const pts = data.map((d, i) => `${x(i)},${y(d.avgTurnaround)}`).join(" ");
    const area = `${padL},${padT+ih} ${pts} ${x(data.length-1)},${padT+ih}`;
    let grid = "";
    for (let s = 0; s <= 3; s++) {
      const v = +((maxV * s) / 3).toFixed(1), yy = y(v);
      grid += `<line class="grid-line" x1="${padL}" y1="${yy}" x2="${W-padR}" y2="${yy}"/>
               <text class="axis-label" x="${padL-7}" y="${yy+3}" text-anchor="end">${v}</text>`;
    }
    let xlab = "";
    data.forEach((d,i)=>{ if(i%5===0||i===data.length-1) xlab+=`<text class="axis-label" x="${x(i)}" y="${H-7}" text-anchor="middle">${d.date.slice(5)}</text>`; });
    let dots = data.map((d,i)=>`<circle cx="${x(i)}" cy="${y(d.avgTurnaround)}" r="2.6" fill="#7c5cff"><title>${d.date}: ${d.avgTurnaround}d</title></circle>`).join("");
    return `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Average turnaround trend">
      <defs><linearGradient id="taG" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#7c5cff" stop-opacity=".5"/><stop offset="100%" stop-color="#7c5cff" stop-opacity="0"/>
      </linearGradient></defs>
      ${grid}
      <line class="axis-line" x1="${padL}" y1="${padT+ih}" x2="${W-padR}" y2="${padT+ih}"/>
      <polygon class="area-fill" points="${area}" fill="url(#taG)"/>
      <polyline class="line-path" points="${pts}" stroke="#7c5cff"/>
      ${dots}${xlab}
    </svg>`;
  }

  function wireSla() {
    $$("#view-sla [data-team]").forEach(el => el.addEventListener("click", () =>
      drillTo("team", el.dataset.team, "Team: " + el.dataset.team)));
    $$("#view-sla [data-bucket]").forEach(el => el.addEventListener("click", () => {
      // map bucket label to a custom filter via age range
      const b = el.dataset.bucket;
      activeFilter = { field: "bucket", value: b, label: "Aging bucket " + b };
      // extend passesFilter on the fly
      go("exceptions");
    }));
  }

  // ============================================================
  //  ADMIN
  // ============================================================
  function renderAdmin() {
    const el = $("#view-admin");
    el.innerHTML = `
      <div class="intro">
        <h2>Rule &amp; Routing Administration</h2>
        <p>Configure the validation rules the daily batch runs, the routing map that turns each error type into a JIRA ticket for the right team, and the SLA targets per severity. Changes here are mocked for the prototype.</p>
      </div>

      <div class="grid cols-2" style="margin-bottom:18px">
        <div class="card">
          <div class="card-h"><h3>Validation Rules</h3><span class="hint">click a row to edit</span></div>
          <div class="tbl-wrap">
            <table>
              <thead><tr><th>Rule</th><th>Type</th><th>Target Table</th><th>Severity</th><th>Enabled</th></tr></thead>
              <tbody id="rulesBody">
                ${D.RULES.map(r=>`<tr data-rule="${r.name}">
                  <td>${r.name.replace(/_/g," ")}</td>
                  <td class="mono">${r.type}</td>
                  <td class="mono">${r.table}</td>
                  <td><span class="badge sev-${r.severity}">${r.severity}</span></td>
                  <td><label class="switch"><input type="checkbox" ${r.enabled?"checked":""}/><span class="slider"></span></label></td>
                </tr>`).join("")}
              </tbody>
            </table>
          </div>
        </div>
        <div class="card">
          <div class="card-h"><h3>Edit Rule</h3><span class="hint" id="editHint">select a rule</span></div>
          <div id="editForm"></div>
        </div>
      </div>

      <div class="grid cols-2b">
        <div class="card">
          <div class="card-h"><h3>Routing Map</h3><span class="hint">error type → team → JIRA</span></div>
          <div class="tbl-wrap">
            <table>
              <thead><tr><th>Error Type</th><th>Team</th><th>Default Assignee</th><th>Project / Component</th></tr></thead>
              <tbody>
                ${D.ROUTING.map(r=>`<tr>
                  <td>${r.type.replace(/_/g," ")}</td>
                  <td>${r.team}</td>
                  <td>${r.assignee}</td>
                  <td class="mono">${r.project} / ${r.component}</td>
                </tr>`).join("")}
              </tbody>
            </table>
          </div>
        </div>
        <div class="card">
          <div class="card-h"><h3>SLA Targets per Severity</h3><span class="hint">resolution target (days)</span></div>
          <div class="tbl-wrap">
            <table>
              <thead><tr><th>Severity</th><th>Target</th><th>Editable</th></tr></thead>
              <tbody>
                ${Object.entries(D.SLA_TARGETS).map(([s,d])=>`<tr>
                  <td><span class="badge sev-${s}">${s}</span></td>
                  <td>${d} day${d>1?"s":""}</td>
                  <td><input type="number" value="${d}" min="1" style="width:70px;background:#0f1626;border:1px solid #1f2a44;color:#e7ecf6;border-radius:8px;padding:6px 8px"/></td>
                </tr>`).join("")}
              </tbody>
            </table>
          </div>
          <div class="note">Targets feed the SLA compliance calculations on the dashboard and Turnaround view.</div>
        </div>
      </div>
    `;
    showEditForm(D.RULES[0]);
    $$("#rulesBody tr[data-rule]").forEach(r => r.addEventListener("click", (ev) => {
      if (ev.target.closest(".switch")) return;
      showEditForm(D.RULES.find(x => x.name === r.dataset.rule));
    }));
  }
  function showEditForm(r) {
    $("#editHint").textContent = r.name;
    $("#editForm").innerHTML = `
      <div class="edit-form">
        <div class="fld full"><label>Rule name</label><input value="${r.name}"/></div>
        <div class="fld"><label>Type</label>
          <select>${["NOT_NULL","REFERENTIAL","RECONCILIATION","RANGE"].map(t=>`<option ${t===r.type?"selected":""}>${t}</option>`).join("")}</select></div>
        <div class="fld"><label>Severity</label>
          <select>${["Critical","High","Medium","Low"].map(s=>`<option ${s===r.severity?"selected":""}>${s}</option>`).join("")}</select></div>
        <div class="fld full"><label>Target table</label>
          <select>${["unified_ledger","po_table"].map(t=>`<option ${t===r.table?"selected":""}>${t}</option>`).join("")}</select></div>
        <div class="fld full"><label>Description</label><textarea rows="2">${r.description}</textarea></div>
        <div class="fld full" style="display:flex;gap:10px;align-items:center">
          <button class="btn primary" id="saveRule">Save rule</button>
          <button class="btn" id="testRule">Dry-run on 2026-06-07</button>
          <span class="note" style="margin:0">Mock — not persisted.</span>
        </div>
      </div>`;
    $("#saveRule").addEventListener("click", () => alert("Saved " + r.name + " (mock)."));
    $("#testRule").addEventListener("click", () => alert("Dry-run of " + r.name + " on run_date 2026-06-07: would flag matching rows (mock)."));
  }

  // ============================================================
  //  Init
  // ============================================================
  renderDashboard();
  renderSla();
  renderAdmin();
  go("dashboard");
})();
