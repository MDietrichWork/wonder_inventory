/* Wonder Inventory Data-Quality Console — Variant B (Inbox + Detail Panel)
   Vanilla JS, file:// safe, client-side view switching, no fetch. */
(function () {
  "use strict";

  const D = window.DATA;
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.prototype.slice.call((r || document).querySelectorAll(s));
  const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const initials = (n) => n.split(" ").map(p => p[0]).join("").slice(0, 2).toUpperCase();
  const statusClass = (s) => "st-" + s.replace(/[\s-]/g, "");

  // ---------- Inline SVG icons (16px, currentColor, ~1.5 stroke) ----------
  const I = {
    inbox: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
    chart: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="3" x2="3" y2="21"/><line x1="3" y1="21" x2="21" y2="21"/><rect x="7" y="11" width="3" height="7"/><rect x="12" y="7" width="3" height="11"/><rect x="17" y="13" width="3" height="5"/></svg>',
    clock: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/></svg>',
    sliders: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>',
    search: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    check: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    user: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    note: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4z"/></svg>',
    external: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
    repeat: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>',
    info: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    arrow: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="13 6 19 12 13 18"/></svg>',
    db: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.66 3.58 3 8 3s8-1.34 8-3V5"/><path d="M4 11v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6"/></svg>',
    route: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="19" r="3"/><circle cx="18" cy="5" r="3"/><path d="M15 5H9a3 3 0 0 0-3 3v8"/></svg>'
  };

  // attach nav icons
  const navIcons = { inbox: I.inbox, reporting: I.chart, sla: I.clock, admin: I.sliders };
  $$(".nav-item").forEach(b => { const v = b.getAttribute("data-view"); $(".nico", b).innerHTML = navIcons[v] || ""; });
  $(".list-search .search-ico").innerHTML = I.search;

  // ---------- Date helpers ----------
  const TODAY = new Date(D.today + "T00:00:00");
  function ageDays(created) {
    const c = new Date(created + "T00:00:00");
    return Math.max(0, Math.round((TODAY - c) / 86400000));
  }
  function ticketOf(ex) { return ex.ticket ? D.ticketsByKey[ex.ticket] : null; }
  function isOpenStatus(s) { return s === "Open" || s === "In Progress" || s === "In Review"; }
  function recurrenceFor(ex) { return D.recurrenceKey[ex.type + "|" + ex.facility] || null; }
  function isOverdue(ex) {
    const t = ticketOf(ex);
    if (!t || !isOpenStatus(t.status)) return false;
    return ageDays(t.created) > D.sla[ex.severity];
  }

  // session-local notes per exception id
  const sessionNotes = {};

  // ---------- Toast ----------
  let toastTimer = null;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg; t.hidden = false;
    requestAnimationFrame(() => t.classList.add("show"));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.classList.remove("show"); setTimeout(() => { t.hidden = true; }, 200); }, 2400);
  }

  // ========================================================================
  //  VIEW SWITCHING
  // ========================================================================
  const views = { inbox: "#view-inbox", reporting: "#view-reporting", sla: "#view-sla", admin: "#view-admin" };
  let built = {};
  function switchView(name) {
    $$(".nav-item").forEach(b => {
      const on = b.getAttribute("data-view") === name;
      b.classList.toggle("active", on);
      if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    Object.keys(views).forEach(k => {
      const sec = $(views[k]);
      const on = k === name;
      sec.classList.toggle("active", on);
      sec.hidden = !on;
    });
    if (name === "reporting" && !built.reporting) { renderReporting(); built.reporting = true; }
    if (name === "sla" && !built.sla) { renderSla(); built.sla = true; }
    if (name === "admin" && !built.admin) { renderAdmin(); built.admin = true; }
  }
  $$(".nav-item").forEach(b => b.addEventListener("click", () => switchView(b.getAttribute("data-view"))));

  // ========================================================================
  //  INBOX
  // ========================================================================
  let currentFolder = "open";
  let searchTerm = "";
  let selectedId = null;
  let visibleList = [];

  function matchesFolder(ex, folder) {
    const t = ticketOf(ex);
    switch (folder) {
      case "open": return ex.status !== "Resolved" && ex.status !== "Closed" && ex.status !== "Auto-Closed";
      case "myteam": return ex.team === "Data Engineering" && isOpenStatus(ex.status); // demo: viewer's adjacent team
      case "critical": return ex.severity === "Critical" && isOpenStatus(ex.status);
      case "recurring": return !!recurrenceFor(ex) && isOpenStatus(ex.status);
      case "autoclosed": return ex.status === "Auto-Closed" || (t && t.status === "Auto-Closed");
      default: return true;
    }
  }
  function matchesSearch(ex, term) {
    if (!term) return true;
    const hay = [ex.headline, ex.facility, ex.system, ex.ruleName, ex.type, ex.assignee, ex.team, ex.ticket || "",
      JSON.stringify(ex.fields)].join(" ").toLowerCase();
    return hay.indexOf(term) !== -1;
  }

  function computeList() {
    visibleList = D.exceptions.filter(ex => matchesFolder(ex, currentFolder) && matchesSearch(ex, searchTerm));
    // sort: open & severity first, then newest
    const sevRank = { Critical: 0, High: 1, Medium: 2, Low: 3 };
    visibleList.sort((a, b) => (sevRank[a.severity] - sevRank[b.severity]) || (a.id < b.id ? -1 : 1));
    return visibleList;
  }

  function folderCount(folder) { return D.exceptions.filter(ex => matchesFolder(ex, folder)).length; }

  function updateFolderCounts() {
    $("#fc-open").textContent = folderCount("open");
    $("#fc-myteam").textContent = folderCount("myteam");
    $("#fc-critical").textContent = folderCount("critical");
    $("#fc-recurring").textContent = folderCount("recurring");
    $("#fc-autoclosed").textContent = folderCount("autoclosed");
    $("#navInboxCount").textContent = folderCount("open");
  }

  function renderRows() {
    computeList();
    const ul = $("#rows");
    ul.innerHTML = "";
    $("#listMeta").textContent = visibleList.length + (visibleList.length === 1 ? " exception" : " exceptions");

    if (!visibleList.length) {
      const li = el("li", "", '<div style="padding:32px;text-align:center;color:var(--text-faint);font-size:12.5px">No exceptions match this folder or search.</div>');
      ul.appendChild(li);
      return;
    }

    visibleList.forEach(ex => {
      const t = ticketOf(ex);
      const status = t ? t.status : ex.status;
      const rec = recurrenceFor(ex);
      const over = isOverdue(ex);
      const age = t ? ageDays(t.created) : null;

      const li = el("li", "row" + (ex.ticket ? "" : " unticketed") + (ex.id === selectedId ? " selected" : ""));
      li.setAttribute("role", "option");
      li.setAttribute("tabindex", "-1");
      li.setAttribute("aria-selected", ex.id === selectedId ? "true" : "false");
      li.dataset.id = ex.id;

      li.innerHTML =
        '<span class="sev-strip ' + ex.severity + '" aria-hidden="true"></span>' +
        '<div class="row-inner">' +
          '<div class="row-top">' +
            (ex.newToday ? '<span class="new-dot" title="New today" aria-label="New today"></span>' : '') +
            '<span class="row-title">' + esc(ex.headline) + '</span>' +
            '<span class="status ' + statusClass(status) + '">' + esc(status) + '</span>' +
          '</div>' +
          '<div class="row-sub">' +
            '<span class="sev-dot ' + ex.severity + '" aria-hidden="true"></span>' +
            '<span>' + esc(ex.ruleName) + '</span>' +
            '<span class="sep">·</span>' +
            '<span class="mono">' + esc(ex.facility) + '</span>' +
            '<span class="sep">·</span>' +
            '<span>' + esc(ex.system) + '</span>' +
          '</div>' +
          '<div class="row-meta">' +
            '<span class="tag">' + I.user + '&nbsp;' + esc(ex.assignee.split(" ")[0]) + '</span>' +
            (ex.ticket ? '<span class="tag mono">' + esc(ex.ticket) + '</span>' : '<span class="tag" style="color:var(--text-faint)">No ticket</span>') +
            (age != null ? '<span class="age ' + (over ? 'over' : '') + '">' + age + 'd old' + (over ? ' · SLA breach' : '') + '</span>' : '') +
            (rec ? '<span class="recur-badge">' + I.repeat + ' ' + rec.count + '× in 30d</span>' : '') +
          '</div>' +
        '</div>';

      li.addEventListener("click", () => selectRow(ex.id));
      ul.appendChild(li);
    });
  }

  function selectRow(id, scroll) {
    selectedId = id;
    $$("#rows .row").forEach(r => {
      const on = r.dataset.id === id;
      r.classList.toggle("selected", on);
      r.setAttribute("aria-selected", on ? "true" : "false");
      if (on && scroll) r.scrollIntoView({ block: "nearest" });
    });
    renderDetail(D.exceptions.find(e => e.id === id));
  }

  // ---------- Detail panel ----------
  function renderDetail(ex) {
    const empty = $("#detailEmpty");
    const body = $("#detailBody");
    if (!ex) { empty.hidden = false; body.hidden = true; return; }
    empty.hidden = true; body.hidden = false;

    const rule = D.rulesById[ex.type];
    const t = ticketOf(ex);
    const status = t ? t.status : ex.status;
    const rec = recurrenceFor(ex);
    const over = isOverdue(ex);

    // fields
    const fieldsHtml = Object.keys(ex.fields).map(k => {
      const v = String(ex.fields[k]);
      const missing = /\(blank\)|no matching row|unresolved|missing|^EXP-0\b/i.test(v) || v === "";
      const showVal = v === "" ? "(blank)" : v;
      return '<div class="k">' + esc(k) + '</div>' +
        '<div class="v' + (missing ? ' flag' : '') + '">' + esc(showVal) +
        (missing ? '<span class="miss-tag">missing</span>' : '') + '</div>';
    }).join("");

    // timeline
    let timelineHtml = '<div class="tip" style="color:var(--text-faint);font-size:12px">No JIRA ticket yet. This exception is queued for routing on confirmation.</div>';
    let jiraHeader = '<span class="jira-key none">No ticket created</span>';
    let autoNote = "";
    if (t) {
      const isAuto = t.status === "Auto-Closed";
      if (isAuto) {
        autoNote = '<div class="autoclose-note">' + I.check +
          '<div><b>Auto-closed.</b> The issue was no longer reproduced in a later validation run, so the system closed this automatically — no manual action was required.</div></div>';
      }
      jiraHeader =
        '<span class="jira-key">' + esc(t.key) + '</span>' +
        '<span class="status ' + statusClass(t.status) + '">' + esc(t.status) + '</span>' +
        '<span class="spacer"></span>' +
        '<span class="tip" style="font-size:11px;color:var(--text-faint)">' + esc(rule.jiraProject) + ' · ' + esc(rule.component) + '</span>';
      timelineHtml = '<ul class="timeline">' + t.timeline.map(step => {
        const auto = /Auto-Closed/.test(step.s);
        return '<li class="' + (auto ? 'auto' : '') + '">' +
          '<span class="tdot" aria-hidden="true"></span>' +
          '<div class="tstatus">' + esc(step.s) + (auto ? '<span class="auto-flag">AUTO</span>' : '') + '</div>' +
          '<div class="tmeta">' + esc(step.d) + '</div>' +
          '<div class="tnote">' + esc(step.note) + '</div>' +
        '</li>';
      }).join("") + '</ul>';
    }

    // notes
    const notes = sessionNotes[ex.id] || [];
    const notesHtml = notes.map(n =>
      '<li class="note"><div class="nm">' + esc(n.who) + ' · just now</div>' + esc(n.text) + '</li>').join("");

    body.innerHTML =
      '<div class="detail-scroll">' +
        '<div class="dh-top">' +
          '<span class="pill sev-pill ' + ex.severity + '"><span class="sev-dot ' + ex.severity + '"></span>' + esc(ex.severity) + '</span>' +
          '<span class="status ' + statusClass(status) + '">' + esc(status) + '</span>' +
          (ex.newToday ? '<span class="tag" style="color:var(--accent);background:var(--accent-soft)">New today</span>' : '') +
          (over ? '<span class="recur-badge" style="background:var(--crit-soft);color:var(--crit)">SLA breached</span>' : '') +
          '<span style="flex:1"></span>' +
          '<span class="dh-id">' + esc(ex.id) + '</span>' +
        '</div>' +
        '<h1 class="dh-headline">' + esc(ex.headline) + '</h1>' +
        '<div class="row-sub" style="font-size:12.5px"><span class="mono">' + esc(ex.facility) + '</span> · ' +
          esc(D.facilities[ex.facility]) + ' · <span>' + esc(ex.system) + '</span></div>' +

        '<div class="why">' +
          '<div class="why-lab">' + I.info + ' Why this matters</div>' +
          '<p>' + esc(rule.why) + '</p>' +
          '<p class="plain">' + esc(rule.plain) + '</p>' +
        '</div>' +

        '<div class="section">' +
          '<h3>' + I.db + ' Offending record &nbsp;<span style="color:var(--text-faint);font-weight:500;text-transform:none;letter-spacing:0">source: ' + esc(ex.table) + '</span></h3>' +
          '<div class="kv">' + fieldsHtml + '</div>' +
        '</div>' +

        '<div class="section">' +
          '<h3>' + I.route + ' Routing</h3>' +
          '<div class="routing">' +
            '<div class="route-card"><div class="rc-lab">Owning team</div><div class="rc-val">' + esc(ex.team) + '</div>' +
              '<div class="rc-sub">Rule type ' + esc(ex.ruleType) + '</div></div>' +
            '<div class="route-card"><div class="rc-lab">Assignee</div>' +
              '<div class="rc-avatar"><span class="mini-avatar">' + esc(initials(ex.assignee)) + '</span>' +
              '<span class="rc-val" style="font-size:13px">' + esc(ex.assignee) + '</span></div>' +
              '<div class="rc-sub">SLA target ' + D.sla[ex.severity] + ' day' + (D.sla[ex.severity] > 1 ? 's' : '') + '</div></div>' +
          '</div>' +
        '</div>' +

        '<div class="section">' +
          '<h3>JIRA ticket</h3>' +
          '<div class="jira-card">' +
            autoNote +
            '<div class="jira-row">' + jiraHeader + '</div>' +
            timelineHtml +
          '</div>' +
        '</div>' +

        (rec ? '<div class="section"><h3>Recurrence</h3>' +
          '<div class="recur-summary"><div class="rs-head">' + I.repeat +
          ' Recurred <span class="rs-count">' + rec.count + '×</span> in the last ' + esc(rec.window) + '</div>' +
          '<div>' + esc(rec.note) + ' Same error type at <b>' + esc(rec.facility) + '</b> — a fix at the source would clear the pattern.</div></div></div>' : '') +

        '<div class="section">' +
          '<h3>' + I.note + ' Notes</h3>' +
          '<ul class="notes" id="noteList">' + (notesHtml || '<li class="tip" style="color:var(--text-faint);font-size:12px;list-style:none">No notes yet.</li>') + '</ul>' +
          '<div class="note-input"><input type="text" id="noteField" placeholder="Add a note…" aria-label="Add a note" /><button class="btn sm" id="noteAdd">' + I.note + ' Add</button></div>' +
        '</div>' +
      '</div>' +

      '<div class="detail-actions">' +
        '<button class="btn primary" id="actConfirm">' + I.check + ' Confirm routing</button>' +
        '<button class="btn" id="actReassign">' + I.user + ' Reassign</button>' +
        '<button class="btn" id="actNote">' + I.note + ' Add note</button>' +
        '<span class="spacer"></span>' +
        '<button class="btn ghost" id="actJira">' + I.external + ' Open in JIRA</button>' +
      '</div>';

    // wire actions
    $("#actConfirm").addEventListener("click", () => toast("Routing confirmed → " + ex.team + " · " + ex.assignee + " (mock)"));
    $("#actReassign").addEventListener("click", () => reassign(ex));
    $("#actJira").addEventListener("click", () => toast(ex.ticket ? "Opening " + ex.ticket + " in JIRA (mock)" : "No JIRA ticket yet — confirm routing to create one (mock)"));
    const addNote = () => {
      const f = $("#noteField");
      const txt = f.value.trim();
      if (!txt) { f.focus(); return; }
      (sessionNotes[ex.id] = sessionNotes[ex.id] || []).push({ who: "Mike Dietrich", text: txt });
      renderDetail(ex);
      toast("Note added (mock)");
    };
    $("#noteAdd").addEventListener("click", addNote);
    $("#noteField").addEventListener("keydown", e => { if (e.key === "Enter") addNote(); });
    $("#actNote").addEventListener("click", () => { $("#noteField").focus(); $("#noteField").scrollIntoView({ block: "center" }); });
  }

  function reassign(ex) {
    const all = [];
    Object.keys(D.teams).forEach(team => D.teams[team].forEach(p => all.push({ team, p })));
    const idx = all.findIndex(x => x.p === ex.assignee);
    const next = all[(idx + 1) % all.length];
    ex.assignee = next.p; ex.team = next.team;
    const t = ticketOf(ex);
    if (t) { t.assignee = next.p; t.team = next.team; }
    renderDetail(ex);
    renderRows(); selectRow(ex.id);
    toast("Reassigned to " + next.p + " · " + next.team + " (mock)");
  }

  // folder tabs
  $$(".folder").forEach(f => f.addEventListener("click", () => {
    currentFolder = f.getAttribute("data-folder");
    $$(".folder").forEach(x => { const on = x === f; x.classList.toggle("active", on); x.setAttribute("aria-selected", on ? "true" : "false"); });
    renderRows();
    // auto-select first row
    if (visibleList.length) selectRow(visibleList[0].id); else renderDetail(null);
  }));

  // search
  $("#inboxSearch").addEventListener("input", e => {
    searchTerm = e.target.value.trim().toLowerCase();
    renderRows();
  });

  // keyboard nav on list
  $("#rows").addEventListener("keydown", e => {
    if (!visibleList.length) return;
    let idx = visibleList.findIndex(x => x.id === selectedId);
    if (e.key === "ArrowDown") { e.preventDefault(); idx = Math.min(visibleList.length - 1, idx < 0 ? 0 : idx + 1); selectRow(visibleList[idx].id, true); }
    else if (e.key === "ArrowUp") { e.preventDefault(); idx = Math.max(0, idx < 0 ? 0 : idx - 1); selectRow(visibleList[idx].id, true); }
    else if (e.key === "Enter" && idx >= 0) { e.preventDefault(); renderDetail(visibleList[idx]); }
  });

  // ========================================================================
  //  REPORTING DASHBOARD
  // ========================================================================
  function bars(items, labelFn, max) {
    return '<div class="hbars">' + items.map(it => {
      const pct = Math.round((it.count / max) * 100);
      return '<div class="hbar"><span class="hlabel">' + esc(labelFn(it)) + '</span>' +
        '<span class="track"><span class="fill" style="width:' + pct + '%"></span></span>' +
        '<span class="hval">' + it.count + '</span></div>';
    }).join("") + '</div>';
  }

  function trendChart() {
    const data = D.trend, W = 640, H = 180, padL = 28, padR = 12, padT = 14, padB = 24;
    const max = Math.max.apply(null, data.map(d => d.count)) + 4;
    const innerW = W - padL - padR, innerH = H - padT - padB;
    const x = i => padL + (i / (data.length - 1)) * innerW;
    const y = v => padT + innerH - (v / max) * innerH;
    const linePts = data.map((d, i) => x(i) + "," + y(d.count)).join(" ");
    const areaPts = padL + "," + (padT + innerH) + " " + linePts + " " + (padL + innerW) + "," + (padT + innerH);
    let grid = "";
    for (let g = 0; g <= 3; g++) { const gy = padT + (g / 3) * innerH; grid += '<line class="gridline" x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '"/>'; }
    const pts = data.map((d, i) => '<circle class="pt" cx="' + x(i) + '" cy="' + y(d.count) + '" r="3"/>').join("");
    const labels = data.map((d, i) => (i % 2 === 0) ? '<text x="' + x(i) + '" y="' + (H - 8) + '" text-anchor="middle">' + d.date + '</text>' : '').join("");
    return '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" role="img" aria-label="14-day error trend">' +
      '<defs><linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="#3b5bdb" stop-opacity="0.22"/><stop offset="100%" stop-color="#3b5bdb" stop-opacity="0.02"/>' +
      '</linearGradient></defs>' + grid +
      '<polygon class="area" points="' + areaPts + '"/>' +
      '<polyline class="line" points="' + linePts + '"/>' + pts + labels + '</svg>';
  }

  function renderReporting() {
    const k = D.kpis;
    const kpis =
      '<div class="kpi-row">' +
        kpi("Open exceptions", k.openExceptions, "from 2026-06-07 run") +
        kpi("New today", k.newToday, "flagged this run") +
        kpi("Auto-closed", k.autoClosedToday, "no longer reproduced", true) +
        kpi("Avg turnaround", k.avgTurnaroundDays + "d", "across resolved tickets") +
        kpi("Within SLA", k.pctWithinSla + "%", "of resolved tickets") +
      '</div>';

    const maxType = Math.max.apply(null, D.errorsByType.map(t => t.count));
    const maxFac = Math.max.apply(null, D.errorsByFacility.map(t => t.count));

    const recur = '<div class="recur-list">' + D.recurrence.map(r =>
      '<div class="recur-item"><span class="rc-count">' + r.count + '</span>' +
      '<div class="rc-body"><div class="rc-title">' + esc(D.rulesById[r.type].name) + ' @ ' + esc(r.facility) + '</div>' +
      '<div class="rc-note">' + esc(r.note) + ' (' + esc(r.window) + ')</div></div></div>').join("") + '</div>';

    $("#reportingBody").innerHTML =
      kpis +
      '<div class="panels">' +
        '<div class="card"><h2>' + I.chart + ' Error trend <span class="hint">last 14 daily runs</span></h2>' + trendChart() + '</div>' +
        '<div class="card"><h2>' + I.repeat + ' Recurring errors <span class="hint">30-day window</span></h2>' + recur + '</div>' +
      '</div>' +
      '<div class="panels equal">' +
        '<div class="card"><h2>Errors by type</h2>' + bars(D.errorsByType, t => D.rulesById[t.key].name, maxType) + '</div>' +
        '<div class="card"><h2>Errors by facility</h2>' + bars(D.errorsByFacility, t => t.key + " — " + D.facilities[t.key].split(" — ")[0], maxFac) + '</div>' +
      '</div>';
  }
  function kpi(label, value, sub, accent) {
    return '<div class="kpi' + (accent ? ' accent' : '') + '"><div class="label">' + esc(label) + '</div>' +
      '<div class="value tnum">' + esc(value) + '</div><div class="sub">' + esc(sub) + '</div></div>';
  }

  // ========================================================================
  //  TURNAROUND / SLA
  // ========================================================================
  function renderSla() {
    const buckets = '<div class="buckets">' + D.aging.map((b, i) =>
      '<div class="bucket b' + i + '"><div class="bk-label">' + esc(b.bucket) + '</div><div class="bk-val tnum">' + b.count + '</div></div>').join("") + '</div>';

    // team table
    const teamRows = D.slaByTeam.map(t => {
      const total = t.within + t.breaching;
      const wPct = total ? Math.round((t.within / total) * 100) : 0;
      const dual = '<span class="dualbar" title="' + t.within + ' within / ' + t.breaching + ' breaching">' +
        '<span class="w" style="width:' + wPct + '%"></span><span class="b" style="width:' + (100 - wPct) + '%"></span></span>';
      const slow = t.avgDays >= 4;
      return '<tr><td><b>' + esc(t.team) + '</b></td>' +
        '<td class="right ' + (slow ? 'sla-bad' : '') + '">' + t.avgDays.toFixed(1) + 'd</td>' +
        '<td class="right sla-ok">' + t.within + '</td>' +
        '<td class="right ' + (t.breaching ? 'sla-bad' : '') + '">' + t.breaching + '</td>' +
        '<td class="right">' + t.open + '</td>' +
        '<td style="width:140px">' + dual + '</td></tr>';
    }).join("");

    const personRows = D.slaByPerson.slice().sort((a, b) => b.avgDays - a.avgDays).map(p => {
      const slow = p.avgDays >= 4;
      return '<tr><td><b>' + esc(p.person) + '</b></td><td>' + esc(p.team) + '</td>' +
        '<td class="right ' + (slow ? 'sla-bad' : '') + '">' + p.avgDays.toFixed(1) + 'd</td>' +
        '<td class="right sla-ok">' + p.within + '</td>' +
        '<td class="right ' + (p.breaching ? 'sla-bad' : '') + '">' + p.breaching + '</td></tr>';
    }).join("");

    // attention ranking
    const ranked = D.slaByTeam.slice().filter(t => t.open > 0).sort((a, b) => (b.breaching - a.breaching) || (b.avgDays - a.avgDays));
    const attention = ranked.map((t, i) =>
      '<div class="attention-row' + (i === 0 ? ' worst' : '') + '">' +
        '<span class="rank">' + (i + 1) + '</span>' +
        '<div><div class="ar-name">' + esc(t.team) + (i === 0 ? ' — needs attention' : '') + '</div>' +
        '<div class="ar-team">' + t.open + ' open · ' + t.breaching + ' breaching SLA</div></div>' +
        '<span class="spacer"></span>' +
        '<div class="ar-stat"><div class="big ' + (t.avgDays >= 4 ? 'sla-bad' : '') + '">' + t.avgDays.toFixed(1) + 'd</div>' +
        '<div class="ar-team">avg time-to-resolve</div></div>' +
      '</div>').join("");

    $("#slaBody").innerHTML =
      '<h2 style="margin:0 0 10px;font-size:13.5px;font-weight:650">Aging of open tickets</h2>' + buckets +
      '<div class="panels equal">' +
        '<div class="card"><h2>Who needs attention</h2>' + attention +
          '<div class="muted-note">Procurement is the clear bottleneck: longest average turnaround and the most SLA breaches.</div></div>' +
        '<div class="card"><h2>By team</h2><table class="mini"><thead><tr><th>Team</th><th class="right">Avg</th><th class="right">Within</th><th class="right">Breach</th><th class="right">Open</th><th>Within / breach</th></tr></thead><tbody>' + teamRows + '</tbody></table></div>' +
      '</div>' +
      '<div class="card"><h2>By person <span class="hint">sorted slowest first</span></h2><table class="mini"><thead><tr><th>Person</th><th>Team</th><th class="right">Avg</th><th class="right">Within SLA</th><th class="right">Breaching</th></tr></thead><tbody>' + personRows + '</tbody></table></div>';
  }

  // ========================================================================
  //  RULE & ROUTING ADMIN
  // ========================================================================
  let selectedRuleId = D.rules[0].id;
  function renderAdmin() {
    $("#adminBody").innerHTML =
      '<div class="admin-grid">' +
        '<div class="card"><h2>' + I.sliders + ' Validation rules</h2>' +
          '<table class="rules" id="rulesTable"><thead><tr><th>Rule</th><th>Type</th><th>Target table</th><th>Severity</th><th>Enabled</th></tr></thead><tbody id="rulesBody"></tbody></table>' +
          '<div class="muted-note">Click a rule to load it in the editor. Toggles and edits are mock-only.</div>' +
        '</div>' +
        '<div class="card" id="ruleEditCard"></div>' +
        '<div class="card"><h2>' + I.route + ' Routing map <span class="hint">error type → team → assignee → JIRA</span></h2>' +
          '<div class="routing-map">' + D.rules.map(r =>
            '<div class="route-flow">' +
              '<span class="rf-err">' + esc(r.name) + '</span>' +
              '<span class="rf-arrow">' + I.arrow + '</span>' +
              '<span><span class="rf-team">' + esc(r.team) + '</span><div class="rf-meta">' + esc(r.assignee) + '</div></span>' +
              '<span class="rf-arrow">' + I.arrow + '</span>' +
              '<span class="rf-jira">' + esc(r.jiraProject) + ' · ' + esc(r.component) + '</span>' +
            '</div>').join("") + '</div></div>' +
        '<div class="card"><h2>' + I.clock + ' SLA targets <span class="hint">resolution time by severity</span></h2>' +
          '<div class="sla-targets">' + ["Critical", "High", "Medium", "Low"].map(sev =>
            '<div class="sla-target"><div class="stt"><span class="sev-dot ' + sev + '"></span>' + sev + '</div>' +
            '<div class="stv tnum">' + D.sla[sev] + '</div><div class="stl">day' + (D.sla[sev] > 1 ? 's' : '') + ' to resolve</div></div>').join("") + '</div></div>' +
      '</div>';

    renderRulesTable();
    renderRuleEditor();
  }

  function renderRulesTable() {
    const tb = $("#rulesBody");
    tb.innerHTML = D.rules.map(r =>
      '<tr data-id="' + r.id + '" class="' + (r.id === selectedRuleId ? 'sel' : '') + '">' +
        '<td><b>' + esc(r.name) + '</b><div class="mono">' + esc(r.id) + '</div></td>' +
        '<td><span class="tag">' + esc(r.type) + '</span></td>' +
        '<td class="mono">' + esc(r.table) + '</td>' +
        '<td><span class="pill sev-pill ' + r.severity + '"><span class="sev-dot ' + r.severity + '"></span>' + r.severity + '</span></td>' +
        '<td><span class="toggle ' + (r.enabled ? 'on' : '') + '" role="switch" aria-checked="' + r.enabled + '" tabindex="0" data-toggle="' + r.id + '" aria-label="Toggle ' + esc(r.name) + '"></span></td>' +
      '</tr>').join("");

    $$("#rulesBody tr").forEach(tr => {
      tr.addEventListener("click", e => {
        if (e.target.closest("[data-toggle]")) return;
        selectedRuleId = tr.dataset.id;
        renderRulesTable(); renderRuleEditor();
      });
    });
    $$("#rulesBody [data-toggle]").forEach(tg => {
      const fire = (e) => {
        e.stopPropagation();
        const r = D.rulesById[tg.dataset.toggle];
        r.enabled = !r.enabled;
        renderRulesTable();
        if (r.id === selectedRuleId) renderRuleEditor();
        toast(r.name + (r.enabled ? " enabled" : " disabled") + " (mock)");
      };
      tg.addEventListener("click", fire);
      tg.addEventListener("keydown", e => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); fire(e); } });
    });
  }

  function renderRuleEditor() {
    const r = D.rulesById[selectedRuleId];
    const sevOpts = ["Critical", "High", "Medium", "Low"].map(s => '<option' + (s === r.severity ? ' selected' : '') + '>' + s + '</option>').join("");
    const teamOpts = Object.keys(D.teams).map(t => '<option' + (t === r.team ? ' selected' : '') + '>' + t + '</option>').join("");
    const card = $("#ruleEditCard");
    card.innerHTML =
      '<h2>' + I.note + ' Edit rule <span class="hint mono">' + esc(r.id) + '</span></h2>' +
      '<div class="form-row"><label>Rule name</label><input type="text" id="ef-name" value="' + esc(r.name) + '"></div>' +
      '<div class="form-row"><label>Validation type</label><input type="text" id="ef-type" value="' + esc(r.type) + '"></div>' +
      '<div class="form-row"><label>Target table</label><input type="text" id="ef-table" value="' + esc(r.table) + '"></div>' +
      '<div class="form-row"><label>Severity</label><select id="ef-sev">' + sevOpts + '</select></div>' +
      '<div class="form-row"><label>Owning team</label><select id="ef-team">' + teamOpts + '</select></div>' +
      '<div class="form-row"><label>JIRA</label><input type="text" value="' + esc(r.jiraProject + " · " + r.component) + '"></div>' +
      '<div style="display:flex;gap:8px;margin-top:6px"><button class="btn primary" id="ef-save">' + I.check + ' Save rule</button>' +
      '<button class="btn ghost" id="ef-reset">Reset</button></div>' +
      '<div class="muted-note">Plain-language: ' + esc(r.plain) + '</div>';

    $("#ef-save").addEventListener("click", () => {
      r.name = $("#ef-name").value || r.name;
      r.severity = $("#ef-sev").value;
      r.team = $("#ef-team").value;
      built.reporting = built.sla = false; // KPIs reference rule names
      renderRulesTable();
      toast("Rule " + r.id + " saved (mock)");
    });
    $("#ef-reset").addEventListener("click", renderRuleEditor);
  }

  // ========================================================================
  //  INIT
  // ========================================================================
  updateFolderCounts();
  renderRows();
  if (visibleList.length) selectRow(visibleList[0].id);

})();
