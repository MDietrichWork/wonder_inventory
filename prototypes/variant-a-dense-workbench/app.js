/* Wonder Inventory Data-Quality Console — Variant A "Dense Workbench"
   Vanilla JS. No build step, works on file://. Reads global DATA from data.js. */
(function () {
  "use strict";
  var D = window.DATA;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === "class") n.className = attrs[k];
      else if (k === "html") n.innerHTML = attrs[k];
      else if (k === "text") n.textContent = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function statusClass(s) { return "st-" + s.replace(/[^A-Za-z]/g, ""); }
  function pluralSel(arr) { return arr; }

  // runtime mutable copy of exceptions so mock actions persist for the session
  var EXC = D.exceptions.map(function (e) { return Object.assign({}, e); });

  /* ============================ NAVIGATION ============================ */
  var VIEWS = ["home", "workbench", "dashboard", "sla", "admin"];
  function showView(name) {
    $$(".view").forEach(function (v) { v.classList.toggle("active", v.id === "view-" + name); });
    $$(".nav-item").forEach(function (b) { b.classList.toggle("active", b.dataset.view === name); });
    if (name === "dashboard") renderDashboard();
    if (name === "sla") renderSLA();
    if (name === "admin") renderAdmin();
    if (name === "workbench") { var s = $("#f-search"); if (s) setTimeout(function () { /* no autofocus to avoid scroll */ }, 0); }
  }
  $$(".nav-item").forEach(function (b) { b.addEventListener("click", function () { showView(b.dataset.view); }); });

  document.addEventListener("keydown", function (e) {
    if (e.target.matches && e.target.matches("input,select,textarea")) {
      if (e.key === "Escape") e.target.blur();
      return;
    }
    if (e.key === "Escape") { closeDrawer(); return; }
    if (e.key === "/") { e.preventDefault(); showView("workbench"); $("#f-search").focus(); return; }
    var idx = ["1", "2", "3", "4", "5"].indexOf(e.key);
    if (idx > -1) showView(VIEWS[idx]);
  });

  /* ============================ HEADER ============================ */
  $("#run-date").textContent = D.meta.runDate;
  $("#today-date").textContent = D.meta.today;

  /* ============================ FILTER POPULATION ============================ */
  function fillSelect(sel, items, allLabel) {
    sel.appendChild(el("option", { value: "" }, [allLabel]));
    items.forEach(function (it) { sel.appendChild(el("option", { value: it }, [it])); });
  }
  fillSelect($("#f-facility"), D.facilities.map(function (f) { return f.id; }), "All facilities");
  fillSelect($("#f-system"), D.systems, "All systems");
  fillSelect($("#f-errortype"), D.errorTypes.map(function (t) { return t.type; }), "All error types");
  fillSelect($("#f-severity"), ["Critical", "High", "Medium", "Low"], "All severities");
  fillSelect($("#f-status"), ["Open", "In Progress", "In Review", "Resolved", "Closed", "Auto-Closed"], "All statuses");
  fillSelect($("#f-team"), Object.keys(D.teams), "All teams");

  /* ============================ WORKBENCH GRID ============================ */
  var COLS = [
    { key: "id", label: "Error ID", cls: "mono" },
    { key: "runDate", label: "Run Date", cls: "mono" },
    { key: "errorType", label: "Error Type" },
    { key: "severity", label: "Severity" },
    { key: "table", label: "Source Table", cls: "mono" },
    { key: "facility", label: "Facility", cls: "mono" },
    { key: "system", label: "System" },
    { key: "entityKey", label: "Entity Key", cls: "mono" },
    { key: "team", label: "Routed Team" },
    { key: "assignee", label: "Assignee" },
    { key: "jira", label: "JIRA Key", cls: "mono" },
    { key: "jiraStatus", label: "JIRA Status" },
    { key: "age", label: "Age (d)", cls: "num", num: true },
    { key: "recurrence", label: "Recur", cls: "num", num: true }
  ];
  var sortKey = "severity", sortDir = 1; // default: most severe / oldest first handled below
  var selected = {}; // id -> true

  // default sort: open first, then severity rank, then age desc
  var SEVRANK = { Critical: 0, High: 1, Medium: 2, Low: 3 };

  function getFilters() {
    return {
      q: $("#f-search").value.trim().toLowerCase(),
      facility: $("#f-facility").value,
      system: $("#f-system").value,
      errortype: $("#f-errortype").value,
      severity: $("#f-severity").value,
      status: $("#f-status").value,
      team: $("#f-team").value
    };
  }

  function filteredRows() {
    var f = getFilters();
    var rows = EXC.filter(function (e) {
      if (f.facility && e.facility !== f.facility) return false;
      if (f.system && e.system !== f.system) return false;
      if (f.errortype && e.errorType !== f.errortype) return false;
      if (f.severity && e.severity !== f.severity) return false;
      if (f.status && e.jiraStatus !== f.status) return false;
      if (f.team && e.team !== f.team) return false;
      if (f.q) {
        var hay = (e.id + " " + e.entityKey + " " + e.jira + " " + e.errorType + " " + e.assignee + " " + e.facility).toLowerCase();
        if (hay.indexOf(f.q) === -1) return false;
      }
      return true;
    });
    rows.sort(function (a, b) {
      var va, vb;
      if (sortKey === "severity") { va = SEVRANK[a.severity]; vb = SEVRANK[b.severity]; }
      else { va = a[sortKey]; vb = b[sortKey]; }
      if (va < vb) return -1 * sortDir;
      if (va > vb) return 1 * sortDir;
      // tiebreak: age desc
      return b.age - a.age;
    });
    return rows;
  }

  function buildHead() {
    var tr = $("#wb-head");
    clear(tr);
    var th0 = el("th", { class: "nosort checkcol" });
    var cb = el("input", { type: "checkbox", "aria-label": "Select all" });
    cb.addEventListener("change", function () {
      var rows = filteredRows();
      rows.forEach(function (r) { if (cb.checked) selected[r.id] = true; else delete selected[r.id]; });
      renderBody();
    });
    th0.appendChild(cb);
    tr.appendChild(th0);
    COLS.forEach(function (c) {
      var th = el("th", { class: c.cls && c.num ? "num" : "" }, [c.label]);
      if (sortKey === c.key) th.appendChild(el("span", { class: "arr" }, [sortDir > 0 ? "▲" : "▼"]));
      th.addEventListener("click", function () {
        if (sortKey === c.key) sortDir *= -1; else { sortKey = c.key; sortDir = 1; }
        buildHead(); renderBody();
      });
      tr.appendChild(th);
    });
  }

  function sevPill(s) { return el("span", { class: "pill sev sev-" + s }, [el("span", { class: "sev-dot " + s }), s]); }
  function statusPill(s) { return el("span", { class: "status " + statusClass(s) }, [s]); }

  function renderBody() {
    var rows = filteredRows();
    var tb = $("#wb-body");
    clear(tb);
    $("#wb-empty").style.display = rows.length ? "none" : "block";
    rows.forEach(function (e) {
      var tr = el("tr", { class: "row" + (selected[e.id] ? " selected" : ""), tabindex: "0", "data-id": e.id });
      var tdc = el("td", { class: "checkcol" });
      var cb = el("input", { type: "checkbox", "aria-label": "Select " + e.id });
      cb.checked = !!selected[e.id];
      cb.addEventListener("click", function (ev) { ev.stopPropagation(); });
      cb.addEventListener("change", function () { if (cb.checked) selected[e.id] = true; else delete selected[e.id]; tr.classList.toggle("selected", cb.checked); updateBulkBar(); });
      tdc.appendChild(cb);
      tr.appendChild(tdc);

      COLS.forEach(function (c) {
        var td = el("td", { class: c.cls || "" });
        var v = e[c.key];
        if (c.key === "severity") td.appendChild(sevPill(v));
        else if (c.key === "jiraStatus") td.appendChild(statusPill(v));
        else if (c.key === "jira") {
          var a = el("a", { class: "jira-link", href: "#", title: "Open " + v + " in JIRA" }, [v]);
          a.addEventListener("click", function (ev) { ev.stopPropagation(); ev.preventDefault(); alert("Mock: open " + v + " in JIRA (project WIQ)."); });
          td.appendChild(a);
        }
        else if (c.key === "age") {
          var over = !e.withinSla && e.isOpen;
          var warn = e.isOpen && !over && e.age >= e.slaTarget;
          td.className = "num age" + (over ? " over" : warn ? " warn" : "");
          td.textContent = v;
          if (over) td.title = "Past " + e.slaTarget + "d SLA target";
        }
        else if (c.key === "recurrence") {
          td.className = "num recur" + (v >= 4 ? " hot" : "");
          td.textContent = "×" + v;
        }
        else td.textContent = v;
        tr.appendChild(td);
      });
      tr.addEventListener("click", function () { openDrawer(e.id); });
      tr.addEventListener("keydown", function (ev) { if (ev.key === "Enter") openDrawer(e.id); });
      tb.appendChild(tr);
    });
    $("#wb-result-meta").innerHTML = "Showing <b>" + rows.length + "</b> of <b>" + EXC.length + "</b> exceptions";
    updateBulkBar();
    // mark active row
    if (activeId) { var ar = tb.querySelector('tr[data-id="' + activeId + '"]'); if (ar) ar.classList.add("active"); }
  }

  function updateBulkBar() {
    var n = Object.keys(selected).length;
    var bar = $("#bulkbar");
    bar.classList.toggle("show", n > 0);
    $("#bulk-count").textContent = n + " selected";
  }

  $$("#wb-toolbar select, #wb-toolbar input").forEach(function (c) {
    c.addEventListener("input", renderBody);
    c.addEventListener("change", renderBody);
  });
  $("#f-clear").addEventListener("click", function () {
    $$("#wb-toolbar select").forEach(function (s) { s.value = ""; });
    $("#f-search").value = "";
    renderBody();
  });

  // Bulk actions (mock)
  function selectedRows() { return EXC.filter(function (e) { return selected[e.id]; }); }
  $("#bulk-reassign").addEventListener("click", function () {
    var who = prompt("Reassign " + Object.keys(selected).length + " exception(s) to (assignee name):", "Sarah Chen");
    if (!who) return;
    selectedRows().forEach(function (e) { e.assignee = who; });
    alert("Mock: reassigned to " + who + ".");
    renderBody();
  });
  $("#bulk-comment").addEventListener("click", function () {
    var c = prompt("Add a comment to " + Object.keys(selected).length + " ticket(s):", "Investigating batch root cause.");
    if (!c) return;
    selectedRows().forEach(function (e) { e._notes = (e._notes || []).concat([{ by: "Mike Dietrich", at: D.meta.today, text: c }]); });
    alert("Mock: comment posted to " + Object.keys(selected).length + " JIRA ticket(s).");
  });
  $("#bulk-resolve").addEventListener("click", function () {
    selectedRows().forEach(function (e) { e.jiraStatus = "Resolved"; e.isOpen = false; });
    alert("Mock: marked resolved.");
    selected = {}; renderBody();
  });
  $("#bulk-clear").addEventListener("click", function () { selected = {}; renderBody(); });

  /* ============================ DETAIL DRAWER ============================ */
  var activeId = null;
  function ruleFor(id) { return D.rules.filter(function (r) { return r.id === id; })[0]; }
  function errTypeMeta(t) { return D.errorTypes.filter(function (x) { return x.type === t; })[0]; }

  function openDrawer(id) {
    var e = EXC.filter(function (x) { return x.id === id; })[0];
    if (!e) return;
    activeId = id;
    var rule = ruleFor(e.rule) || {};
    var meta = errTypeMeta(e.errorType) || {};

    $("#dr-id").textContent = e.id + " · " + e.errorType;
    var sub = $("#dr-sub"); clear(sub);
    sub.appendChild(sevPill(e.severity));
    sub.appendChild(statusPill(e.jiraStatus));
    sub.appendChild(el("span", { class: "tag" }, [e.facility + " · " + e.system]));
    sub.appendChild(el("a", { class: "jira-link", href: "#", html: e.jira }));
    sub.appendChild(el("span", { class: "tip" }, ["Age " + e.age + "d / " + e.slaTarget + "d SLA · " + (e.withinSla ? "within SLA" : "BREACHING")]));

    var body = $("#dr-body"); clear(body);

    // Validation rule that fired
    var rsec = el("div", { class: "section" }, [el("h3", {}, ["Validation rule that fired"])]);
    var rbox = el("div", { class: "rule-box" }, [
      el("div", { class: "rname" }, [(rule.name || e.errorType) + "  —  " + (rule.type || meta.ruleType || "")]),
      el("div", { class: "tip", html: meta.desc || "" }),
      el("code", { text: rule.expression || "(rule expression unavailable)" })
    ]);
    rsec.appendChild(rbox);
    body.appendChild(rsec);

    // Offending data snapshot
    var dsec = el("div", { class: "section" }, [el("h3", {}, ["Offending " + e.table + " snapshot"])]);
    var kv = el("div", { class: "kv" });
    Object.keys(e.snapshot).forEach(function (k) {
      var val = e.snapshot[k];
      var neg = (typeof val === "number" && val < 0) || val === null;
      kv.appendChild(el("div", { class: "k" }, [k]));
      kv.appendChild(el("div", { class: "v" + (neg ? " neg" : "") }, [val === null ? "NULL" : String(val)]));
    });
    dsec.appendChild(kv);
    body.appendChild(dsec);

    // Routing
    var route = D.routing.filter(function (r) { return r.errorType === e.errorType; })[0] || {};
    var rosec = el("div", { class: "section" }, [el("h3", {}, ["Routing"])]);
    var rkv = el("div", { class: "kv" }, [
      el("div", { class: "k" }, ["routed_team"]), el("div", { class: "v" }, [e.team]),
      el("div", { class: "k" }, ["assignee"]), el("div", { class: "v" }, [e.assignee]),
      el("div", { class: "k" }, ["jira_project"]), el("div", { class: "v" }, [route.project || "WIQ"]),
      el("div", { class: "k" }, ["component"]), el("div", { class: "v" }, [route.component || "—"]),
      el("div", { class: "k" }, ["recurrence_30d"]), el("div", { class: "v" }, ["×" + e.recurrence])
    ]);
    rosec.appendChild(rkv);
    body.appendChild(rosec);

    // JIRA timeline
    var tsec = el("div", { class: "section" }, [el("h3", {}, ["JIRA status timeline · " + e.jira])]);
    var ul = el("ul", { class: "timeline" });
    e.timeline.forEach(function (t) {
      var auto = /auto/i.test(t.status) || t.by === "batch-validator";
      var li = el("li", { class: auto ? "auto" : "" }, [
        el("span", { class: "tdot" }),
        el("div", { class: "tstatus" }, [t.status]),
        el("div", { class: "tmeta" }, [t.at.replace("T", " ").replace("Z", " UTC") + " · " + t.by])
      ]);
      ul.appendChild(li);
    });
    tsec.appendChild(ul);
    if (e.autoClosed) tsec.appendChild(el("div", { class: "tip", html: "✔ <b style='color:var(--ok)'>Auto-closed</b> — this issue did not reproduce on the " + D.meta.runDate + " run after the underlying table was fixed." }));
    body.appendChild(tsec);

    // Notes
    var nsec = el("div", { class: "section" }, [el("h3", {}, ["Notes"])]);
    var notes = el("ul", { class: "notes" });
    (e._notes || []).forEach(function (n) {
      notes.appendChild(el("li", { class: "note" }, [el("div", { class: "nm" }, [n.by + " · " + n.at]), el("div", {}, [n.text])]));
    });
    if (!(e._notes || []).length) notes.appendChild(el("div", { class: "tip" }, ["No notes yet."]));
    nsec.appendChild(notes);
    var ni = el("div", { class: "note-input" });
    var inp = el("input", { type: "text", placeholder: "Add a note (mock)…" });
    var addb = el("button", { class: "btn sm primary" }, ["Add"]);
    function addNote() {
      if (!inp.value.trim()) return;
      e._notes = (e._notes || []).concat([{ by: "Mike Dietrich", at: D.meta.today, text: inp.value.trim() }]);
      openDrawer(id);
    }
    addb.addEventListener("click", addNote);
    inp.addEventListener("keydown", function (ev) { if (ev.key === "Enter") addNote(); });
    ni.appendChild(inp); ni.appendChild(addb);
    nsec.appendChild(ni);
    body.appendChild(nsec);

    // action buttons (rebind to this row)
    $("#dr-jira").onclick = function () { alert("Mock: open " + e.jira + " in JIRA."); };
    $("#dr-reassign").onclick = function () { var w = prompt("Reassign " + e.id + " to:", e.assignee); if (w) { e.assignee = w; openDrawer(id); renderBody(); } };
    $("#dr-override").onclick = function () { var t = prompt("Override routed team for " + e.id + ":", e.team); if (t) { e.team = t; openDrawer(id); renderBody(); } };
    $("#dr-note").onclick = function () { inp.focus(); };

    $("#drawer").classList.add("show");
    $("#drawer").setAttribute("aria-hidden", "false");
    $("#drawer-scrim").classList.add("show");
    renderBody();
  }
  function closeDrawer() {
    activeId = null;
    $("#drawer").classList.remove("show");
    $("#drawer").setAttribute("aria-hidden", "true");
    $("#drawer-scrim").classList.remove("show");
    $$("#wb-body tr.active").forEach(function (r) { r.classList.remove("active"); });
  }
  $("#dr-close").addEventListener("click", closeDrawer);
  $("#drawer-scrim").addEventListener("click", closeDrawer);

  /* ============================ AGGREGATES ============================ */
  function countBy(rows, key) {
    var m = {};
    rows.forEach(function (r) { var k = typeof key === "function" ? key(r) : r[key]; m[k] = (m[k] || 0) + 1; });
    return m;
  }
  function openExc() { return EXC.filter(function (e) { return e.isOpen; }); }

  function metrics() {
    var open = openExc();
    var newToday = EXC.filter(function (e) { return e.created === D.meta.runDate; });
    var autoClosedToday = EXC.filter(function (e) { return e.autoClosed && e.resolved === D.meta.runDate; });
    var resolvedAll = EXC.filter(function (e) { return e.turnaround != null; });
    var avgTat = resolvedAll.length ? (resolvedAll.reduce(function (s, e) { return s + e.turnaround; }, 0) / resolvedAll.length) : 0;
    var withinAll = EXC.filter(function (e) { return !e.isOpen ? e.withinSla : e.age <= e.slaTarget; });
    var pctSla = Math.round(100 * withinAll.length / EXC.length);
    return { open: open.length, newToday: newToday.length, autoClosedToday: autoClosedToday.length, avgTat: avgTat, pctSla: pctSla };
  }

  /* ============================ HOME ============================ */
  function renderHome() {
    var m = metrics();
    var k = $("#home-kpis"); clear(k);
    [["Open exceptions", m.open, "accent"], ["New today", m.newToday], ["Auto-closed today", m.autoClosedToday],
     ["Avg turnaround", m.avgTat.toFixed(1) + "d"], ["% within SLA", m.pctSla + "%"]].forEach(function (t) {
      k.appendChild(el("div", { class: "kpi" + (t[2] ? " " + t[2] : "") }, [
        el("div", { class: "label" }, [t[0]]), el("div", { class: "value" }, [String(t[1])])
      ]));
    });
    $("#nav-open-count").textContent = m.open;

    var jump = $("#home-jump"); clear(jump);
    [["Exception Workbench", "workbench", m.open + " open to triage"],
     ["Reporting Dashboard", "dashboard", "volume, trend & composition"],
     ["Turnaround / SLA", "sla", "who is falling behind"],
     ["Rule & Routing Admin", "admin", D.rules.length + " rules · " + D.routing.length + " routes"]].forEach(function (j) {
      var row = el("div", { class: "hbar", style: "grid-template-columns: 1fr auto; cursor:pointer;" }, [
        el("div", { class: "hlabel" }, [el("b", { style: "color:var(--text)" }, [j[0]]), el("div", { class: "tip" }, [j[2]])]),
        el("span", { class: "btn sm" }, ["Open →"])
      ]);
      row.addEventListener("click", function () { showView(j[1]); });
      jump.appendChild(row);
    });

    var g = $("#home-glance"); clear(g);
    var byTeam = countBy(openExc(), "team");
    var pairs = [["Run date validated", D.meta.runDate],
      ["Total exceptions in system", EXC.length],
      ["Critical open", openExc().filter(function (e) { return e.severity === "Critical"; }).length],
      ["Breaching SLA (open)", openExc().filter(function (e) { return !e.withinSla; }).length],
      ["Open · Data Engineering", byTeam["Data Engineering"] || 0],
      ["Open · Inventory Ops", byTeam["Inventory Ops"] || 0],
      ["Open · Procurement", byTeam["Procurement"] || 0]];
    pairs.forEach(function (p) { g.appendChild(el("div", { class: "k" }, [p[0]])); g.appendChild(el("div", { class: "v" }, [String(p[1])])); });
  }

  /* ============================ DASHBOARD ============================ */
  function hbarList(container, entries, max, fmt) {
    clear(container);
    var mx = max || Math.max.apply(null, entries.map(function (e) { return e[1]; }).concat([1]));
    entries.forEach(function (e) {
      container.appendChild(el("div", { class: "hbar" }, [
        el("div", { class: "hlabel", title: e[0] }, [e[0]]),
        el("div", { class: "track" }, [el("div", { class: "fill", style: "width:" + Math.round(100 * e[1] / mx) + "%" })]),
        el("div", { class: "hval" }, [fmt ? fmt(e[1]) : String(e[1])])
      ]));
    });
  }

  function renderDashboard() {
    var m = metrics();
    var k = $("#dash-kpis"); clear(k);
    [["Open exceptions", m.open, "accent", openExc().filter(function (e) { return !e.withinSla; }).length + " breaching", "up"],
     ["New today", m.newToday, "", "run " + D.meta.runDate, ""],
     ["Auto-closed today", m.autoClosedToday, "", "fixed upstream", "down"],
     ["Avg turnaround", m.avgTat.toFixed(1) + "d", "", "across resolved", ""],
     ["% within SLA", m.pctSla + "%", "", "target ≥ 90%", m.pctSla >= 90 ? "down" : "up"]].forEach(function (t) {
      k.appendChild(el("div", { class: "kpi" + (t[2] ? " " + t[2] : "") }, [
        el("div", { class: "label" }, [t[0]]), el("div", { class: "value" }, [String(t[1])]),
        el("div", { class: "delta " + (t[4] || "") }, [t[3]])
      ]));
    });

    renderTrend();

    hbarList($("#sev-bars"), ["Critical", "High", "Medium", "Low"].map(function (s) {
      return [s, EXC.filter(function (e) { return e.severity === s; }).length];
    }));

    var byType = countBy(EXC, "errorType");
    hbarList($("#type-bars"), Object.keys(byType).map(function (k2) { return [k2, byType[k2]]; }).sort(function (a, b) { return b[1] - a[1]; }));

    var byFac = countBy(EXC, "facility");
    hbarList($("#facility-bars"), D.facilities.map(function (f) { return [f.id + " (" + f.type + ")", byFac[f.id] || 0]; }).sort(function (a, b) { return b[1] - a[1]; }));

    var rt = $("#recurring-table tbody"); clear(rt);
    var maxR = Math.max.apply(null, D.recurring.map(function (r) { return r.count30d; }));
    D.recurring.forEach(function (r) {
      rt.appendChild(el("tr", {}, [
        el("td", { class: "mono", style: "font-size:11.5px" }, [r.fingerprint]),
        el("td", {}, [r.team]),
        el("td", { class: "mono" }, [r.lastSeen]),
        el("td", { class: "num" }, [el("b", { class: r.count30d >= 4 ? "recur hot" : "" }, ["×" + r.count30d])]),
        el("td", { class: "bar-cell" }, [el("div", { class: "minib", style: "width:" + Math.round(100 * r.count30d / maxR) + "%" })])
      ]));
    });
  }

  function renderTrend() {
    var data = D.trend;
    var W = 600, H = 180, padL = 26, padB = 22, padT = 10, padR = 8;
    var iw = W - padL - padR, ih = H - padB - padT;
    var maxV = Math.max.apply(null, data.map(function (d) { return d.count; }));
    var stepX = iw / (data.length - 1);
    var x = function (i) { return padL + i * stepX; };
    var y = function (v) { return padT + ih - (v / maxV) * ih; };

    var pts = data.map(function (d, i) { return x(i) + "," + y(d.count); }).join(" ");
    var area = "M" + x(0) + "," + (padT + ih) + " L" + pts.replace(/ /g, " L") + " L" + x(data.length - 1) + "," + (padT + ih) + " Z";

    var svg = '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Error trend line chart">';
    svg += '<defs><linearGradient id="grad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#4f8cff"/><stop offset="100%" stop-color="#4f8cff" stop-opacity="0"/></linearGradient></defs>';
    // gridlines + y labels
    for (var g = 0; g <= 4; g++) {
      var gv = Math.round(maxV * g / 4);
      var gy = y(gv);
      svg += '<line class="gridline" x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '"/>';
      svg += '<text x="' + (padL - 5) + '" y="' + (gy + 3) + '" text-anchor="end">' + gv + '</text>';
    }
    svg += '<path class="area" d="' + area + '"/>';
    svg += '<polyline class="line" points="' + pts + '"/>';
    data.forEach(function (d, i) {
      svg += '<circle class="pt" cx="' + x(i) + '" cy="' + y(d.count) + '" r="2.5"><title>' + d.date + ': ' + d.count + '</title></circle>';
      if (i % 2 === 0 || i === data.length - 1)
        svg += '<text x="' + x(i) + '" y="' + (H - 6) + '" text-anchor="middle">' + d.date.slice(5) + '</text>';
    });
    svg += '</svg>';
    $("#trend-chart").innerHTML = svg;
  }

  /* ============================ SLA ============================ */
  function renderSLA() {
    var open = openExc();
    // aging buckets on open tickets
    var buckets = [["0–1 day", function (a) { return a <= 1; }, "b0"],
      ["1–3 days", function (a) { return a > 1 && a <= 3; }, "b1"],
      ["3–7 days", function (a) { return a > 3 && a <= 7; }, "b2"],
      ["7+ days", function (a) { return a > 7; }, "b3"]];
    var bc = $("#aging-buckets"); clear(bc);
    buckets.forEach(function (b) {
      var n = open.filter(function (e) { return b[1](e.age); }).length;
      bc.appendChild(el("div", { class: "bucket " + b[2] }, [
        el("div", { class: "bk-label" }, [b[0]]),
        el("div", { class: "bk-val" }, [String(n)]),
        el("div", { class: "tip" }, ["open tickets"])
      ]));
    });

    // by team
    var tb = $("#team-sla tbody"); clear(tb);
    Object.keys(D.teams).forEach(function (team) {
      var all = EXC.filter(function (e) { return e.team === team; });
      if (!all.length) return;
      var openT = all.filter(function (e) { return e.isOpen; });
      var resolved = all.filter(function (e) { return e.turnaround != null; });
      var avg = resolved.length ? (resolved.reduce(function (s, e) { return s + e.turnaround; }, 0) / resolved.length) : null;
      var within = all.filter(function (e) { return (e.isOpen ? e.age <= e.slaTarget : e.withinSla); }).length;
      var breaching = all.length - within;
      var pct = Math.round(100 * within / all.length);
      tb.appendChild(el("tr", {}, [
        el("td", {}, [el("b", {}, [team])]),
        el("td", { class: "num" }, [String(openT.length)]),
        el("td", { class: "num" }, [avg == null ? "—" : avg.toFixed(1) + "d"]),
        el("td", { class: "num" }, [String(within)]),
        el("td", { class: "num" }, [el("span", { class: breaching > 0 ? "sla-bad" : "" }, [String(breaching)])]),
        el("td", { class: "num" }, [el("span", { class: pct >= 90 ? "sla-ok" : "sla-bad" }, [pct + "%"])])
      ]));
    });

    // by person
    var pb = $("#person-sla tbody"); clear(pb);
    var people = [];
    Object.keys(D.teams).forEach(function (team) { D.teams[team].forEach(function (p) { people.push({ name: p, team: team }); }); });
    people.map(function (p) {
      var theirs = EXC.filter(function (e) { return e.assignee === p.name; });
      var openP = theirs.filter(function (e) { return e.isOpen; });
      var breach = openP.filter(function (e) { return !e.withinSla; }).length;
      var avgAge = openP.length ? (openP.reduce(function (s, e) { return s + e.age; }, 0) / openP.length) : null;
      return { p: p, total: theirs.length, open: openP.length, breach: breach, avgAge: avgAge };
    }).filter(function (r) { return r.total > 0; })
      .sort(function (a, b) { return b.breach - a.breach || (b.avgAge || 0) - (a.avgAge || 0); })
      .forEach(function (r) {
        pb.appendChild(el("tr", {}, [
          el("td", {}, [el("b", { class: r.breach > 0 ? "behind" : "" }, [r.p.name])]),
          el("td", {}, [r.p.team]),
          el("td", { class: "num" }, [String(r.open)]),
          el("td", { class: "num" }, [el("span", { class: r.breach > 0 ? "sla-bad" : "" }, [String(r.breach)])]),
          el("td", { class: "num" }, [r.avgAge == null ? "—" : r.avgAge.toFixed(1) + "d"])
        ]));
      });

    // overdue
    var ob = $("#overdue-table tbody"); clear(ob);
    open.filter(function (e) { return !e.withinSla; }).sort(function (a, b) { return (b.age - b.slaTarget) - (a.age - a.slaTarget); }).forEach(function (e) {
      var over = e.age - e.slaTarget;
      var row = el("tr", { style: "cursor:pointer" }, [
        el("td", { class: "mono" }, [e.id]),
        el("td", {}, [el("a", { class: "jira-link", href: "#" }, [e.jira])]),
        el("td", {}, [e.errorType]),
        el("td", {}, [sevPill(e.severity)]),
        el("td", {}, [e.assignee]),
        el("td", { class: "num" }, [e.age + "d"]),
        el("td", { class: "num" }, [e.slaTarget + "d"]),
        el("td", { class: "num" }, [el("span", { class: "sla-bad" }, ["+" + over + "d"])])
      ]);
      row.addEventListener("click", function () { showView("workbench"); openDrawer(e.id); });
      ob.appendChild(row);
    });
  }

  /* ============================ ADMIN ============================ */
  function renderAdmin() {
    var rb = $("#rules-table tbody"); clear(rb);
    D.rules.forEach(function (r) {
      var tog = el("span", { class: "toggle" + (r.enabled ? " on" : ""), role: "switch", "aria-checked": String(r.enabled), tabindex: "0", "aria-label": "Toggle " + r.name });
      tog.addEventListener("click", function (ev) { ev.stopPropagation(); r.enabled = !r.enabled; tog.classList.toggle("on", r.enabled); tog.setAttribute("aria-checked", String(r.enabled)); });
      var row = el("tr", { style: "cursor:pointer" }, [
        el("td", {}, [el("b", {}, [r.name]), el("div", { class: "tip mono" }, [r.id + " → " + r.errorType])]),
        el("td", {}, [el("span", { class: "tag" }, [r.type])]),
        el("td", { class: "mono" }, [r.target]),
        el("td", {}, [sevPill(r.severity)]),
        el("td", { class: "num" }, [tog])
      ]);
      row.addEventListener("click", function () { loadRuleEditor(r); });
      rb.appendChild(row);
    });
    loadRuleEditor(D.rules[0]);

    var rmt = $("#routing-table tbody"); clear(rmt);
    D.routing.forEach(function (r) {
      rmt.appendChild(el("tr", {}, [
        el("td", { class: "mono" }, [r.errorType]),
        el("td", {}, [r.team]),
        el("td", {}, [r.assignee]),
        el("td", { class: "mono" }, [r.project]),
        el("td", {}, [el("span", { class: "tag" }, [r.component])])
      ]));
    });

    var st = $("#sla-targets-table tbody"); clear(st);
    ["Critical", "High", "Medium", "Low"].forEach(function (s) {
      st.appendChild(el("tr", {}, [el("td", {}, [sevPill(s)]), el("td", { class: "num" }, [D.slaTargets[s] + " day" + (D.slaTargets[s] > 1 ? "s" : "")])]));
    });
  }

  function loadRuleEditor(r) {
    var f = $("#rule-form"); clear(f);
    function fr(label, control) { return el("div", { class: "form-row" }, [el("label", {}, [label]), control]); }
    f.appendChild(fr("Rule name", el("input", { type: "text", value: r.name })));
    f.appendChild(fr("Rule ID", el("input", { type: "text", value: r.id, readonly: "readonly" })));
    var typeSel = el("select", {});
    ["NOT_NULL", "REFERENTIAL", "RECONCILIATION", "RANGE"].forEach(function (t) {
      var o = el("option", { value: t }, [t]); if (t === r.type) o.selected = true; typeSel.appendChild(o);
    });
    f.appendChild(fr("Rule type", typeSel));
    f.appendChild(fr("Target table", (function () {
      var s = el("select", {}); D.sourceTables.forEach(function (t) { var o = el("option", { value: t }, [t]); if (t === r.target) o.selected = true; s.appendChild(o); }); return s;
    })()));
    f.appendChild(fr("Maps to error", el("input", { type: "text", value: r.errorType, readonly: "readonly" })));
    var sevSel = el("select", {});
    ["Critical", "High", "Medium", "Low"].forEach(function (s) { var o = el("option", { value: s }, [s]); if (s === r.severity) o.selected = true; sevSel.appendChild(o); });
    f.appendChild(fr("Severity", sevSel));
    f.appendChild(fr("Expression", el("textarea", { rows: "3", style: "width:100%;background:#0c0e13;border:1px solid var(--line);color:#c8d3ec;border-radius:6px;padding:8px;font-family:var(--mono);font-size:11px;" }, [r.expression])));
    f.appendChild(fr("Enabled", el("span", { class: "toggle" + (r.enabled ? " on" : "") })));
    var actions = el("div", { style: "display:flex;gap:8px;margin-top:6px;" }, [
      el("button", { class: "btn primary sm" }, ["Save (mock)"]),
      el("button", { class: "btn sm" }, ["Run dry-validation (mock)"])
    ]);
    actions.querySelector(".primary").addEventListener("click", function () { alert("Mock: saved rule " + r.id + "."); });
    f.appendChild(actions);
    f.appendChild(el("div", { class: "muted-note" }, ["Editing is mocked in this prototype — no changes are persisted to BigQuery."]));
  }

  /* ============================ INIT ============================ */
  buildHead();
  renderBody();
  renderHome();
  showView("home");
})();
