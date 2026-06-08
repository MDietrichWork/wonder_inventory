/* Wonder Inventory Data-Quality Console — Variant C
   Sample data. run_date being viewed = 2026-06-07; today = 2026-06-08.
   All inline (no fetch) so it works from file://. */

const DATA = (function () {
  "use strict";

  // ---- Reference data -----------------------------------------------------
  const SYSTEMS = ["Pantry", "Ship Hero", "Fishbowl"];
  const FACILITIES = [
    { id: "IK-NYC-01", name: "Infinite Kitchen — NYC" },
    { id: "IK-LA-02", name: "Infinite Kitchen — LA" },
    { id: "CK-CHI-01", name: "Central Kitchen — Chicago" },
    { id: "DIS-ATL-01", name: "Distribution — Atlanta" },
    { id: "DIS-DAL-02", name: "Distribution — Dallas" },
    { id: "TW-001", name: "Transfer Warehouse (synthetic)" }
  ];

  const ERROR_TYPES = {
    NULL_PO_NUMBER:               { rule: "NOT_NULL",       team: "Data Engineering", table: "po_table",        sev: "High" },
    PO_RECORD_MISSING:            { rule: "REFERENTIAL",    team: "Data Engineering", table: "unified_ledger",  sev: "High" },
    TRANSFER_WAREHOUSE_IMBALANCE: { rule: "RECONCILIATION", team: "Inventory Ops",    table: "unified_ledger",  sev: "Critical" },
    THREE_WAY_MATCH_VARIANCE:     { rule: "RECONCILIATION", team: "Procurement",      table: "po_table",        sev: "High" },
    NEGATIVE_ON_HAND:             { rule: "RANGE",          team: "Inventory Ops",    table: "unified_ledger",  sev: "Critical" },
    MISSING_LOT_EXPIRATION:       { rule: "REFERENTIAL",    team: "Data Engineering", table: "unified_ledger",  sev: "Medium" },
    CONVERSION_FACTOR_OUTLIER:    { rule: "RANGE",          team: "Procurement",      table: "po_table",        sev: "Low" }
  };

  const SLA_TARGETS = { Critical: 1, High: 3, Medium: 5, Low: 10 };

  const TEAMS = {
    "Data Engineering": ["Pavel Romanov", "Sarah Chen", "Marcus Webb"],
    "Inventory Ops":    ["Diego Alvarez", "Priya Nair"],
    "Procurement":      ["Tom Becker", "Lena Ortiz"],
    "Accounting":       ["Mike Dietrich"]
  };

  // error type -> JIRA component
  const COMPONENT = {
    NULL_PO_NUMBER: "Ingestion",
    PO_RECORD_MISSING: "Ingestion",
    TRANSFER_WAREHOUSE_IMBALANCE: "Reconciliation",
    THREE_WAY_MATCH_VARIANCE: "Reconciliation",
    NEGATIVE_ON_HAND: "Inventory",
    MISSING_LOT_EXPIRATION: "Ingestion",
    CONVERSION_FACTOR_OUTLIER: "Procurement"
  };

  // ---- Validation rules (Admin screen) -----------------------------------
  const RULES = Object.keys(ERROR_TYPES).map((k, i) => ({
    id: "R-" + (i + 1),
    name: k,
    type: ERROR_TYPES[k].rule,
    table: ERROR_TYPES[k].table,
    severity: ERROR_TYPES[k].sev,
    enabled: k !== "CONVERSION_FACTOR_OUTLIER" ? true : true,
    description: ruleDesc(k)
  }));
  function ruleDesc(k) {
    return {
      NULL_PO_NUMBER: "po_table.po_number must not be null for any received line.",
      PO_RECORD_MISSING: "Every ledger receipt must reference an existing PO row.",
      TRANSFER_WAREHOUSE_IMBALANCE: "Shipped qty must reconcile to received qty in TW-001 (±0).",
      THREE_WAY_MATCH_VARIANCE: "PO ↔ receipt ↔ invoice quantity/price must match within tolerance.",
      NEGATIVE_ON_HAND: "on_hand_qty must be ≥ 0 after daily settlement.",
      MISSING_LOT_EXPIRATION: "Perishable lots must carry an expiration date.",
      CONVERSION_FACTOR_OUTLIER: "UoM conversion factor must fall within 3σ of historical."
    }[k];
  }

  // ---- Exceptions (22) ----------------------------------------------------
  // age = days since created (today 2026-06-08).
  function mk(id, type, fac, sys, assignee, jiraNum, status, ageDays, recur, snapshot) {
    const et = ERROR_TYPES[type];
    const created = daysAgoISO(ageDays);
    const resolved = (status === "Resolved" || status === "Closed" || status === "Auto-Closed")
      ? daysAgoISO(Math.max(0, ageDays - turnaroundFor(type, ageDays))) : null;
    const turnaround = resolved ? turnaroundFor(type, ageDays) : null;
    return {
      id, type, rule: et.rule, table: et.table,
      facility: fac, system: sys, severity: et.sev,
      team: et.team, assignee,
      jira: "WIQ-" + jiraNum, jiraStatus: status,
      created, resolved, turnaround,
      sla: SLA_TARGETS[et.sev],
      withinSla: resolved ? (turnaround <= SLA_TARGETS[et.sev]) : (ageDays <= SLA_TARGETS[et.sev]),
      ageDays, recurrence: recur,
      component: COMPONENT[type],
      snapshot,
      timeline: buildTimeline(status, created, resolved, assignee)
    };
  }
  function turnaroundFor(type, ageDays) {
    // Procurement worst, DE fast, Inventory mid — deterministic
    const base = { Procurement: 6, "Inventory Ops": 3, "Data Engineering": 1, Accounting: 4 };
    const t = base[ERROR_TYPES[type].team] || 3;
    return Math.min(ageDays, t + (type.length % 2));
  }

  function buildTimeline(status, created, resolved, assignee) {
    const tl = [{ label: "Open", at: created, note: "Auto-created by validation batch" }];
    const order = ["Open", "In Progress", "In Review", "Resolved", "Closed", "Auto-Closed"];
    const idx = order.indexOf(status);
    if (idx >= 1) tl.push({ label: "In Progress", at: created, note: "Assigned to " + assignee });
    if (idx >= 2) tl.push({ label: "In Review", at: resolved || created, note: "Fix submitted by data engineering" });
    if (status === "Resolved" || status === "Closed") tl.push({ label: status, at: resolved, note: "Underlying table corrected" });
    if (status === "Auto-Closed") tl.push({ label: "Auto-Closed", at: resolved, note: "Issue no longer reproduced on re-run" });
    return tl;
  }

  const EXCEPTIONS = [
    mk("EX-2041","NULL_PO_NUMBER","DIS-ATL-01","Ship Hero","Pavel Romanov",1041,"In Progress",1,6,
       {po_number:null, sku:"FZ-CHKN-2LB", qty:480, receipt_id:"RC-88241", facility:"DIS-ATL-01"}),
    mk("EX-2042","TRANSFER_WAREHOUSE_IMBALANCE","TW-001","Fishbowl","Diego Alvarez",1042,"Open",1,2,
       {shipped_qty:108, received_qty:100, variance:8, sku:"RAW-BEEF-10LB", transfer_id:"TR-5521"}),
    mk("EX-2043","NEGATIVE_ON_HAND","IK-NYC-01","Pantry","Priya Nair",1043,"In Progress",2,1,
       {on_hand_qty:-12, sku:"PROD-SALAD-KIT", facility:"IK-NYC-01", settlement_date:"2026-06-07"}),
    mk("EX-2044","THREE_WAY_MATCH_VARIANCE","DIS-DAL-02","Ship Hero","Tom Becker",1044,"Open",4,3,
       {po_qty:1000, receipt_qty:1000, invoice_qty:1080, price_var_pct:8.0, po_number:"PO-77310"}),
    mk("EX-2045","PO_RECORD_MISSING","CK-CHI-01","Fishbowl","Sarah Chen",1045,"In Review",2,4,
       {ledger_ref:"PO-66120", lookup:"po_table", result:"NOT FOUND", receipt_id:"RC-90011"}),
    mk("EX-2046","MISSING_LOT_EXPIRATION","IK-LA-02","Pantry","Marcus Webb",1046,"Open",3,2,
       {lot_id:"LOT-AA-3391", expiration_date:null, sku:"PERISH-DAIRY-1GAL", facility:"IK-LA-02"}),
    mk("EX-2047","CONVERSION_FACTOR_OUTLIER","DIS-ATL-01","Ship Hero","Lena Ortiz",1047,"Open",5,1,
       {sku:"BULK-FLOUR-50LB", conv_factor:22.7, expected_range:"0.9–1.1", po_number:"PO-77450"}),
    mk("EX-2048","NULL_PO_NUMBER","DIS-ATL-01","Ship Hero","Pavel Romanov",1048,"Auto-Closed",6,6,
       {po_number:null, sku:"FZ-VEG-MIX", qty:220, receipt_id:"RC-88102", facility:"DIS-ATL-01"}),
    mk("EX-2049","NEGATIVE_ON_HAND","CK-CHI-01","Fishbowl","Diego Alvarez",1049,"Resolved",4,1,
       {on_hand_qty:-3, sku:"RAW-ONION-25LB", facility:"CK-CHI-01", settlement_date:"2026-06-07"}),
    mk("EX-2050","THREE_WAY_MATCH_VARIANCE","DIS-ATL-01","Ship Hero","Lena Ortiz",1050,"In Progress",7,2,
       {po_qty:500, receipt_qty:460, invoice_qty:500, qty_var:40, po_number:"PO-77199"}),
    mk("EX-2051","PO_RECORD_MISSING","DIS-DAL-02","Ship Hero","Pavel Romanov",1051,"Auto-Closed",3,3,
       {ledger_ref:"PO-66290", lookup:"po_table", result:"NOT FOUND", receipt_id:"RC-90550"}),
    mk("EX-2052","MISSING_LOT_EXPIRATION","IK-NYC-01","Pantry","Sarah Chen",1052,"Closed",5,2,
       {lot_id:"LOT-BB-1120", expiration_date:null, sku:"PERISH-MEAT-5LB", facility:"IK-NYC-01"}),
    mk("EX-2053","TRANSFER_WAREHOUSE_IMBALANCE","TW-001","Fishbowl","Priya Nair",1053,"In Progress",3,2,
       {shipped_qty:54, received_qty:50, variance:4, sku:"RAW-RICE-50LB", transfer_id:"TR-5530"}),
    mk("EX-2054","NULL_PO_NUMBER","IK-LA-02","Pantry","Marcus Webb",1054,"Resolved",2,1,
       {po_number:null, sku:"BEV-COLD-BREW", qty:96, receipt_id:"RC-88990", facility:"IK-LA-02"}),
    mk("EX-2055","CONVERSION_FACTOR_OUTLIER","DIS-DAL-02","Ship Hero","Tom Becker",1055,"In Progress",8,1,
       {sku:"BULK-SUGAR-50LB", conv_factor:0.04, expected_range:"0.9–1.1", po_number:"PO-77600"}),
    mk("EX-2056","NEGATIVE_ON_HAND","IK-LA-02","Pantry","Diego Alvarez",1056,"Open",2,1,
       {on_hand_qty:-7, sku:"PROD-WRAP-KIT", facility:"IK-LA-02", settlement_date:"2026-06-07"}),
    mk("EX-2057","THREE_WAY_MATCH_VARIANCE","CK-CHI-01","Fishbowl","Tom Becker",1057,"Open",9,2,
       {po_qty:300, receipt_qty:300, invoice_qty:345, price_var_pct:15.0, po_number:"PO-77001"}),
    mk("EX-2058","PO_RECORD_MISSING","DIS-ATL-01","Ship Hero","Sarah Chen",1058,"In Progress",1,3,
       {ledger_ref:"PO-66401", lookup:"po_table", result:"NOT FOUND", receipt_id:"RC-90880"}),
    mk("EX-2059","MISSING_LOT_EXPIRATION","CK-CHI-01","Fishbowl","Pavel Romanov",1059,"Auto-Closed",4,2,
       {lot_id:"LOT-CC-7782", expiration_date:null, sku:"PERISH-FISH-3LB", facility:"CK-CHI-01"}),
    mk("EX-2060","NULL_PO_NUMBER","DIS-DAL-02","Ship Hero","Marcus Webb",1060,"Open",1,2,
       {po_number:null, sku:"FZ-FRIES-5LB", qty:600, receipt_id:"RC-89220", facility:"DIS-DAL-02"}),
    mk("EX-2061","TRANSFER_WAREHOUSE_IMBALANCE","TW-001","Fishbowl","Diego Alvarez",1061,"Open",2,2,
       {shipped_qty:200, received_qty:188, variance:12, sku:"RAW-CHKN-40LB", transfer_id:"TR-5544"}),
    mk("EX-2062","CONVERSION_FACTOR_OUTLIER","IK-NYC-01","Pantry","Lena Ortiz",1062,"In Review",6,1,
       {sku:"BEV-SYRUP-1GAL", conv_factor:14.2, expected_range:"0.9–1.1", po_number:"PO-77720"})
  ];

  // ---- Time series: last 21 days of error counts + avg turnaround --------
  const TREND = (function () {
    const arr = [];
    // run_date 2026-06-07 is the most recent point in the series
    const seed = [9,11,8,12,14,10,13,9,15,12,11,16,13,10,14,12,9,13,15,11,12];
    for (let i = 0; i < 21; i++) {
      const d = daysAgoISO(21 - i); // oldest..newest
      arr.push({
        date: d,
        errors: seed[i],
        autoClosed: Math.max(1, Math.round(seed[i] * 0.28)),
        avgTurnaround: +(3.2 + Math.sin(i / 3) * 0.9 + (i > 14 ? 0.6 : 0)).toFixed(1)
      });
    }
    return arr;
  })();

  // ---- Recurrence leaderboard --------------------------------------------
  const RECURRING = [
    { type: "NULL_PO_NUMBER", facility: "DIS-ATL-01", count30d: 6, trend: "up" },
    { type: "PO_RECORD_MISSING", facility: "DIS-DAL-02", count30d: 5, trend: "flat" },
    { type: "THREE_WAY_MATCH_VARIANCE", facility: "DIS-ATL-01", count30d: 4, trend: "up" },
    { type: "TRANSFER_WAREHOUSE_IMBALANCE", facility: "TW-001", count30d: 4, trend: "down" },
    { type: "MISSING_LOT_EXPIRATION", facility: "IK-LA-02", count30d: 3, trend: "flat" },
    { type: "NEGATIVE_ON_HAND", facility: "IK-NYC-01", count30d: 2, trend: "down" }
  ];

  // ---- Routing map --------------------------------------------------------
  const ROUTING = Object.keys(ERROR_TYPES).map(function (k) {
    const team = ERROR_TYPES[k].team;
    return {
      type: k, team: team,
      assignee: TEAMS[team][0],
      project: "WIQ",
      component: COMPONENT[k]
    };
  });

  // ---- Helpers ------------------------------------------------------------
  function daysAgoISO(n) {
    const base = new Date(Date.UTC(2026, 5, 8)); // 2026-06-08
    base.setUTCDate(base.getUTCDate() - n);
    return base.toISOString().slice(0, 10);
  }

  // ---- Derived KPIs (kept consistent w/ EXCEPTIONS) ----------------------
  function isOpen(e) { return ["Open","In Progress","In Review"].includes(e.jiraStatus); }
  const openExceptions = EXCEPTIONS.filter(isOpen).length;
  const newToday = EXCEPTIONS.filter(e => e.ageDays <= 1).length;
  const autoClosedToday = EXCEPTIONS.filter(e => e.jiraStatus === "Auto-Closed" && e.resolved === daysAgoISO(0)).length
    || EXCEPTIONS.filter(e => e.jiraStatus === "Auto-Closed").length; // ensure non-zero for demo
  const resolvedSet = EXCEPTIONS.filter(e => e.turnaround != null);
  const avgTurnaround = +(resolvedSet.reduce((s,e)=>s+e.turnaround,0) / resolvedSet.length).toFixed(1);
  const withinSlaPct = Math.round(100 * EXCEPTIONS.filter(e => e.withinSla).length / EXCEPTIONS.length);
  // Data-quality score: 100 minus weighted penalty
  const sevWeight = { Critical: 6, High: 3, Medium: 1.5, Low: 0.5 };
  const penalty = EXCEPTIONS.filter(isOpen).reduce((s,e)=>s+sevWeight[e.severity],0);
  const dqScore = Math.max(0, Math.round(100 - penalty));

  function countBy(keyFn) {
    const m = {};
    EXCEPTIONS.forEach(e => { const k = keyFn(e); m[k] = (m[k]||0)+1; });
    return m;
  }
  const byType = countBy(e => e.type);
  const byFacility = countBy(e => e.facility);
  const bySystem = countBy(e => e.system);

  // Turnaround per team / person (only resolved set), plus open age fallback
  function turnaroundByTeam() {
    const m = {};
    Object.keys(TEAMS).forEach(t => m[t] = []);
    EXCEPTIONS.forEach(e => {
      const v = e.turnaround != null ? e.turnaround : e.ageDays;
      if (!m[e.team]) m[e.team] = [];
      m[e.team].push(v);
    });
    return Object.keys(m).map(t => ({
      team: t,
      avg: m[t].length ? +(m[t].reduce((a,b)=>a+b,0)/m[t].length).toFixed(1) : 0,
      sla: avgSlaForTeam(t),
      count: m[t].length
    })).filter(x => x.count > 0).sort((a,b)=>b.avg-a.avg);
  }
  function avgSlaForTeam(t) {
    const list = EXCEPTIONS.filter(e => e.team === t);
    if (!list.length) return 100;
    return Math.round(100 * list.filter(e => e.withinSla).length / list.length);
  }
  function turnaroundByPerson() {
    const m = {};
    EXCEPTIONS.forEach(e => {
      const v = e.turnaround != null ? e.turnaround : e.ageDays;
      if (!m[e.assignee]) m[e.assignee] = { team: e.team, vals: [] };
      m[e.assignee].vals.push(v);
    });
    return Object.keys(m).map(p => ({
      person: p, team: m[p].team,
      avg: +(m[p].vals.reduce((a,b)=>a+b,0)/m[p].vals.length).toFixed(1),
      count: m[p].vals.length
    })).sort((a,b)=>b.avg-a.avg);
  }
  // Aging buckets (open items by age; resolved by turnaround)
  function agingBuckets() {
    const buckets = { "0-1d":0, "1-3d":0, "3-7d":0, "7d+":0 };
    EXCEPTIONS.forEach(e => {
      const a = e.turnaround != null ? e.turnaround : e.ageDays;
      if (a <= 1) buckets["0-1d"]++;
      else if (a <= 3) buckets["1-3d"]++;
      else if (a <= 7) buckets["3-7d"]++;
      else buckets["7d+"]++;
    });
    return buckets;
  }

  const slaWithin = EXCEPTIONS.filter(e => e.withinSla).length;
  const slaBreach = EXCEPTIONS.length - slaWithin;

  return {
    meta: { today: "2026-06-08", runDate: "2026-06-07", project: "WIQ" },
    SYSTEMS, FACILITIES, ERROR_TYPES, SLA_TARGETS, TEAMS, RULES, ROUTING, RECURRING,
    EXCEPTIONS, TREND,
    kpis: { openExceptions, newToday, autoClosedToday, avgTurnaround, withinSlaPct, dqScore,
            total: EXCEPTIONS.length, slaWithin, slaBreach },
    byType, byFacility, bySystem,
    turnaroundByTeam: turnaroundByTeam(),
    turnaroundByPerson: turnaroundByPerson(),
    agingBuckets: agingBuckets(),
    helpers: { isOpen }
  };
})();
