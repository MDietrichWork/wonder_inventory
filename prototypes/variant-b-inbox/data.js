/* ============================================================
   Wonder Inventory Data-Quality Console
   Variant B — Inbox + Detail Panel (light, professional)
   Global sample DATA (inlined; no fetch, works on file://)
   Today = 2026-06-08, validation run_date = 2026-06-07
   ============================================================ */
const DATA = (function () {

  // ---- Reference / config -------------------------------------------------
  const teams = {
    "Data Engineering": ["Pavel Romanov", "Sarah Chen", "Marcus Webb"],
    "Inventory Ops": ["Diego Alvarez", "Priya Nair"],
    "Procurement": ["Tom Becker", "Lena Ortiz"],
    "Accounting": ["Mike Dietrich"]
  };

  const facilities = {
    "IK-NYC-01": "Infinite Kitchen — New York",
    "IK-LA-02": "Infinite Kitchen — Los Angeles",
    "CK-CHI-01": "Central Kitchen — Chicago",
    "DIS-ATL-01": "Distribution — Atlanta",
    "DIS-DAL-02": "Distribution — Dallas",
    "TW-001": "Transfer Warehouse (synthetic)"
  };

  const systems = {
    "Pantry": "Pantry — selling locations",
    "Ship Hero": "Ship Hero — distribution",
    "Fishbowl": "Fishbowl — production"
  };

  // SLA targets (resolution) in days, per severity
  const sla = { Critical: 1, High: 3, Medium: 5, Low: 10 };

  // Validation rules + routing
  const rules = [
    {
      id: "NULL_PO_NUMBER", name: "Missing PO Number", type: "NOT_NULL",
      table: "po_table", severity: "High", enabled: true,
      team: "Data Engineering", assignee: "Pavel Romanov",
      jiraProject: "WIQ", component: "Ingestion",
      plain: "A receipt was booked without a purchase-order reference, so it can't be matched to spend.",
      why: "Accounting can't tie the receipt to a PO at month-end, so the cost could land in the wrong account."
    },
    {
      id: "PO_RECORD_MISSING", name: "PO Record Missing", type: "REFERENTIAL",
      table: "po_table", severity: "High", enabled: true,
      team: "Data Engineering", assignee: "Sarah Chen",
      jiraProject: "WIQ", component: "Ingestion",
      plain: "The ledger points to a PO that doesn't exist in the PO table.",
      why: "A dangling reference means the receipt looks valid but has nothing to reconcile against."
    },
    {
      id: "TRANSFER_WAREHOUSE_IMBALANCE", name: "Transfer Warehouse Imbalance", type: "RECONCILIATION",
      table: "unified_ledger", severity: "Medium", enabled: true,
      team: "Inventory Ops", assignee: "Diego Alvarez",
      jiraProject: "WIQ", component: "Reconciliation",
      plain: "Stock that left one facility hasn't fully arrived at the other — the transfer warehouse is out of balance.",
      why: "Aged in-transit stock inflates inventory value and hides shrink or mis-shipments."
    },
    {
      id: "THREE_WAY_MATCH_VARIANCE", name: "Three-Way Match Variance", type: "RECONCILIATION",
      table: "po_table", severity: "Critical", enabled: true,
      team: "Procurement", assignee: "Tom Becker",
      jiraProject: "WIQ", component: "Match",
      plain: "The invoice, the PO, and the received quantity don't all agree.",
      why: "We could over- or under-pay a supplier, and the GL booking would be wrong."
    },
    {
      id: "NEGATIVE_ON_HAND", name: "Negative On-Hand", type: "RANGE",
      table: "unified_ledger", severity: "High", enabled: true,
      team: "Inventory Ops", assignee: "Priya Nair",
      jiraProject: "WIQ", component: "Reconciliation",
      plain: "Cumulative on-hand for a SKU has gone below zero, which isn't physically possible.",
      why: "Negative inventory usually means a missing receipt or a double-counted shipment."
    },
    {
      id: "MISSING_LOT_EXPIRATION", name: "Missing Lot Expiration", type: "REFERENTIAL",
      table: "unified_ledger", severity: "Medium", enabled: true,
      team: "Data Engineering", assignee: "Marcus Webb",
      jiraProject: "WIQ", component: "Ingestion",
      plain: "A lot's expiration ID doesn't resolve to a real expiration record.",
      why: "Without a valid expiration date we can't track shelf life or food-safety holds."
    },
    {
      id: "CONVERSION_FACTOR_OUTLIER", name: "Conversion Factor Outlier", type: "RANGE",
      table: "po_table", severity: "Low", enabled: true,
      team: "Procurement", assignee: "Lena Ortiz",
      jiraProject: "WIQ", component: "Match",
      plain: "The supplier unit-of-measure to Wonder-SKU conversion factor looks far outside its normal range.",
      why: "A bad conversion factor silently multiplies or shrinks quantities and unit cost."
    }
  ];

  const rulesById = {};
  rules.forEach(r => { rulesById[r.id] = r; });

  // ---- Tickets (12) -------------------------------------------------------
  function tl(steps) { return steps; }

  const tickets = [
    {
      key: "WIQ-1041", type: "NULL_PO_NUMBER", facility: "DIS-ATL-01",
      team: "Data Engineering", assignee: "Pavel Romanov", severity: "High",
      status: "In Progress", created: "2026-06-07", resolved: null, turnaround: null,
      timeline: tl([
        { s: "Open", d: "2026-06-07 06:12", note: "Auto-created by daily validation run" },
        { s: "In Progress", d: "2026-06-07 09:40", note: "Pavel investigating ingestion mapping" }
      ])
    },
    {
      key: "WIQ-1042", type: "PO_RECORD_MISSING", facility: "DIS-DAL-02",
      team: "Data Engineering", assignee: "Sarah Chen", severity: "High",
      status: "Open", created: "2026-06-07", resolved: null, turnaround: null,
      timeline: tl([
        { s: "Open", d: "2026-06-07 06:12", note: "Auto-created by daily validation run" }
      ])
    },
    {
      key: "WIQ-1043", type: "THREE_WAY_MATCH_VARIANCE", facility: "DIS-DAL-02",
      team: "Procurement", assignee: "Tom Becker", severity: "Critical",
      status: "Open", created: "2026-06-06", resolved: null, turnaround: null,
      timeline: tl([
        { s: "Open", d: "2026-06-06 06:11", note: "Auto-created by daily validation run" }
      ])
    },
    {
      key: "WIQ-1044", type: "THREE_WAY_MATCH_VARIANCE", facility: "CK-CHI-01",
      team: "Procurement", assignee: "Lena Ortiz", severity: "Critical",
      status: "In Progress", created: "2026-06-05", resolved: null, turnaround: null,
      timeline: tl([
        { s: "Open", d: "2026-06-05 06:10", note: "Auto-created by daily validation run" },
        { s: "In Progress", d: "2026-06-07 14:02", note: "Awaiting supplier invoice copy" }
      ])
    },
    {
      key: "WIQ-1045", type: "TRANSFER_WAREHOUSE_IMBALANCE", facility: "TW-001",
      team: "Inventory Ops", assignee: "Diego Alvarez", severity: "Medium",
      status: "In Review", created: "2026-06-04", resolved: null, turnaround: null,
      timeline: tl([
        { s: "Open", d: "2026-06-04 06:09", note: "Auto-created by daily validation run" },
        { s: "In Progress", d: "2026-06-04 11:20", note: "Diego matching in-transit shipments" },
        { s: "In Review", d: "2026-06-06 16:45", note: "Pending Inventory Ops lead sign-off" }
      ])
    },
    {
      key: "WIQ-1046", type: "NEGATIVE_ON_HAND", facility: "IK-NYC-01",
      team: "Inventory Ops", assignee: "Priya Nair", severity: "High",
      status: "Resolved", created: "2026-06-05", resolved: "2026-06-07", turnaround: 2,
      timeline: tl([
        { s: "Open", d: "2026-06-05 06:10", note: "Auto-created by daily validation run" },
        { s: "In Progress", d: "2026-06-05 13:15", note: "Found missing receipt for SKU 88421" },
        { s: "Resolved", d: "2026-06-07 10:05", note: "Receipt back-posted; on-hand corrected" }
      ])
    },
    {
      key: "WIQ-1031", type: "MISSING_LOT_EXPIRATION", facility: "IK-LA-02",
      team: "Data Engineering", assignee: "Marcus Webb", severity: "Medium",
      status: "Auto-Closed", created: "2026-06-02", resolved: "2026-06-04", turnaround: 2,
      autoClosed: true,
      timeline: tl([
        { s: "Open", d: "2026-06-02 06:08", note: "Auto-created by daily validation run" },
        { s: "In Progress", d: "2026-06-03 09:00", note: "DE patched lot-expiration join" },
        { s: "Auto-Closed", d: "2026-06-04 06:09", note: "Issue no longer reproduced in 2026-06-03 run — auto-closed" }
      ])
    },
    {
      key: "WIQ-1027", type: "NULL_PO_NUMBER", facility: "DIS-ATL-01",
      team: "Data Engineering", assignee: "Pavel Romanov", severity: "High",
      status: "Auto-Closed", created: "2026-05-30", resolved: "2026-06-01", turnaround: 2,
      autoClosed: true,
      timeline: tl([
        { s: "Open", d: "2026-05-30 06:07", note: "Auto-created by daily validation run" },
        { s: "In Progress", d: "2026-05-31 10:30", note: "Mapping fix deployed to ingestion" },
        { s: "Auto-Closed", d: "2026-06-01 06:08", note: "No longer reproduced — auto-closed" }
      ])
    },
    {
      key: "WIQ-1019", type: "CONVERSION_FACTOR_OUTLIER", facility: "DIS-DAL-02",
      team: "Procurement", assignee: "Lena Ortiz", severity: "Low",
      status: "Open", created: "2026-05-26", resolved: null, turnaround: null,
      timeline: tl([
        { s: "Open", d: "2026-05-26 06:05", note: "Auto-created by daily validation run" }
      ])
    },
    {
      key: "WIQ-1014", type: "THREE_WAY_MATCH_VARIANCE", facility: "DIS-ATL-01",
      team: "Procurement", assignee: "Tom Becker", severity: "Critical",
      status: "Closed", created: "2026-05-22", resolved: "2026-05-28", turnaround: 6,
      timeline: tl([
        { s: "Open", d: "2026-05-22 06:03", note: "Auto-created by daily validation run" },
        { s: "In Progress", d: "2026-05-24 15:00", note: "Supplier credit memo requested" },
        { s: "In Review", d: "2026-05-27 12:00", note: "Credit applied; awaiting close" },
        { s: "Closed", d: "2026-05-28 09:30", note: "Manually closed by Procurement" }
      ])
    },
    {
      key: "WIQ-1008", type: "TRANSFER_WAREHOUSE_IMBALANCE", facility: "TW-001",
      team: "Inventory Ops", assignee: "Priya Nair", severity: "Medium",
      status: "Closed", created: "2026-05-20", resolved: "2026-05-23", turnaround: 3,
      timeline: tl([
        { s: "Open", d: "2026-05-20 06:02", note: "Auto-created by daily validation run" },
        { s: "In Progress", d: "2026-05-21 08:45", note: "Reconciled 8 in-transit units" },
        { s: "Closed", d: "2026-05-23 11:10", note: "Balance restored" }
      ])
    },
    {
      key: "WIQ-1002", type: "NEGATIVE_ON_HAND", facility: "CK-CHI-01",
      team: "Inventory Ops", assignee: "Diego Alvarez", severity: "High",
      status: "Auto-Closed", created: "2026-05-18", resolved: "2026-05-19", turnaround: 1,
      autoClosed: true,
      timeline: tl([
        { s: "Open", d: "2026-05-18 06:01", note: "Auto-created by daily validation run" },
        { s: "In Progress", d: "2026-05-18 14:20", note: "Double-counted shipment removed at source" },
        { s: "Auto-Closed", d: "2026-05-19 06:02", note: "No longer reproduced — auto-closed" }
      ])
    }
  ];

  const ticketsByKey = {};
  tickets.forEach(t => { ticketsByKey[t.key] = t; });

  // ---- Exceptions (from the 2026-06-07 run) -------------------------------
  function ex(o) {
    const r = rulesById[o.type];
    return Object.assign({
      severity: r.severity, team: r.team, assignee: r.assignee,
      ruleName: r.name, ruleType: r.type, table: r.table,
      jiraProject: r.jiraProject, component: r.component
    }, o);
  }

  const exceptions = [
    ex({ id: "EX-0001", type: "NULL_PO_NUMBER", facility: "DIS-ATL-01", system: "Ship Hero",
        ticket: "WIQ-1041", status: "In Progress", newToday: true,
        headline: "Receipt at DIS-ATL-01 is missing its PO number",
        fields: { "Receipt ID": "RCPT-558210", "SKU": "88421 — Frozen Dough 5kg", "Qty received": "120 cs", "PO number": "(blank)", "Received": "2026-06-07" } }),
    ex({ id: "EX-0002", type: "NULL_PO_NUMBER", facility: "DIS-ATL-01", system: "Ship Hero",
        ticket: "WIQ-1041", status: "In Progress", newToday: true,
        headline: "Another DIS-ATL-01 receipt has no PO number",
        fields: { "Receipt ID": "RCPT-558244", "SKU": "88533 — Marinara 1gal", "Qty received": "48 cs", "PO number": "(blank)", "Received": "2026-06-07" } }),
    ex({ id: "EX-0003", type: "NULL_PO_NUMBER", facility: "DIS-ATL-01", system: "Ship Hero",
        ticket: "WIQ-1041", status: "In Progress", newToday: true,
        headline: "DIS-ATL-01 receipt missing PO number (recurring)",
        fields: { "Receipt ID": "RCPT-558261", "SKU": "88533 — Marinara 1gal", "Qty received": "24 cs", "PO number": "(blank)", "Received": "2026-06-07" } }),
    ex({ id: "EX-0004", type: "PO_RECORD_MISSING", facility: "DIS-DAL-02", system: "Ship Hero",
        ticket: "WIQ-1042", status: "Open", newToday: true,
        headline: "A DIS-DAL-02 receipt points to a PO that doesn't exist",
        fields: { "Receipt ID": "RCPT-560011", "PO referenced": "PO-77310", "SKU": "90112 — Olive Oil 4L", "Qty": "30 cs", "PO lookup": "no matching row" } }),
    ex({ id: "EX-0005", type: "PO_RECORD_MISSING", facility: "IK-NYC-01", system: "Pantry",
        ticket: "WIQ-1042", status: "Open", newToday: true,
        headline: "IK-NYC-01 ledger row references a missing PO",
        fields: { "Ledger row": "UL-991204", "PO referenced": "PO-77418", "SKU": "44120 — To-Go Cups", "Qty": "1,000 ea", "PO lookup": "no matching row" } }),
    ex({ id: "EX-0006", type: "THREE_WAY_MATCH_VARIANCE", facility: "DIS-DAL-02", system: "Ship Hero",
        ticket: "WIQ-1043", status: "Open", newToday: true,
        headline: "Invoice, PO, and receipt don't agree at DIS-DAL-02",
        fields: { "PO number": "PO-77290", "PO qty": "200 cs", "Received qty": "188 cs", "Invoiced qty": "200 cs", "Variance": "12 cs / $480" } }),
    ex({ id: "EX-0007", type: "THREE_WAY_MATCH_VARIANCE", facility: "CK-CHI-01", system: "Fishbowl",
        ticket: "WIQ-1044", status: "In Progress", newToday: true,
        headline: "Three-way match variance at CK-CHI-01",
        fields: { "PO number": "PO-77155", "PO unit price": "$18.50", "Invoiced price": "$21.00", "Qty": "60 cs", "Variance": "$150.00" } }),
    ex({ id: "EX-0008", type: "THREE_WAY_MATCH_VARIANCE", facility: "DIS-DAL-02", system: "Ship Hero",
        ticket: "WIQ-1043", status: "Open", newToday: true,
        headline: "Price mismatch between PO and invoice (DIS-DAL-02)",
        fields: { "PO number": "PO-77301", "PO unit price": "$9.20", "Invoiced price": "$9.95", "Qty": "150 cs", "Variance": "$112.50" } }),
    ex({ id: "EX-0009", type: "TRANSFER_WAREHOUSE_IMBALANCE", facility: "TW-001", system: "Ship Hero",
        ticket: "WIQ-1045", status: "In Review", newToday: true,
        headline: "Transfer warehouse TW-001 is out of balance",
        fields: { "Transfer ID": "TR-30188", "From": "DIS-ATL-01", "To": "IK-NYC-01", "Shipped": "108 cs", "Received": "100 cs", "In transit / aged": "8 cs (6 days)" } }),
    ex({ id: "EX-0010", type: "TRANSFER_WAREHOUSE_IMBALANCE", facility: "TW-001", system: "Ship Hero",
        ticket: "WIQ-1045", status: "In Review", newToday: true,
        headline: "Aged in-transit stock in TW-001",
        fields: { "Transfer ID": "TR-30205", "From": "DIS-DAL-02", "To": "IK-LA-02", "Shipped": "60 cs", "Received": "54 cs", "In transit / aged": "6 cs (9 days)" } }),
    ex({ id: "EX-0011", type: "NEGATIVE_ON_HAND", facility: "IK-LA-02", system: "Pantry",
        ticket: null, status: "Open", newToday: true,
        headline: "On-hand for a SKU at IK-LA-02 went negative",
        fields: { "SKU": "77011 — Espresso Beans 1kg", "On-hand": "-14 ea", "Last movement": "Sale of 30 ea", "Likely cause": "missing receipt" } }),
    ex({ id: "EX-0012", type: "NEGATIVE_ON_HAND", facility: "IK-NYC-01", system: "Pantry",
        ticket: "WIQ-1046", status: "Resolved", newToday: false,
        headline: "Negative on-hand corrected at IK-NYC-01",
        fields: { "SKU": "88421 — Frozen Dough 5kg", "On-hand": "0 ea (was -22)", "Fix": "receipt back-posted", "Status": "corrected 06-07" } }),
    ex({ id: "EX-0013", type: "NEGATIVE_ON_HAND", facility: "CK-CHI-01", system: "Fishbowl",
        ticket: null, status: "Open", newToday: true,
        headline: "Negative on-hand for a production input at CK-CHI-01",
        fields: { "SKU": "65003 — Yeast Block", "On-hand": "-5 ea", "Last movement": "Production draw 40 ea", "Likely cause": "double-counted draw" } }),
    ex({ id: "EX-0014", type: "MISSING_LOT_EXPIRATION", facility: "IK-LA-02", system: "Pantry",
        ticket: null, status: "Open", newToday: true,
        headline: "A lot at IK-LA-02 has no valid expiration date",
        fields: { "Lot ID": "LOT-22189", "SKU": "55120 — Cream Cheese 2kg", "Expiration ID": "EXP-0 (unresolved)", "Qty": "40 ea" } }),
    ex({ id: "EX-0015", type: "MISSING_LOT_EXPIRATION", facility: "CK-CHI-01", system: "Fishbowl",
        ticket: null, status: "Open", newToday: true,
        headline: "Lot expiration doesn't resolve at CK-CHI-01",
        fields: { "Lot ID": "LOT-22240", "SKU": "61002 — Butter 25lb", "Expiration ID": "(blank)", "Qty": "18 ea" } }),
    ex({ id: "EX-0016", type: "MISSING_LOT_EXPIRATION", facility: "IK-NYC-01", system: "Pantry",
        ticket: null, status: "Open", newToday: true,
        headline: "Unresolved lot expiration at IK-NYC-01",
        fields: { "Lot ID": "LOT-22301", "SKU": "55121 — Cream Cheese 5kg", "Expiration ID": "EXP-9991 (missing)", "Qty": "12 ea" } }),
    ex({ id: "EX-0017", type: "CONVERSION_FACTOR_OUTLIER", facility: "DIS-DAL-02", system: "Ship Hero",
        ticket: "WIQ-1019", status: "Open", newToday: true,
        headline: "Conversion factor looks off for a DIS-DAL-02 item",
        fields: { "SKU": "90112 — Olive Oil 4L", "Supplier UoM": "1 pallet", "Expected factor": "48 ea/pallet", "Recorded factor": "480 ea/pallet", "Flag": "10x outlier" } }),
    ex({ id: "EX-0018", type: "CONVERSION_FACTOR_OUTLIER", facility: "DIS-ATL-01", system: "Ship Hero",
        ticket: null, status: "Open", newToday: true,
        headline: "Possible bad conversion factor at DIS-ATL-01",
        fields: { "SKU": "88701 — Napkins bulk", "Supplier UoM": "1 case", "Expected factor": "12 pk/case", "Recorded factor": "1 pk/case", "Flag": "low outlier" } }),
    ex({ id: "EX-0019", type: "NULL_PO_NUMBER", facility: "DIS-DAL-02", system: "Ship Hero",
        ticket: null, status: "Open", newToday: true,
        headline: "DIS-DAL-02 receipt missing PO number",
        fields: { "Receipt ID": "RCPT-560044", "SKU": "90118 — Balsamic 2L", "Qty received": "24 cs", "PO number": "(blank)", "Received": "2026-06-07" } }),
    ex({ id: "EX-0020", type: "TRANSFER_WAREHOUSE_IMBALANCE", facility: "TW-001", system: "Ship Hero",
        ticket: null, status: "Open", newToday: true,
        headline: "Small transfer imbalance flagged in TW-001",
        fields: { "Transfer ID": "TR-30210", "From": "CK-CHI-01", "To": "DIS-ATL-01", "Shipped": "200 cs", "Received": "197 cs", "In transit / aged": "3 cs (2 days)" } }),
    ex({ id: "EX-0021", type: "THREE_WAY_MATCH_VARIANCE", facility: "DIS-ATL-01", system: "Ship Hero",
        ticket: null, status: "Open", newToday: true,
        headline: "Quantity variance between PO and receipt (DIS-ATL-01)",
        fields: { "PO number": "PO-77260", "PO qty": "100 cs", "Received qty": "112 cs", "Invoiced qty": "100 cs", "Variance": "+12 cs over-received" } }),
    ex({ id: "EX-0022", type: "PO_RECORD_MISSING", facility: "DIS-ATL-01", system: "Ship Hero",
        ticket: null, status: "Open", newToday: true,
        headline: "DIS-ATL-01 receipt references a PO not yet loaded",
        fields: { "Receipt ID": "RCPT-558290", "PO referenced": "PO-77520", "SKU": "88421 — Frozen Dough 5kg", "Qty": "60 cs", "PO lookup": "no matching row" } }),

    // ---- Recently auto-closed (flagged on prior runs, no longer reproduce) ----
    // These link to auto-closed tickets so the "Auto-closed" folder showcases the
    // flagship auto-close behaviour. They are NOT part of the current run
    // (newToday:false) and are excluded from the dashboard run breakdowns below.
    ex({ id: "EX-0023", type: "NULL_PO_NUMBER", facility: "DIS-ATL-01", system: "Ship Hero",
        team: "Data Engineering", assignee: "Pavel Romanov", severity: "High",
        ticket: "WIQ-1027", status: "Auto-Closed", newToday: false,
        headline: "DIS-ATL-01 missing PO number — auto-resolved",
        fields: { "Receipt ID": "RCPT-557120", "SKU": "88421 — Frozen Dough 5kg", "Qty received": "96 cs", "PO number": "PO-77011 (back-filled by DE)", "Received": "2026-05-30" } }),
    ex({ id: "EX-0024", type: "MISSING_LOT_EXPIRATION", facility: "IK-LA-02", system: "Pantry",
        team: "Data Engineering", assignee: "Marcus Webb", severity: "Medium",
        ticket: "WIQ-1031", status: "Auto-Closed", newToday: false,
        headline: "Lot expiration at IK-LA-02 — auto-resolved",
        fields: { "Lot ID": "LOT-22050", "SKU": "55120 — Cream Cheese 2kg", "Expiration ID": "EXP-8830 (now resolves)", "Qty": "36 ea" } }),
    ex({ id: "EX-0025", type: "NEGATIVE_ON_HAND", facility: "CK-CHI-01", system: "Fishbowl",
        team: "Inventory Ops", assignee: "Diego Alvarez", severity: "High",
        ticket: "WIQ-1002", status: "Auto-Closed", newToday: false,
        headline: "Negative on-hand at CK-CHI-01 — auto-resolved",
        fields: { "SKU": "65003 — Yeast Block", "On-hand": "0 ea (was -9)", "Last movement": "Production draw 40 ea", "Resolution": "double-counted draw removed at source" } })
  ];

  // ---- Recurrence (30-day window) -----------------------------------------
  const recurrence = [
    { type: "NULL_PO_NUMBER", facility: "DIS-ATL-01", count: 6, window: "30 days", note: "Same ingestion mapping gap keeps recurring." },
    { type: "THREE_WAY_MATCH_VARIANCE", facility: "DIS-DAL-02", count: 4, window: "30 days", note: "One supplier repeatedly invoices off PO price." },
    { type: "TRANSFER_WAREHOUSE_IMBALANCE", facility: "TW-001", count: 4, window: "30 days", note: "In-transit aging between ATL and the kitchens." },
    { type: "MISSING_LOT_EXPIRATION", facility: "IK-LA-02", count: 3, window: "30 days", note: "Expiration join intermittently fails." }
  ];
  const recurrenceKey = {};
  recurrence.forEach(r => { recurrenceKey[r.type + "|" + r.facility] = r; });

  // ---- Dashboard KPIs -----------------------------------------------------
  const kpis = {
    openExceptions: 22,
    newToday: 22,
    autoClosedToday: 3,
    avgTurnaroundDays: 2.7,
    pctWithinSla: 78
  };

  // 14-day error trend (most recent last = run 2026-06-07)
  const trend = [
    { date: "05-25", count: 19 }, { date: "05-26", count: 24 }, { date: "05-27", count: 17 },
    { date: "05-28", count: 21 }, { date: "05-29", count: 26 }, { date: "05-30", count: 23 },
    { date: "05-31", count: 18 }, { date: "06-01", count: 20 }, { date: "06-02", count: 25 },
    { date: "06-03", count: 22 }, { date: "06-04", count: 27 }, { date: "06-05", count: 24 },
    { date: "06-06", count: 20 }, { date: "06-07", count: 22 }
  ];

  // ---- SLA / turnaround by team & person ----------------------------------
  const slaByTeam = [
    { team: "Data Engineering", avgDays: 1.8, within: 5, breaching: 0, open: 2 },
    { team: "Inventory Ops", avgDays: 2.3, within: 3, breaching: 1, open: 3 },
    { team: "Procurement", avgDays: 5.4, within: 1, breaching: 3, open: 3 },
    { team: "Accounting", avgDays: 1.0, within: 1, breaching: 0, open: 0 }
  ];

  const slaByPerson = [
    { person: "Pavel Romanov", team: "Data Engineering", avgDays: 1.5, within: 3, breaching: 0 },
    { person: "Sarah Chen", team: "Data Engineering", avgDays: 2.0, within: 2, breaching: 0 },
    { person: "Marcus Webb", team: "Data Engineering", avgDays: 2.1, within: 2, breaching: 0 },
    { person: "Diego Alvarez", team: "Inventory Ops", avgDays: 2.0, within: 2, breaching: 0 },
    { person: "Priya Nair", team: "Inventory Ops", avgDays: 2.6, within: 1, breaching: 1 },
    { person: "Tom Becker", team: "Procurement", avgDays: 6.0, within: 0, breaching: 2 },
    { person: "Lena Ortiz", team: "Procurement", avgDays: 4.5, within: 1, breaching: 1 }
  ];

  const aging = [
    { bucket: "0–1 day", count: 3, tone: "ok" },
    { bucket: "1–3 days", count: 3, tone: "ok" },
    { bucket: "3–7 days", count: 1, tone: "warn" },
    { bucket: "7+ days", count: 1, tone: "bad" }
  ];

  const overdue = ["WIQ-1043", "WIQ-1044", "WIQ-1019"];

  // ---- Derived: errors by type & facility ---------------------------------
  function countBy(arr, key) {
    const m = {};
    arr.forEach(e => { m[e[key]] = (m[e[key]] || 0) + 1; });
    return Object.keys(m).map(k => ({ key: k, count: m[k] })).sort((a, b) => b.count - a.count);
  }
  // Dashboard breakdowns reflect the current run only (exclude historical auto-closed).
  const runExceptions = exceptions.filter(e => e.status !== "Auto-Closed");
  const errorsByType = countBy(runExceptions, "type");
  const errorsByFacility = countBy(runExceptions, "facility");

  return {
    runDate: "2026-06-07", today: "2026-06-08",
    teams, facilities, systems, sla, rules, rulesById,
    tickets, ticketsByKey, exceptions, recurrence, recurrenceKey,
    kpis, trend, slaByTeam, slaByPerson, aging, overdue,
    errorsByType, errorsByFacility
  };
})();

// app.js reads window.DATA; a top-level `const` is not attached to window.
window.DATA = DATA;
