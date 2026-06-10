/* Wonder Inventory Data-Quality Console — APPROVED build
   Variant A "Dense Workbench" base + Variant C dashboard-as-home, dark-blue, condensed.
   Vanilla JS. No build step, works on file://. Reads global DATA from data.js. */
(function () {
  "use strict";
  var D = window.DATA;
  var API = window.WONDER_API || "/api";
  // POST to the API then hard-reload so every screen reflects the new server state.
  function apiPost(path, body, okMsg) {
    return fetch(API + path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : null
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (res) {
      if (okMsg) alert(okMsg);
      location.reload();
      return res;
    }).catch(function (e) { alert("Action failed: " + e); });
  }
  // Real Jira deep-link when connected to a live Jira (else a mock notice).
  function jiraUrl(key) {
    var b = D.meta && D.meta.jiraBaseUrl;
    return (b && key && key !== "—") ? b.replace(/\/+$/, "") + "/browse/" + key : null;
  }
  function openJira(key) {
    var u = jiraUrl(key);
    if (u) window.open(u, "_blank");
    else alert("Mock: would open " + key + " in JIRA (set TICKET_SINK=jira for live links).");
  }
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

  // runtime mutable copy of exceptions so mock actions persist for the session
  var EXC = D.exceptions.map(function (e) { return Object.assign({}, e); });

  // Inventory movement category for an exception (drives the "by movement type" breakout).
  function movementOf(e) {
    var t = e.snapshot && e.snapshot.txn_type;
    if (e.errorType === "TRANSFER_WAREHOUSE_IMBALANCE") return "Transfer";
    if (e.errorType === "MISSING_LOT_EXPIRATION") return "Expiration";
    if (t === "PO_RECEIPT" || t === "ADD") return "PO Receipt";
    if (t === "CONSUME" || t === "PRODUCE_CONSUME") return "Production";
    if (t === "SHIP") return "Sales / Outbound";
    if (e.table === "po_table") return "PO Receipt"; // 3-way match / conversion are PO-driven
    return "Adjustment";
  }

  /* ============================ NAVIGATION ============================ */
  var VIEWS = ["dashboard", "workbench", "sla", "admin"];
  function showView(name) {
    $$(".view").forEach(function (v) { v.classList.toggle("active", v.id === "view-" + name); });
    $$(".nav-item").forEach(function (b) { b.classList.toggle("active", b.dataset.view === name); });
    if (name === "dashboard") renderDashboard();
    if (name === "sla") renderSLA();
    if (name === "admin") renderAdmin();
  }
  $$(".nav-item").forEach(function (b) { b.addEventListener("click", function () { showView(b.dataset.view); }); });

  document.addEventListener("keydown", function (e) {
    if (e.target.matches && e.target.matches("input,select,textarea")) {
      if (e.key === "Escape") e.target.blur();
      return;
    }
    if (e.key === "Escape") { closeDrawer(); return; }
    if (e.key === "/") { e.preventDefault(); showView("workbench"); $("#f-search").focus(); return; }
    var idx = ["1", "2", "3", "4"].indexOf(e.key);
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
  // Derive facility/system options from the actual exceptions so filters match live data.
  var exVals = function (key) { return Array.from(new Set(EXC.map(function (e) { return e[key]; }).filter(Boolean))).sort(); };
  fillSelect($("#f-facility"), exVals("facility"), "All facilities");
  fillSelect($("#f-system"), exVals("system"), "All systems");
  fillSelect($("#f-errortype"), D.errorTypes.map(function (t) { return t.type; }), "All error types");
  fillSelect($("#f-severity"), ["Urgent", "High", "Medium", "Low"], "All severities");
  fillSelect($("#f-status"), exVals("jiraStatus"), "All statuses");
  fillSelect($("#f-team"), Object.keys(D.teams), "All teams");
  fillSelect($("#f-owner"), exVals("primaryOwner"), "All owners");

  /* ============================ WORKBENCH GRID ============================ */
  var COLS = [
    { key: "id", label: "Error ID", cls: "mono" },
    { key: "runDate", label: "Run Date", cls: "mono" },
    { key: "errorType", label: "Error Type" },
    { key: "severity", label: "Severity" },
    { key: "facility", label: "Facility", cls: "mono" },
    { key: "system", label: "System" },
    { key: "entityKey", label: "Entity Key", cls: "mono" },
    { key: "team", label: "Routed Team" },
    { key: "primaryOwner", label: "Primary Owner" },
    { key: "currentHolder", label: "Assignee", title: "Current holder when handed off — blank means the primary owner still has it." },
    { key: "jira", label: "JIRA Key", cls: "mono" },
    { key: "jiraStatus", label: "JIRA Status" },
    { key: "age", label: "Age (d)", cls: "num", num: true },
    { key: "recurrence", label: "Recurrence", cls: "num", num: true, title: "How many times this same error (same rule + entity) has recurred in the last 30 days. ×4 or more is flagged as a repeat offender." }
  ];
  var sortKey = "severity", sortDir = 1;
  var selected = {}; // id -> true
  var drill = null;  // { label, test(e) } — dashboard drill-down

  var SEVRANK = { Urgent: 0, High: 1, Medium: 2, Low: 3 };

  function getFilters() {
    return {
      q: $("#f-search").value.trim().toLowerCase(),
      facility: $("#f-facility").value,
      system: $("#f-system").value,
      errortype: $("#f-errortype").value,
      severity: $("#f-severity").value,
      status: $("#f-status").value,
      team: $("#f-team").value,
      owner: $("#f-owner").value
    };
  }

  function filteredRows() {
    var f = getFilters();
    var rows = EXC.filter(function (e) {
      if (drill && !drill.test(e)) return false;
      if (f.facility && e.facility !== f.facility) return false;
      if (f.system && e.system !== f.system) return false;
      if (f.errortype && e.errorType !== f.errortype) return false;
      if (f.severity && e.severity !== f.severity) return false;
      if (f.status && e.jiraStatus !== f.status) return false;
      if (f.team && e.team !== f.team) return false;
      if (f.owner && e.primaryOwner !== f.owner) return false;
      if (f.q) {
        var hay = (e.id + " " + e.entityKey + " " + e.jira + " " + e.errorType + " " + e.primaryOwner + " " + e.currentHolder + " " + e.facility).toLowerCase();
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
      if (c.title) th.title = c.title;
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
        else if (c.key === "currentHolder") {
          // Only show an assignee once it's been handed off; blank means the primary owner still holds it.
          var handed = e.currentHolder && e.currentHolder !== e.primaryOwner;
          td.textContent = handed ? e.currentHolder : "";
          if (handed) td.appendChild(el("span", { class: "subtag", title: "Held " + e.heldDays + "d" }, ["↳ held " + e.heldDays + "d"]));
        }
        else if (c.key === "jira") {
          var a = el("a", { class: "jira-link", href: jiraUrl(v) || "#", title: "Open " + v + " in JIRA" }, [v]);
          a.addEventListener("click", function (ev) { ev.stopPropagation(); ev.preventDefault(); openJira(v); });
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
          td.title = "Recurred " + v + " time" + (v === 1 ? "" : "s") + " in the last 30 days";
        }
        else td.textContent = v;
        tr.appendChild(td);
      });
      tr.addEventListener("click", function () { openDrawer(e.id); });
      tr.addEventListener("keydown", function (ev) { if (ev.key === "Enter") openDrawer(e.id); });
      tb.appendChild(tr);
    });
    $("#wb-result-meta").innerHTML = "Showing <b>" + rows.length + "</b> of <b>" + EXC.length + "</b> exceptions";
    $("#nav-open-count").textContent = openExc().length;
    updateBulkBar();
    if (activeId) { var ar = tb.querySelector('tr[data-id="' + activeId + '"]'); if (ar) ar.classList.add("active"); }
  }

  function updateBulkBar() {
    var n = Object.keys(selected).length;
    var bar = $("#bulkbar");
    bar.classList.toggle("show", n > 0);
    $("#bulk-count").textContent = n + " selected";
  }

  /* ---- Drill-down from the dashboard ---- */
  function clearSelects() {
    $$("#wb-toolbar select").forEach(function (s) { s.value = ""; });
    $("#f-search").value = "";
  }
  function renderDrillChip() {
    var bar = $("#wb-drill");
    clear(bar);
    if (!drill) { bar.classList.remove("show"); return; }
    bar.classList.add("show");
    bar.appendChild(el("span", { class: "drill-from" }, ["Drilled from dashboard:"]));
    var chip = el("span", { class: "fchip" }, [drill.label]);
    var x = el("button", { class: "fchip-x", title: "Clear drill-down", "aria-label": "Clear drill-down" }, ["✕"]);
    x.addEventListener("click", function () { drill = null; renderDrillChip(); renderBody(); });
    chip.appendChild(x);
    bar.appendChild(chip);
  }
  function drillTo(label, test) {
    clearSelects();
    drill = { label: label, test: test };
    showView("workbench");
    renderDrillChip();
    renderBody();
  }
  // Accountability queue: everything a person is the primary owner of (handed-off included).
  function ownerQueue(name) {
    clearSelects(); drill = null; renderDrillChip();
    $("#f-owner").value = name;
    showView("workbench");
    renderBody();
  }

  $$("#wb-toolbar select, #wb-toolbar input").forEach(function (c) {
    c.addEventListener("input", renderBody);
    c.addEventListener("change", renderBody);
  });
  $("#f-clear").addEventListener("click", function () {
    clearSelects(); drill = null; renderDrillChip(); renderBody();
  });

  // Bulk actions (persisted via the API, then reload)
  function selectedRows() { return EXC.filter(function (e) { return selected[e.id]; }); }
  function postAll(rows, fn) { return Promise.all(rows.map(fn)); }
  $("#bulk-reassign").addEventListener("click", function () {
    var rows = selectedRows(); if (!rows.length) return;
    var who = prompt("Reassign " + rows.length + " exception(s) to (assignee name):", "Sarah Chen");
    if (!who) return;
    postAll(rows, function (e) {
      return fetch(API + "/exceptions/" + e.pk + "/assign", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ assignee: who }) });
    }).then(function () { alert("Reassigned " + rows.length + " ticket(s) to " + who + "."); location.reload(); });
  });
  $("#bulk-comment").addEventListener("click", function () {
    var rows = selectedRows(); if (!rows.length) return;
    prompt("Add a comment to " + rows.length + " ticket(s):", "Investigating batch root cause.");
    alert("Mock: comment posted to " + rows.length + " JIRA ticket(s).");
  });
  $("#bulk-resolve").addEventListener("click", function () {
    var rows = selectedRows(); if (!rows.length) return;
    postAll(rows, function (e) { return fetch(API + "/exceptions/" + e.pk + "/resolve", { method: "POST" }); })
      .then(function () { alert("Marked " + rows.length + " ticket(s) resolved."); location.reload(); });
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
    sub.appendChild(el("a", { class: "jira-link", href: jiraUrl(e.jira) || "#", target: "_blank", html: e.jira }));
    sub.appendChild(el("span", { class: "tip" }, ["Age " + e.age + "d / " + e.slaTarget + "d SLA · " + (e.withinSla ? "within SLA" : "BREACHING")]));

    var body = $("#dr-body"); clear(body);

    // Validation rule that fired — built here, appended at the BOTTOM (after Notes).
    var rsec = el("div", { class: "section" }, [el("h3", {}, ["Validation rule that fired"])]);
    var rbox = el("div", { class: "rule-box" }, [
      el("div", { class: "rname" }, [(rule.name || e.errorType) + "  —  " + (rule.type || meta.ruleType || "")]),
      el("div", { class: "tip", html: meta.desc || "" }),
      el("code", { text: rule.expression || "(rule expression unavailable)" })
    ]);
    rsec.appendChild(rbox);

    // Offending data snapshot — hide backend-only fields; fold UoM into the qty line.
    var snap = e.snapshot;
    var SNAP_HIDE = { tolerance_pct: 1, uom_match: 1, status: 1, ordered_uom: 1, received_uom: 1 };
    var dsec = el("div", { class: "section" }, [el("h3", {}, ["Offending " + e.table + " snapshot"])]);
    var kv = el("div", { class: "kv" });
    Object.keys(snap).forEach(function (k) {
      if (SNAP_HIDE[k]) return;
      var val = snap[k];
      if (k === "ordered_qty" && snap.ordered_uom) val = fmtNum(val) + " " + snap.ordered_uom;
      else if (k === "received_qty" && snap.received_uom) val = fmtNum(val) + " " + snap.received_uom;
      else if (k === "over_by_pct" && val != null) val = fmtNum(val) + "%";
      var neg = (typeof val === "number" && val < 0) || val === null;
      kv.appendChild(el("div", { class: "k" }, [k]));
      kv.appendChild(el("div", { class: "v" + (neg ? " neg" : "") }, [val === null ? "NULL" : String(val)]));
    });
    dsec.appendChild(kv);
    body.appendChild(dsec);

    // Why this flagged — contributing PO line vs ledger receipt events (live BigQuery lookup)
    if (e.errorType === "PO_OVER_RECEIPT" || e.errorType === "PO_IMPLAUSIBLE_QTY") {
      var bsec = el("div", { class: "section" }, [el("h3", {}, ["Why this flagged — contributing records"])]);
      var bbox = el("div", { class: "tip" }, ["Loading the PO line and ledger receipts…"]);
      bsec.appendChild(bbox);
      body.appendChild(bsec);
      fetch(API + "/exceptions/" + e.pk + "/breakdown")
        .then(function (r) { return r.json(); })
        .then(function (d) { if (activeId === id) renderBreakdown(bbox, d); })
        .catch(function () { bbox.textContent = "Breakdown unavailable."; });
    }

    // Ownership & assignment (incl. sub-assignment concept — under review)
    var route = D.routing.filter(function (r) { return r.errorType === e.errorType; })[0] || {};
    var osec = el("div", { class: "section" }, [el("h3", {}, ["Ownership & assignment"])]);
    var handed = !!(e.currentHolder && e.currentHolder !== e.primaryOwner);
    var okv = el("div", { class: "kv" }, [
      el("div", { class: "k" }, ["routed_team"]), el("div", { class: "v" }, [e.team]),
      el("div", { class: "k" }, ["primary_owner"]), el("div", { class: "v" }, [e.primaryOwner + "  (accountable)"]),
      el("div", { class: "k" }, ["currently_with"]), el("div", { class: "v" }, [e.currentHolder + " · held " + e.heldDays + "d (since " + e.heldSince + ")"]),
      el("div", { class: "k" }, ["jira_project"]), el("div", { class: "v" }, [route.project || "WIQ"]),
      el("div", { class: "k" }, ["recurrence_30d"]), el("div", { class: "v" }, ["×" + e.recurrence])
    ]);
    osec.appendChild(okv);
    if (handed && e.subAssign) {
      var sa = e.subAssign;
      osec.appendChild(el("div", { class: "subassign-box" }, [
        el("div", { class: "sa-head" }, ["↳ Handed off to ", el("b", {}, [sa.toPerson + (sa.toTeam ? " · " + sa.toTeam : "")])]),
        el("div", { class: "tip" }, ["By " + e.primaryOwner + " on " + (sa.at || "").replace("T", " ").replace("Z", " UTC") + " — " + e.primaryOwner + " stays primary owner (accountable)."]),
        el("div", { class: "sa-sla" }, ["SLA does not reset · current holder " + e.currentHolder + " has had it " + e.heldDays + " day(s)"])
      ]));
    } else {
      osec.appendChild(el("div", { class: "tip", style: "margin-top:8px" }, ["Held by the primary owner. Use “Hand off…” to give the work to someone else while staying accountable (SLA doesn’t reset)."]));
    }
    body.appendChild(osec);

    // JIRA timeline (includes ownership transitions)
    var tsec = el("div", { class: "section" }, [el("h3", {}, ["JIRA & ownership timeline · " + e.jira])]);
    var ul = el("ul", { class: "timeline" });
    e.timeline.forEach(function (t) {
      var auto = /auto/i.test(t.status) || t.by === "batch-validator";
      var handoff = /sub-assigned|handed off/i.test(t.status);
      var li = el("li", { class: auto ? "auto" : (handoff ? "handoff" : "") }, [
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

    body.appendChild(rsec);  // "Validation rule that fired" goes last (kept for Pavel to see the SQL)

    // action buttons (rebind to this row) — persisted via the API
    var statusSel = $("#dr-status");
    var STATUS_OPTS = ["Open", "In Progress", "In Review", "Resolved"];  // app wording; mapped to Jira on push
    var opts = STATUS_OPTS.indexOf(e.jiraStatus) > -1 ? STATUS_OPTS
      : [e.jiraStatus].concat(STATUS_OPTS);
    statusSel.innerHTML = opts.map(function (s) {
      return '<option' + (s === e.jiraStatus ? ' selected' : '') + '>' + s + '</option>';
    }).join("");
    statusSel.onchange = function () {
      if (statusSel.value !== e.jiraStatus) apiPost("/exceptions/" + e.pk + "/transition", { to: statusSel.value });
    };
    $("#dr-jira").onclick = function () { openJira(e.jira); };
    $("#dr-assign").onclick = function () {
      var w = prompt("Reassign the PRIMARY OWNER of " + e.id + " (accountability moves to this person, updates the Jira assignee):", e.primaryOwner);
      if (w) apiPost("/exceptions/" + e.pk + "/assign", { assignee: w });
    };
    $("#dr-subassign").onclick = function () {
      var p = prompt("Hand off " + e.id + " to which person? (they do the work; " + e.primaryOwner + " stays accountable, SLA doesn’t reset)", e.subAssign ? e.subAssign.toPerson : "");
      if (!p) return;
      var t = prompt("Their team (optional):", e.subAssign ? e.subAssign.toTeam : "");
      apiPost("/exceptions/" + e.pk + "/subassign", { person: p, team: t || null });
    };
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

  function fmtNum(v) { if (v == null) return "—"; var n = Number(v); if (isNaN(n)) return String(v); return n.toLocaleString("en-US", { maximumFractionDigits: 2 }); }
  function renderBreakdown(box, d) {
    clear(box); box.className = "";
    if (!d || !d.available) {
      box.appendChild(el("div", { class: "tip" }, [d && d.error ? "Breakdown unavailable: " + d.error
        : "Live record breakdown is available when the app is connected to BigQuery."]));
      return;
    }
    box.appendChild(el("div", { class: "tip", style: "margin-bottom:8px" }, [
      "Ordered " + fmtNum(d.ordered_qty) + " " + (d.ordered_uom || "") + " · received " + fmtNum(d.received_qty) +
      " " + (d.received_uom || "") + " (" + d.over_by_pct + "% over) · " + d.ledger_count + " ledger receipt(s)"]));
    if (d.uom_match === false) {
      box.appendChild(el("div", { class: "dup-warn" }, ["⚠ Unit-of-measure mismatch — ordered in " +
        (d.ordered_uom || "?") + " but received in " + (d.received_uom || "?") + ". The over-receipt % may be an " +
        "apples-to-oranges comparison until the UoMs are reconciled."]));
    }
    if (d.duplicate_suspected) {
      box.appendChild(el("div", { class: "dup-warn" }, ["⚠ Possible duplicate receipt — multiple identical " +
        "Add / PO Receipt events. Inventory was added (l1 = Add), not adjusted out or transferred, so the same " +
        "receipt looks double-logged."]));
    }
    var tbl = el("table", { class: "mini" });
    tbl.appendChild(el("thead", { html: "<tr><th>Source</th><th class='num'>Qty</th><th>UoM</th><th>Type / action</th><th>Facility</th><th>When</th></tr>" }));
    var tb = el("tbody");
    (d.rows || []).forEach(function (r) {
      var typ = r.source === "PO" ? (r.order_type || "—")
        : (r.l1_action || "") + (r.l2_action ? " / " + r.l2_action : "");
      tb.appendChild(el("tr", { class: r.source === "PO" ? "bd-po" : "" }, [
        el("td", {}, [el("span", { class: "tag" }, [r.source])]),
        el("td", { class: "num" }, [fmtNum(r.qty)]),
        el("td", {}, [r.uom || "—"]),
        el("td", {}, [typ]),
        el("td", {}, [r.facility || "—"]),
        el("td", { class: "mono", style: "font-size:11px" }, [r.ts ? r.ts.replace("T", " ").slice(0, 19) : "—"])
      ]));
    });
    tbl.appendChild(tb);
    box.appendChild(tbl);
  }

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
    return { open: open.length, newToday: newToday.length, autoClosedToday: autoClosedToday.length, avgTat: avgTat, pctSla: pctSla, withinCount: withinAll.length, total: EXC.length };
  }

  /* ============================ DASHBOARD ============================ */
  // clickable horizontal-bar list; entries: [label, value, drillValue]
  function hbarDrill(container, entries, drillKind) {
    clear(container);
    var mx = Math.max.apply(null, entries.map(function (e) { return e[1]; }).concat([1]));
    entries.forEach(function (e, i) {
      var row = el("div", { class: "hbar" + (drillKind ? " clickable" : ""), title: e[0] }, [
        el("div", { class: "hlabel" }, [e[0]]),
        el("div", { class: "track" }, [el("div", { class: "fill", style: "width:" + Math.round(100 * e[1] / mx) + "%" })]),
        el("div", { class: "hval" }, [String(e[1])])
      ]);
      if (drillKind) row.addEventListener("click", function () { drillKind(e[2] != null ? e[2] : e[0]); });
      container.appendChild(row);
    });
  }

  function renderDashboard() {
    var m = metrics();

    // ---- KPI tiles (clickable → drill into workbench) ----
    var k = $("#dash-kpis"); clear(k);
    var breaching = openExc().filter(function (e) { return !e.withinSla; }).length;
    var kpis = [
      { label: "Open exceptions", val: m.open, color: "var(--bad)", chip: breaching + " breaching", good: false,
        drill: ["Open exceptions", function (e) { return e.isOpen; }] },
      { label: "New today", val: m.newToday, color: "var(--high)", chip: "run " + D.meta.runDate, good: false,
        drill: ["New today · run " + D.meta.runDate, function (e) { return e.created === D.meta.runDate; }] },
      { label: "Auto-closed today", val: m.autoClosedToday, color: "var(--teal)", chip: "flagship", good: true,
        drill: ["Auto-closed today", function (e) { return e.autoClosed && e.resolved === D.meta.runDate; }] },
      { label: "Avg turnaround", val: m.avgTat.toFixed(1) + "d", color: "var(--brand-2)", chip: "across resolved", good: true, drill: null },
      { label: "% within SLA", val: m.pctSla + "%", color: "var(--ok)", chip: m.withinCount + " of " + m.total + " on target", good: m.pctSla >= 90,
        drill: ["Breaching SLA (open)", function (e) { return e.isOpen && !e.withinSla; }] }
    ];
    kpis.forEach(function (t) {
      var tile = el("div", { class: "kpi" + (t.drill ? " clickable" : "") }, [
        el("div", { class: "label" }, [t.label]),
        el("div", { class: "value" }, [String(t.val)])
      ]);
      if (t.drill) tile.addEventListener("click", function () { drillTo(t.drill[0], t.drill[1]); });
      k.appendChild(tile);
    });

    renderTrend();
    renderSystemDonut();

    var byType = countBy(EXC, "errorType");
    hbarDrill($("#type-bars"), Object.keys(byType).map(function (k2) { return [k2, byType[k2], k2]; }).sort(function (a, b) { return b[1] - a[1]; }),
      function (v) { drillTo("Type: " + v, function (e) { return e.errorType === v; }); });

    var byFac = countBy(EXC, "facility");
    hbarDrill($("#facility-bars"), Object.keys(byFac).map(function (f) { return [f, byFac[f], f]; })
        .sort(function (a, b) { return b[1] - a[1]; }).slice(0, 10),
      function (v) { drillTo("Facility: " + v, function (e) { return e.facility === v; }); });

    var byMove = countBy(EXC, movementOf);
    hbarDrill($("#movement-bars"), Object.keys(byMove).map(function (mt) { return [mt, byMove[mt], mt]; }).sort(function (a, b) { return b[1] - a[1]; }),
      function (v) { drillTo("Movement: " + v, function (e) { return movementOf(e) === v; }); });

    hbarDrill($("#sev-bars"), ["Urgent", "High", "Medium", "Low"].map(function (s) {
      return [s, EXC.filter(function (e) { return e.severity === s; }).length, s];
    }), function (v) { drillTo("Severity: " + v, function (e) { return e.severity === v; }); });

    renderRecurringLeaderboard();
  }

  function renderTrend() {
    var data = D.trend || [];
    if (data.length < 2) {
      $("#trend-chart").innerHTML = '<div class="tip" style="padding:24px 4px">' +
        (data.length ? "Only one validation run so far — the trend builds as daily runs accumulate." :
         "No runs yet.") + "</div>";
      return;
    }
    var W = 600, H = 190, padL = 26, padB = 22, padT = 10, padR = 8;
    var iw = W - padL - padR, ih = H - padB - padT;
    var maxV = Math.max.apply(null, data.map(function (d) { return d.count; })) || 1;
    var stepX = iw / (data.length - 1);
    var x = function (i) { return padL + i * stepX; };
    var y = function (v) { return padT + ih - (v / maxV) * ih; };

    var pts = data.map(function (d, i) { return x(i) + "," + y(d.count); }).join(" ");
    var autoPts = data.map(function (d, i) { return x(i) + "," + y(d.autoClosed); }).join(" ");
    var area = "M" + x(0) + "," + (padT + ih) + " L" + pts.replace(/ /g, " L") + " L" + x(data.length - 1) + "," + (padT + ih) + " Z";

    var svg = '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Error trend line chart">';
    svg += '<defs><linearGradient id="grad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--accent)"/><stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs>';
    for (var g = 0; g <= 4; g++) {
      var gv = Math.round(maxV * g / 4);
      var gy = y(gv);
      svg += '<line class="gridline" x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy + '"/>';
      svg += '<text x="' + (padL - 5) + '" y="' + (gy + 3) + '" text-anchor="end">' + gv + '</text>';
    }
    svg += '<path class="area" d="' + area + '"/>';
    svg += '<polyline class="line" points="' + pts + '"/>';
    svg += '<polyline class="line auto-line" points="' + autoPts + '"/>';
    data.forEach(function (d, i) {
      svg += '<circle class="pt" cx="' + x(i) + '" cy="' + y(d.count) + '" r="2.4"><title>' + d.date + ': ' + d.count + ' flagged</title></circle>';
      if (i % 3 === 0 || i === data.length - 1)
        svg += '<text x="' + x(i) + '" y="' + (H - 6) + '" text-anchor="middle">' + d.date.slice(5) + '</text>';
    });
    svg += '</svg>';
    $("#trend-chart").innerHTML = svg;
  }

  var SYS_PAL = ["var(--accent)", "var(--brand-2)", "var(--teal)", "var(--ok)", "var(--high)", "var(--med)"];
  function renderSystemDonut() {
    var bySys = countBy(EXC, "system");
    var entries = Object.keys(bySys).map(function (s) { return [s, bySys[s]]; }).sort(function (a, b) { return b[1] - a[1]; });
    var color = function (i) { return SYS_PAL[i % SYS_PAL.length]; };
    var total = entries.reduce(function (a, b) { return a + b[1]; }, 0) || 1;
    var r = 54, cx = 66, cy = 66, sw = 20, circ = 2 * Math.PI * r, offset = 0, arcs = "";
    entries.forEach(function (en, i) {
      var len = circ * (en[1] / total);
      arcs += '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="' + color(i) + '" stroke-width="' + sw +
        '" stroke-dasharray="' + len + ' ' + (circ - len) + '" stroke-dashoffset="' + (-offset) + '" transform="rotate(-90 ' + cx + ' ' + cy + ')"><title>' + en[0] + ': ' + en[1] + '</title></circle>';
      offset += len;
    });
    var wrap = $("#system-donut"); clear(wrap);
    wrap.className = "donut-wrap";
    var svgWrap = el("div", { html: '<svg width="132" height="132" viewBox="0 0 132 132" role="img" aria-label="Errors by system">' + arcs +
      '<text x="' + cx + '" y="' + (cy - 1) + '" text-anchor="middle" fill="var(--text)" font-size="21" font-weight="800">' + total + '</text>' +
      '<text x="' + cx + '" y="' + (cy + 15) + '" text-anchor="middle" fill="var(--text-faint)" font-size="10">errors</text></svg>' });
    wrap.appendChild(svgWrap);
    var legend = el("div", { class: "donut-legend" });
    entries.forEach(function (en, i) {
      var row = el("div", { class: "row clickable" }, [
        el("span", { class: "sw", style: "background:" + color(i) }),
        document.createTextNode(en[0]),
        el("span", { class: "lv" }, [en[1] + " · " + Math.round(100 * en[1] / total) + "%"])
      ]);
      row.addEventListener("click", function () { drillTo("System: " + en[0], function (e) { return e.system === en[0]; }); });
      legend.appendChild(row);
    });
    wrap.appendChild(legend);
  }

  function renderRecurringLeaderboard() {
    var c = $("#recurring-lb"); clear(c);
    var lb = el("div", { class: "lb" });
    D.recurring.forEach(function (r, i) {
      var trCls = r.trend === "up" ? "tr-up" : r.trend === "down" ? "tr-down" : "tr-flat";
      var trIco = r.trend === "up" ? "▲ rising" : r.trend === "down" ? "▼ falling" : "— flat";
      var row = el("div", { class: "lb-row clickable" }, [
        el("div", { class: "lb-rank" }, [String(i + 1)]),
        el("div", {}, [
          el("div", { class: "lb-title" }, [r.errorType.replace(/_/g, " ")]),
          el("div", { class: "lb-sub" }, [r.facility + " · " + r.team + " · recurred " + r.count30d + "× / 30d"])
        ]),
        el("div", { class: "tr-ico " + trCls }, [trIco]),
        el("div", { class: "lb-count" + (r.count30d >= 4 ? " hot" : "") }, ["×" + r.count30d])
      ]);
      row.addEventListener("click", function () {
        drillTo(r.errorType.replace(/_/g, " ") + " @ " + r.facility, function (e) { return e.errorType === r.errorType && e.facility === r.facility; });
      });
      lb.appendChild(row);
    });
    c.appendChild(lb);
  }

  /* ============================ SLA ============================ */
  function renderSLA() {
    var open = openExc();
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

    // ---- By owner (accountability): keyed on primary owner; includes handed-off tickets ----
    var pb = $("#person-sla tbody"); clear(pb);
    var owners = {};
    EXC.forEach(function (e) {
      var o = e.primaryOwner; if (!o) return;
      (owners[o] = owners[o] || []).push(e);
    });
    Object.keys(owners).map(function (name) {
      var theirs = owners[name];
      var openP = theirs.filter(function (e) { return e.isOpen; });
      var handed = openP.filter(function (e) { return e.currentHolder && e.currentHolder !== name; }).length;
      var breach = openP.filter(function (e) { return !e.withinSla; }).length;
      var avgAge = openP.length ? (openP.reduce(function (s, e) { return s + e.age; }, 0) / openP.length) : null;
      return { name: name, team: theirs[0].team, total: theirs.length, open: openP.length, handed: handed, breach: breach, avgAge: avgAge };
    }).filter(function (r) { return r.total > 0; })
      .sort(function (a, b) { return b.breach - a.breach || (b.avgAge || 0) - (a.avgAge || 0); })
      .forEach(function (r) {
        var tr = el("tr", { class: "clickrow", title: "Open " + r.name + "'s accountability queue (everything they own, handed-off included)" }, [
          el("td", {}, [el("b", { class: r.breach > 0 ? "behind" : "" }, [r.name])]),
          el("td", {}, [r.team]),
          el("td", { class: "num" }, [String(r.open)]),
          el("td", { class: "num" }, [r.handed ? el("span", { class: "subtag" }, ["↳ " + r.handed]) : document.createTextNode("—")]),
          el("td", { class: "num" }, [el("span", { class: r.breach > 0 ? "sla-bad" : "" }, [String(r.breach)])]),
          el("td", { class: "num" }, [r.avgAge == null ? "—" : r.avgAge.toFixed(1) + "d"])
        ]);
        tr.addEventListener("click", function () { ownerQueue(r.name); });
        pb.appendChild(tr);
      });

    // ---- By holder (active work): keyed on whoever currently holds each OPEN ticket ----
    var hb = $("#holder-sla tbody"); clear(hb);
    var holders = {};
    openExc().forEach(function (e) {
      var h = e.currentHolder || e.primaryOwner; if (!h) return;
      (holders[h] = holders[h] || []).push(e);
    });
    Object.keys(holders).map(function (name) {
      var held = holders[name];
      var handedToThem = held.filter(function (e) { return e.primaryOwner && e.primaryOwner !== name; }).length;
      var breach = held.filter(function (e) { return !e.withinSla; }).length;
      var totalHeld = held.reduce(function (s, e) { return s + (e.heldDays || 0); }, 0);
      var avgHeld = held.length ? totalHeld / held.length : 0;
      return { name: name, holding: held.length, handedToThem: handedToThem, breach: breach, avgHeld: avgHeld, totalHeld: totalHeld };
    }).sort(function (a, b) { return b.totalHeld - a.totalHeld || b.holding - a.holding; })
      .forEach(function (r) {
        var tr = el("tr", { class: "clickrow", title: "Show the tickets " + r.name + " is currently holding" }, [
          el("td", {}, [el("b", {}, [r.name])]),
          el("td", { class: "num" }, [String(r.holding)]),
          el("td", { class: "num" }, [r.handedToThem ? el("span", { class: "subtag" }, ["↳ " + r.handedToThem]) : document.createTextNode("—")]),
          el("td", { class: "num" }, [el("span", { class: r.breach > 0 ? "sla-bad" : "" }, [String(r.breach)])]),
          el("td", { class: "num" }, [r.avgHeld.toFixed(1) + "d"]),
          el("td", { class: "num" }, [String(r.totalHeld) + "d"])
        ]);
        tr.addEventListener("click", function () { drillTo("Currently held by: " + r.name, function (e) { return e.isOpen && (e.currentHolder || e.primaryOwner) === r.name; }); });
        hb.appendChild(tr);
      });

    var ob = $("#overdue-table tbody"); clear(ob);
    open.filter(function (e) { return !e.withinSla; }).sort(function (a, b) { return (b.age - b.slaTarget) - (a.age - a.slaTarget); }).forEach(function (e) {
      var over = e.age - e.slaTarget;
      var row = el("tr", { style: "cursor:pointer" }, [
        el("td", { class: "mono" }, [e.id]),
        el("td", {}, [el("a", { class: "jira-link", href: "#" }, [e.jira])]),
        el("td", {}, [e.errorType]),
        el("td", {}, [sevPill(e.severity)]),
        el("td", {}, [e.assignee]),
        el("td", {}, [e.subAssign ? el("span", { class: "subtag" }, ["↳ " + e.subAssign.toTeam]) : document.createTextNode("—")]),
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
    ["Urgent", "High", "Medium", "Low"].forEach(function (s) {
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
    ["Urgent", "High", "Medium", "Low"].forEach(function (s) { var o = el("option", { value: s }, [s]); if (s === r.severity) o.selected = true; sevSel.appendChild(o); });
    f.appendChild(fr("Severity", sevSel));
    f.appendChild(fr("Expression / SQL", el("textarea", { rows: "20", style: "width:100%;background:var(--surface-3);border:1px solid var(--line);color:#c8d3ec;border-radius:6px;padding:8px;font-family:var(--mono);font-size:11px;white-space:pre;" }, [r.expression])));
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
  var runBtn = $("#run-btn");
  if (runBtn) runBtn.addEventListener("click", function () {
    runBtn.disabled = true; runBtn.textContent = "Running…";
    fetch(API + "/run", { method: "POST" }).then(function (r) { return r.json(); }).then(function (res) {
      alert("Validation run " + res.ran + " complete — scanned " + res.scanned + ", " +
        res.seen + " issues seen, " + res["new"] + " new, " + res.autoClosed + " auto-closed.");
      location.reload();
    }).catch(function (e) { alert("Run failed: " + e); runBtn.disabled = false; runBtn.textContent = "↻ Run validation"; });
  });
  var syncBtn = $("#sync-btn");
  if (syncBtn) syncBtn.addEventListener("click", function () {
    syncBtn.disabled = true; syncBtn.textContent = "Syncing…";
    fetch(API + "/sync", { method: "POST" }).then(function (r) { return r.json(); }).then(function (res) {
      alert("Synced from Jira — polled " + res.polled + " issue(s): " + res.status_updates + " status update(s), " +
        res.closed + " closed, " + res.reopened + " reopened.");
      location.reload();
    }).catch(function (e) { alert("Sync failed: " + e); syncBtn.disabled = false; syncBtn.textContent = "⟲ Sync from Jira"; });
  });
  buildHead();
  renderBody();
  showView("dashboard");
})();
