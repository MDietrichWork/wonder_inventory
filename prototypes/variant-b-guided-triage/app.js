/* =========================================================
   Wonder DQ Console — Variant B (Guided Triage)
   Vanilla JS. Client-side view switching, no router, no fetch.
   ========================================================= */
(function () {
  "use strict";

  // ---------- tiny helpers ----------
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const el = (tag, cls, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  };
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const initials = name => name.split(" ").map(p => p[0]).slice(0, 2).join("").toUpperCase();
  const statusClass = s => "st-" + s.replace(/[^A-Za-z]/g, "");

  let toastTimer;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 2200);
  }

  // ---------- state ----------
  const reviewed = new Set();   // exception ids reviewed this session
  let queue = [];               // filtered exception list
  let idx = 0;                  // current card index within queue
  let listMode = false;

  // ===========================================================
  //  NAVIGATION
  // ===========================================================
  function showView(name) {
    $$(".view").forEach(v => { v.hidden = v.id !== "view-" + name; });
    $$(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.view === name));
    if (name === "triage") rebuildQueue();
    window.scrollTo(0, 0);
  }
  $$("[data-view]").forEach(b => b.addEventListener("click", () => showView(b.dataset.view)));

  // ===========================================================
  //  HOME
  // ===========================================================
  function renderHome() {
    $("#homeOpenCount").textContent = DATA.kpis.openExceptions;
    $("#homeNewToday").textContent = DATA.kpis.newToday;
    $("#homeAutoClosed").textContent = DATA.kpis.autoClosedToday;
    $("#homeSla").textContent = DATA.kpis.pctWithinSla + "%";
    $("#runDateFoot").textContent = DATA.runDate;
    // nav badge = number of actionable (not yet reviewed) exceptions
    $("#navTriageBadge").textContent = DATA.exceptions.length;
  }

  // ===========================================================
  //  EXCEPTION TRIAGE
  // ===========================================================
  function activeFilters() {
    const scope = $('input[name="f-scope"]:checked').value;
    const team = $("#f-team").value;
    const sev = $$(".f-sev:checked").map(c => c.value);
    const status = $$(".f-status:checked").map(c => c.value);
    return { scope, team, sev, status };
  }

  function rebuildQueue() {
    const f = activeFilters();
    queue = DATA.exceptions.filter(e => {
      if (f.scope === "myteam" && e.team !== f.team) return false;
      if (!f.sev.includes(e.severity)) return false;
      if (!f.status.includes(e.status)) return false;
      return true;
    });
    if (idx >= queue.length) idx = Math.max(0, queue.length - 1);
    if (listMode) renderList(); else renderCard();
  }

  function recurrenceFor(e) {
    return DATA.recurrence.find(r => r.type === e.type && r.facility === e.facility);
  }

  function renderCard() {
    const slot = $("#cardSlot");
    slot.innerHTML = "";

    // progress
    const total = queue.length;
    const human = total ? (idx + 1) : 0;
    $("#progressText").textContent = total
      ? `Exception ${human} of ${total}`
      : "No exceptions match your filters";
    $("#progressFill").style.width = total ? `${(reviewed.size / DATA.exceptions.length) * 100}%` : "0%";
    $("#progressSub").textContent = `${reviewed.size} reviewed in this session`;

    if (!total) {
      slot.appendChild(buildEmpty());
      $("#prevBtn").disabled = true;
      $("#skipBtn").disabled = true;
      return;
    }
    $("#prevBtn").disabled = idx === 0;
    $("#skipBtn").disabled = total <= 1;

    const e = queue[idx];
    const ticket = e.ticket ? DATA.ticketsByKey[e.ticket] : null;
    const rec = recurrenceFor(e);

    const card = el("div", "ex-card");

    // top bar
    const top = el("div", "ex-top");
    top.appendChild(el("span", "sev-badge sev-" + e.severity,
      `<span class="dot dot-${e.severity.toLowerCase()}"></span>${e.severity}`));
    top.appendChild(el("span", "ex-meta-chip", esc(DATA.facilities[e.facility]) + ` · ${e.facility}`));
    top.appendChild(el("span", "ex-meta-chip", "Source: " + esc(e.system)));
    top.appendChild(el("span", "ex-id", esc(e.id) + " · " + esc(e.ruleName)));
    card.appendChild(top);

    // body
    const body = el("div", "ex-body");
    body.appendChild(el("h2", "ex-headline", esc(e.headline)));

    if (rec) {
      body.appendChild(el("div", "recur-flag",
        `🔁 Heads up — this kind of error (<strong>${esc(DATA.rulesById[e.type].name)}</strong> at ${esc(e.facility)}) has happened <strong>${rec.count} times</strong> in the last ${esc(rec.window)}. It may need a permanent fix, not just a one-off.`));
    }

    const rule = DATA.rulesById[e.type];
    const why = el("div", "ex-why",
      `<span class="why-label">Why this matters</span>${esc(rule.why)}`);
    body.appendChild(why);

    // data fields
    const data = el("div", "ex-data");
    Object.keys(e.fields).forEach(k => {
      const v = e.fields[k];
      const blank = /^\(blank\)$|no matching row|unresolved|\(missing\)/i.test(v);
      const field = el("div", "ex-field");
      field.appendChild(el("div", "fk", esc(k)));
      field.appendChild(el("div", "fv" + (blank ? " blank" : ""), esc(v)));
      data.appendChild(field);
    });
    body.appendChild(data);

    // assignment row
    const arow = el("div", "assign-row");
    arow.appendChild(el("span", "avatar", initials(e.assignee)));
    const at = el("div", "assign-text");
    at.appendChild(el("div", "at-name", esc(e.assignee)));
    at.appendChild(el("div", "at-team", esc(e.team)));
    arow.appendChild(at);

    const jira = el("div", "jira-chip");
    if (ticket) {
      jira.appendChild(el("span", "jira-key", esc(ticket.key)));
      jira.appendChild(el("span", "status-chip " + statusClass(ticket.status), esc(ticket.status)));
    } else {
      jira.appendChild(el("span", "no-ticket", "No ticket yet — confirming will open one"));
    }
    arow.appendChild(jira);
    body.appendChild(arow);

    // actions
    const actions = el("div", "ex-actions");
    const confirm = el("button", "btn btn-primary", "✓ Looks right — route it");
    confirm.addEventListener("click", () => doConfirm(e));
    const reassign = el("button", "btn", "Reassign");
    reassign.addEventListener("click", () => openReassign(e));
    const note = el("button", "btn", "Add note");
    note.addEventListener("click", () => openNote(e));
    const jiraBtn = el("button", "btn btn-ghost", "↗ Open in JIRA");
    jiraBtn.addEventListener("click", () =>
      toast(ticket ? `Would open ${ticket.key} in JIRA (mock)` : "No ticket yet — confirm to create one (mock)"));
    actions.append(confirm, reassign, note, jiraBtn);
    body.appendChild(actions);

    card.appendChild(body);
    slot.appendChild(card);
  }

  function buildEmpty() {
    const e = el("div", "empty-state");
    e.innerHTML = `<div class="es-emoji">🎉</div>
      <h3>Nothing here right now</h3>
      <p>No exceptions match your current filters. Try widening them on the left, or you're all caught up.</p>`;
    return e;
  }

  function advance() {
    if (idx < queue.length - 1) { idx++; }
    else { idx = Math.min(idx, queue.length - 1); }
    renderCard();
  }

  function markReviewed(e) {
    reviewed.add(e.id);
    $("#navTriageBadge").textContent = Math.max(0, DATA.exceptions.length - reviewed.size);
  }

  function doConfirm(e) {
    markReviewed(e);
    toast(e.ticket
      ? `Confirmed — ${e.ticket} routed to ${e.assignee}`
      : `Confirmed — new ticket opened for ${e.assignee}`);
    advance();
  }

  $("#prevBtn").addEventListener("click", () => { if (idx > 0) { idx--; renderCard(); } });
  $("#skipBtn").addEventListener("click", () => { advance(); });

  // filters
  $$('input[name="f-scope"], .f-sev, .f-status, #f-team').forEach(c =>
    c.addEventListener("change", () => { idx = 0; rebuildQueue(); }));
  $("#resetFilters").addEventListener("click", () => {
    $('input[name="f-scope"][value="all"]').checked = true;
    $$(".f-sev, .f-status").forEach(c => c.checked = true);
    idx = 0; rebuildQueue();
    toast("Filters reset");
  });

  // view toggle
  $("#toggleCard").addEventListener("click", () => setMode(false));
  $("#toggleList").addEventListener("click", () => setMode(true));
  function setMode(list) {
    listMode = list;
    $("#toggleCard").classList.toggle("active", !list);
    $("#toggleList").classList.toggle("active", list);
    $("#cardMode").hidden = list;
    $("#listMode").hidden = !list;
    if (list) renderList(); else renderCard();
  }

  function renderList() {
    const tb = $("#listBody");
    tb.innerHTML = "";
    const total = queue.length;
    $("#progressText").textContent = total ? `${total} exceptions in your queue` : "No exceptions match your filters";
    $("#progressFill").style.width = `${(reviewed.size / DATA.exceptions.length) * 100}%`;
    $("#progressSub").textContent = `${reviewed.size} reviewed in this session`;

    if (!total) {
      tb.appendChild(el("tr", null, `<td colspan="7" style="text-align:center;color:var(--muted);padding:28px">No exceptions match your filters.</td>`));
      return;
    }
    queue.forEach((e, i) => {
      const ticket = e.ticket ? DATA.ticketsByKey[e.ticket] : null;
      const tr = el("tr");
      tr.innerHTML =
        `<td>${esc(e.headline)}</td>
         <td>${esc(e.facility)}</td>
         <td><span class="sev-badge sev-${e.severity}"><span class="dot dot-${e.severity.toLowerCase()}"></span>${e.severity}</span></td>
         <td>${esc(e.team)}</td>
         <td>${ticket ? `<span class="jira-key">${esc(ticket.key)}</span>` : '<span class="no-ticket">—</span>'}</td>
         <td><span class="status-chip ${statusClass(e.status)}">${esc(e.status)}</span></td>`;
      const td = el("td");
      const open = el("button", "link-btn", "Open card");
      open.addEventListener("click", () => { idx = i; setMode(false); });
      td.appendChild(open);
      tr.appendChild(td);
      tb.appendChild(tr);
    });
  }

  // ---------- reassign modal ----------
  let reassignTarget = null;
  function openReassign(e) {
    reassignTarget = e;
    const teamSel = $("#ra-team");
    teamSel.innerHTML = Object.keys(DATA.teams).map(t =>
      `<option ${t === e.team ? "selected" : ""}>${esc(t)}</option>`).join("");
    fillPeople(e.team, e.assignee);
    teamSel.onchange = () => fillPeople(teamSel.value);
    $("#reassignModal").hidden = false;
  }
  function fillPeople(team, sel) {
    $("#ra-person").innerHTML = DATA.teams[team].map(p =>
      `<option ${p === sel ? "selected" : ""}>${esc(p)}</option>`).join("");
  }
  $("#reassignCancel").addEventListener("click", () => $("#reassignModal").hidden = true);
  $("#reassignSave").addEventListener("click", () => {
    const team = $("#ra-team").value, person = $("#ra-person").value;
    if (reassignTarget) { reassignTarget.team = team; reassignTarget.assignee = person; }
    $("#reassignModal").hidden = true;
    markReviewed(reassignTarget);
    toast(`Reassigned to ${person} (${team})`);
    renderCard();
  });

  // ---------- note modal ----------
  let noteTarget = null;
  function openNote(e) {
    noteTarget = e;
    $("#noteFor").textContent = `${e.id} — ${e.headline}`;
    $("#noteText").value = "";
    $("#noteModal").hidden = false;
    setTimeout(() => $("#noteText").focus(), 50);
  }
  $("#noteCancel").addEventListener("click", () => $("#noteModal").hidden = true);
  $("#noteSave").addEventListener("click", () => {
    $("#noteModal").hidden = true;
    toast("Note saved (mock)");
  });

  // ===========================================================
  //  DASHBOARD
  // ===========================================================
  function renderDashboard() {
    const k = DATA.kpis;
    const tiles = [
      { big: k.openExceptions, label: "open exceptions", cls: "" },
      { big: k.newToday, label: "new today", cls: "" },
      { big: k.autoClosedToday, label: "auto-closed recently", cls: "k-good" },
      { big: k.avgTurnaroundDays + "d", label: "avg turnaround", cls: "" },
      { big: k.pctWithinSla + "%", label: "within SLA", cls: k.pctWithinSla >= 80 ? "k-good" : "k-warn" }
    ];
    $("#kpiRow").innerHTML = tiles.map(t =>
      `<div class="kpi ${t.cls}"><div class="k-big">${t.big}</div><div class="k-label">${t.label}</div></div>`).join("");

    renderTrend();
    renderBars("#byTypeChart", DATA.errorsByType.map(d => ({
      label: DATA.rulesById[d.key].name, count: d.count })), "");
    renderBars("#byFacilityChart", DATA.errorsByFacility.map(d => ({
      label: d.key, count: d.count })), "teal");

    // recurrence
    const rl = $("#recurList");
    rl.innerHTML = "";
    DATA.recurrence.forEach(r => {
      const item = el("div", "recur-item");
      item.innerHTML =
        `<div class="recur-count">${r.count}×</div>
         <div class="recur-main">
           <div class="rm-title">${esc(DATA.rulesById[r.type].name)} @ ${esc(r.facility)}</div>
           <div class="rm-note">${esc(r.note)} (${esc(r.window)})</div>
         </div>`;
      rl.appendChild(item);
    });
  }

  function renderBars(sel, rows, tone) {
    const max = Math.max.apply(null, rows.map(r => r.count));
    $(sel).innerHTML = rows.map(r =>
      `<div class="bar-row">
         <div>${esc(r.label)}</div>
         <div class="bar-track"><div class="bar-fill ${tone}" style="width:${(r.count / max) * 100}%"></div></div>
         <div class="bar-count">${r.count}</div>
       </div>`).join("");
  }

  function renderTrend() {
    const data = DATA.trend;
    const W = 560, H = 180, padL = 28, padB = 24, padT = 12, padR = 10;
    const max = Math.max.apply(null, data.map(d => d.count)) * 1.15;
    const innerW = W - padL - padR, innerH = H - padT - padB;
    const x = i => padL + (i / (data.length - 1)) * innerW;
    const y = v => padT + innerH - (v / max) * innerH;

    const linePts = data.map((d, i) => `${x(i)},${y(d.count)}`).join(" ");
    const areaPts = `${padL},${padT + innerH} ${linePts} ${x(data.length - 1)},${padT + innerH}`;

    // gridlines
    let grid = "";
    for (let g = 0; g <= 3; g++) {
      const gy = padT + (innerH / 3) * g;
      grid += `<line x1="${padL}" y1="${gy}" x2="${W - padR}" y2="${gy}" stroke="#ece8e0" stroke-width="1"/>`;
    }
    const dots = data.map((d, i) =>
      `<circle cx="${x(i)}" cy="${y(d.count)}" r="3" fill="#e07a3f"/>`).join("");
    const labels = data.map((d, i) =>
      (i % 2 === 0) ? `<text class="trend-axis" x="${x(i)}" y="${H - 8}" text-anchor="middle">${d.date}</text>` : "").join("");

    $("#trendChart").innerHTML =
      `<svg viewBox="0 0 ${W} ${H}" class="trend-svg" role="img" aria-label="Daily error count trend">
         ${grid}
         <polygon points="${areaPts}" fill="rgba(224,122,63,.12)"/>
         <polyline points="${linePts}" fill="none" stroke="#e07a3f" stroke-width="2.5" stroke-linejoin="round"/>
         ${dots}${labels}
       </svg>`;
  }

  // ===========================================================
  //  SLA
  // ===========================================================
  function renderSla() {
    // by team
    const st = $("#slaTeam"); st.innerHTML = "";
    DATA.slaByTeam.forEach(t => {
      const totalClosed = t.within + t.breaching;
      const wPct = totalClosed ? (t.within / totalClosed) * 100 : 0;
      const bPct = totalClosed ? (t.breaching / totalClosed) * 100 : 0;
      const needs = t.breaching >= 2;
      const row = el("div", "sla-team-row");
      row.innerHTML =
        `<div class="str-top">
           <div class="str-name">${esc(t.team)}${needs ? '<span class="attention-tag">needs attention</span>' : ''}</div>
           <div class="str-avg">avg ${t.avgDays}d · ${t.open} open</div>
         </div>
         <div class="str-bar">
           <div class="str-within" style="width:${wPct}%"></div>
           <div class="str-breach" style="width:${bPct}%"></div>
         </div>
         <div class="str-meta">${t.within} within SLA · ${t.breaching} breaching</div>`;
      st.appendChild(row);
    });

    // by person
    const sp = $("#slaPerson"); sp.innerHTML = "";
    DATA.slaByPerson.slice().sort((a, b) => b.avgDays - a.avgDays).forEach(p => {
      const totalClosed = p.within + p.breaching;
      const wPct = totalClosed ? (p.within / totalClosed) * 100 : 0;
      const bPct = totalClosed ? (p.breaching / totalClosed) * 100 : 0;
      const needs = p.breaching >= 1 && p.avgDays > 3;
      const row = el("div", "sla-team-row");
      row.innerHTML =
        `<div class="str-top">
           <div class="str-name">${esc(p.person)}${needs ? '<span class="attention-tag">needs attention</span>' : ''}</div>
           <div class="str-avg">avg ${p.avgDays}d</div>
         </div>
         <div class="str-bar">
           <div class="str-within" style="width:${wPct}%"></div>
           <div class="str-breach" style="width:${bPct}%"></div>
         </div>
         <div class="str-meta">${esc(p.team)} · ${p.within} within · ${p.breaching} breaching</div>`;
      sp.appendChild(row);
    });

    // aging
    const max = Math.max.apply(null, DATA.aging.map(a => a.count));
    $("#agingChart").innerHTML = DATA.aging.map(a =>
      `<div class="bar-row">
         <div>${esc(a.bucket)}</div>
         <div class="bar-track"><div class="bar-fill" style="width:${(a.count / max) * 100}%;background:${a.tone === 'bad' ? 'var(--bad)' : a.tone === 'warn' ? 'var(--warn)' : 'var(--ok)'}"></div></div>
         <div class="bar-count">${a.count}</div>
       </div>`).join("");

    // overdue tickets
    const ol = $("#overdueList"); ol.innerHTML = "";
    DATA.overdue.forEach(key => {
      const t = DATA.ticketsByKey[key];
      if (!t) return;
      const target = DATA.sla[t.severity];
      const ageDays = Math.round((new Date(DATA.today) - new Date(t.created)) / 86400000);
      const item = el("div", "overdue-item");
      item.innerHTML =
        `<span class="status-chip ${statusClass(t.status)}">${esc(t.status)}</span>
         <div>
           <div><span class="jira-key">${esc(t.key)}</span> · ${esc(DATA.rulesById[t.type].name)}</div>
           <div class="str-meta">${esc(t.assignee)} (${esc(t.team)}) · open ${ageDays}d · ${t.severity} target ${target}d</div>
         </div>
         <span class="attention-tag" style="margin-left:auto">${ageDays - target}d over</span>`;
      ol.appendChild(item);
    });
  }

  // ===========================================================
  //  ADMIN
  // ===========================================================
  let editingRule = null;
  function renderAdmin() {
    // rules
    const rb = $("#rulesBody"); rb.innerHTML = "";
    DATA.rules.forEach(r => {
      const tr = el("tr");
      tr.innerHTML =
        `<td><strong>${esc(r.name)}</strong><br><span class="str-meta">${esc(r.id)}</span></td>
         <td><span class="type-tag">${esc(r.type)}</span></td>
         <td class="mono">${esc(r.table)}</td>
         <td><span class="sev-badge sev-${r.severity}"><span class="dot dot-${r.severity.toLowerCase()}"></span>${r.severity}</span></td>
         <td><label class="toggle-switch"><input type="checkbox" ${r.enabled ? "checked" : ""} data-rule="${r.id}"><span class="slider"></span></label></td>`;
      const td = el("td");
      const edit = el("button", "link-btn", "Edit");
      edit.addEventListener("click", () => openRuleModal(r));
      td.appendChild(edit);
      tr.appendChild(td);
      rb.appendChild(tr);
    });
    $$('input[data-rule]').forEach(c => c.addEventListener("change", () => {
      const r = DATA.rulesById[c.dataset.rule];
      r.enabled = c.checked;
      toast(`${r.name} ${c.checked ? "enabled" : "disabled"} (mock)`);
    }));

    // routing
    const route = $("#routeBody"); route.innerHTML = "";
    DATA.rules.forEach(r => {
      route.appendChild(el("tr", null,
        `<td><span class="type-tag">${esc(r.id)}</span></td>
         <td>${esc(r.team)}</td>
         <td>${esc(r.assignee)}</td>
         <td class="mono">${esc(r.jiraProject)} / ${esc(r.component)}</td>`));
    });

    // sla targets
    const stb = $("#slaTargetBody"); stb.innerHTML = "";
    Object.keys(DATA.sla).forEach(sev => {
      stb.appendChild(el("tr", null,
        `<td><span class="sev-badge sev-${sev}"><span class="dot dot-${sev.toLowerCase()}"></span>${sev}</span></td>
         <td>resolve within <strong>${DATA.sla[sev]} day${DATA.sla[sev] > 1 ? "s" : ""}</strong></td>`));
    });
  }

  function openRuleModal(r) {
    editingRule = r;
    $("#rf-name").value = r.name;
    $("#rf-table").value = r.table;
    $("#rf-sev").value = r.severity;
    $("#rf-team").value = r.team;
    $("#rf-enabled").checked = r.enabled;
    $("#ruleModal").hidden = false;
  }
  $("#ruleCancel").addEventListener("click", () => $("#ruleModal").hidden = true);
  $("#ruleForm").addEventListener("submit", ev => {
    ev.preventDefault();
    if (editingRule) {
      editingRule.name = $("#rf-name").value;
      editingRule.table = $("#rf-table").value;
      editingRule.severity = $("#rf-sev").value;
      editingRule.team = $("#rf-team").value;
      editingRule.enabled = $("#rf-enabled").checked;
    }
    $("#ruleModal").hidden = true;
    renderAdmin();
    toast("Rule saved (mock)");
  });

  // close modals on overlay click / Esc
  $$(".modal-overlay").forEach(ov => ov.addEventListener("click", e => {
    if (e.target === ov) ov.hidden = true;
  }));
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") $$(".modal-overlay").forEach(ov => ov.hidden = true);
  });

  // ===========================================================
  //  INIT — render every view once so switching is instant
  // ===========================================================
  renderHome();
  renderDashboard();
  renderSla();
  renderAdmin();
  rebuildQueue();
  showView("home");
})();
