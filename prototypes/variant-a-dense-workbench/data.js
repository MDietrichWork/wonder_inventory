/* Wonder Inventory Data-Quality Console — Variant A
 * Sample data. Run being viewed: run_date 2026-06-07. "Today" = 2026-06-08.
 * All data is synthetic. Global DATA object consumed by app.js.
 */
(function () {
  "use strict";

  const TODAY = "2026-06-08";
  const RUN_DATE = "2026-06-07";

  // ---- Reference dimensions ----
  const facilities = [
    { id: "IK-NYC-01", type: "Infinite Kitchen", note: "formerly High-Density Restaurant" },
    { id: "IK-LA-02", type: "Infinite Kitchen", note: "formerly High-Density Restaurant" },
    { id: "CK-CHI-01", type: "Central Kitchen", note: "" },
    { id: "DIS-ATL-01", type: "Distribution", note: "" },
    { id: "DIS-DAL-02", type: "Distribution", note: "" },
    { id: "TW-001", type: "Transfer Warehouse", note: "synthetic" }
  ];

  const systems = ["Pantry", "Ship Hero", "Fishbowl"];

  const sourceTables = ["unified_ledger", "po_table"];

  const errorTypes = [
    { type: "NULL_PO_NUMBER", rule: "PO number present", ruleType: "NOT_NULL", team: "Data Engineering",
      desc: "Add / PO-receipt transaction is missing a PO reference." },
    { type: "PO_RECORD_MISSING", rule: "PO exists in PO table", ruleType: "REFERENTIAL", team: "Data Engineering",
      desc: "Ledger PO reference has no matching row in po_table." },
    { type: "TRANSFER_WAREHOUSE_IMBALANCE", rule: "Transfer Warehouse balances", ruleType: "RECONCILIATION", team: "Inventory Ops",
      desc: "Aged / unbalanced stock stuck in synthetic Transfer Warehouse TW-001." },
    { type: "THREE_WAY_MATCH_VARIANCE", rule: "3-way match", ruleType: "RECONCILIATION", team: "Procurement",
      desc: "Invoice vs PO vs ledger quantity/price mismatch beyond tolerance." },
    { type: "NEGATIVE_ON_HAND", rule: "On-hand >= 0", ruleType: "RANGE", team: "Inventory Ops",
      desc: "Cumulative on-hand quantity went negative for an SKU / location." },
    { type: "MISSING_LOT_EXPIRATION", rule: "Lot expiration resolvable", ruleType: "REFERENTIAL", team: "Data Engineering",
      desc: "Lot Expiration ID does not resolve in the subsidiary table." },
    { type: "CONVERSION_FACTOR_OUTLIER", rule: "Conversion factor sane", ruleType: "RANGE", team: "Procurement",
      desc: "Supplier-UoM to Wonder-SKU conversion factor is wildly out of range." }
  ];

  const teams = {
    "Data Engineering": ["Pavel Romanov", "Sarah Chen", "Marcus Webb"],
    "Inventory Ops": ["Diego Alvarez", "Priya Nair"],
    "Procurement": ["Tom Becker", "Lena Ortiz"],
    "Accounting": ["Mike Dietrich"]
  };

  const slaTargets = { Critical: 1, High: 3, Medium: 5, Low: 10 }; // days

  // ---- Validation rules (admin) ----
  const rules = [
    { id: "R-001", name: "PO number present", type: "NOT_NULL", errorType: "NULL_PO_NUMBER", target: "unified_ledger", severity: "High", enabled: true,
      expression: "po_number IS NOT NULL WHERE txn_type IN ('ADD','PO_RECEIPT')" },
    { id: "R-002", name: "PO exists in PO table", type: "REFERENTIAL", errorType: "PO_RECORD_MISSING", target: "unified_ledger", severity: "High", enabled: true,
      expression: "EXISTS (SELECT 1 FROM po_table p WHERE p.po_number = l.po_number)" },
    { id: "R-003", name: "Transfer Warehouse balances", type: "RECONCILIATION", errorType: "TRANSFER_WAREHOUSE_IMBALANCE", target: "unified_ledger", severity: "Medium", enabled: true,
      expression: "SUM(shipped_qty) = SUM(received_qty) GROUP BY transfer_id WHERE facility = 'TW-001'" },
    { id: "R-004", name: "3-way match", type: "RECONCILIATION", errorType: "THREE_WAY_MATCH_VARIANCE", target: "po_table", severity: "High", enabled: true,
      expression: "ABS(invoice_qty - po_qty) <= 0 AND ABS(invoice_price - po_price) <= 0.01" },
    { id: "R-005", name: "On-hand >= 0", type: "RANGE", errorType: "NEGATIVE_ON_HAND", target: "unified_ledger", severity: "Critical", enabled: true,
      expression: "running_on_hand >= 0" },
    { id: "R-006", name: "Lot expiration resolvable", type: "REFERENTIAL", errorType: "MISSING_LOT_EXPIRATION", target: "unified_ledger", severity: "Medium", enabled: true,
      expression: "EXISTS (SELECT 1 FROM lot_master m WHERE m.lot_exp_id = l.lot_exp_id)" },
    { id: "R-007", name: "Conversion factor sane", type: "RANGE", errorType: "CONVERSION_FACTOR_OUTLIER", target: "po_table", severity: "Medium", enabled: true,
      expression: "conversion_factor BETWEEN 0.01 AND 1000" },
    { id: "R-008", name: "Negative unit cost", type: "RANGE", errorType: "NEGATIVE_ON_HAND", target: "po_table", severity: "Low", enabled: false,
      expression: "unit_cost >= 0" }
  ];

  // ---- Routing map (error type -> team -> default assignee -> JIRA project/component) ----
  const routing = [
    { errorType: "NULL_PO_NUMBER", team: "Data Engineering", assignee: "Pavel Romanov", project: "WIQ", component: "Ledger Ingest" },
    { errorType: "PO_RECORD_MISSING", team: "Data Engineering", assignee: "Sarah Chen", project: "WIQ", component: "PO Sync" },
    { errorType: "MISSING_LOT_EXPIRATION", team: "Data Engineering", assignee: "Marcus Webb", project: "WIQ", component: "Reference Data" },
    { errorType: "TRANSFER_WAREHOUSE_IMBALANCE", team: "Inventory Ops", assignee: "Diego Alvarez", project: "WIQ", component: "Transfer Recon" },
    { errorType: "NEGATIVE_ON_HAND", team: "Inventory Ops", assignee: "Priya Nair", project: "WIQ", component: "On-Hand Recon" },
    { errorType: "THREE_WAY_MATCH_VARIANCE", team: "Procurement", assignee: "Tom Becker", project: "WIQ", component: "3-Way Match" },
    { errorType: "CONVERSION_FACTOR_OUTLIER", team: "Procurement", assignee: "Lena Ortiz", project: "WIQ", component: "UoM / Conversions" }
  ];

  // ---- Helper to build status timelines ----
  function tl(arr) { return arr.map(function (x) { return { status: x[0], at: x[1], by: x[2] }; }); }

  // ---- Exceptions (each maps to a JIRA ticket) ----
  // Age is days since created relative to TODAY 2026-06-08.
  const exceptions = [
    {
      id: "ERR-24801", runDate: RUN_DATE, errorType: "NEGATIVE_ON_HAND", severity: "Critical",
      table: "unified_ledger", facility: "DIS-ATL-01", system: "Ship Hero", entityKey: "SKU-44821",
      team: "Inventory Ops", assignee: "Priya Nair", jira: "WIQ-1041", jiraStatus: "In Progress",
      created: "2026-06-07", resolved: null, recurrence: 2,
      snapshot: { "txn_id": "L-9912034", "sku": "SKU-44821", "facility": "DIS-ATL-01", "system_of_origin": "Ship Hero",
        "txn_type": "SHIP", "qty": -42, "running_on_hand": -18, "txn_ts": "2026-06-07T04:12Z", "lot_exp_id": "LOT-7781" },
      rule: "R-005",
      timeline: tl([["Open", "2026-06-07T05:02Z", "batch-validator"], ["In Progress", "2026-06-07T14:20Z", "Priya Nair"]])
    },
    {
      id: "ERR-24802", runDate: RUN_DATE, errorType: "NULL_PO_NUMBER", severity: "High",
      table: "unified_ledger", facility: "DIS-ATL-01", system: "Ship Hero", entityKey: "SKU-10233",
      team: "Data Engineering", assignee: "Pavel Romanov", jira: "WIQ-1042", jiraStatus: "Open",
      created: "2026-06-07", resolved: null, recurrence: 6,
      snapshot: { "txn_id": "L-9912101", "sku": "SKU-10233", "facility": "DIS-ATL-01", "system_of_origin": "Ship Hero",
        "txn_type": "PO_RECEIPT", "po_number": null, "qty": 240, "txn_ts": "2026-06-07T06:40Z" },
      rule: "R-001",
      timeline: tl([["Open", "2026-06-07T07:01Z", "batch-validator"]])
    },
    {
      id: "ERR-24803", runDate: RUN_DATE, errorType: "THREE_WAY_MATCH_VARIANCE", severity: "High",
      table: "po_table", facility: "CK-CHI-01", system: "Fishbowl", entityKey: "PO-558120",
      team: "Procurement", assignee: "Tom Becker", jira: "WIQ-1031", jiraStatus: "Open",
      created: "2026-06-01", resolved: null, recurrence: 3,
      snapshot: { "po_number": "PO-558120", "supplier": "Atlas Foods", "po_qty": 500, "invoice_qty": 540,
        "po_price": 2.10, "invoice_price": 2.35, "ledger_received_qty": 500, "variance_qty": 40, "variance_amt": 135.00 },
      rule: "R-004",
      timeline: tl([["Open", "2026-06-01T05:10Z", "batch-validator"]])
    },
    {
      id: "ERR-24804", runDate: RUN_DATE, errorType: "TRANSFER_WAREHOUSE_IMBALANCE", severity: "Medium",
      table: "unified_ledger", facility: "TW-001", system: "Ship Hero", entityKey: "TRF-30188",
      team: "Inventory Ops", assignee: "Diego Alvarez", jira: "WIQ-1037", jiraStatus: "In Progress",
      created: "2026-06-04", resolved: null, recurrence: 4,
      snapshot: { "transfer_id": "TRF-30188", "from_facility": "DIS-DAL-02", "to_facility": "IK-LA-02",
        "shipped_qty": 108, "received_qty": 100, "in_transit_aged_days": 5, "facility": "TW-001", "sku": "SKU-22910" },
      rule: "R-003",
      timeline: tl([["Open", "2026-06-04T05:08Z", "batch-validator"], ["In Progress", "2026-06-05T09:30Z", "Diego Alvarez"]])
    },
    {
      id: "ERR-24805", runDate: RUN_DATE, errorType: "PO_RECORD_MISSING", severity: "High",
      table: "unified_ledger", facility: "DIS-DAL-02", system: "Ship Hero", entityKey: "SKU-77310",
      team: "Data Engineering", assignee: "Sarah Chen", jira: "WIQ-1040", jiraStatus: "In Review",
      created: "2026-06-06", resolved: null, recurrence: 1,
      snapshot: { "txn_id": "L-9911880", "sku": "SKU-77310", "facility": "DIS-DAL-02", "system_of_origin": "Ship Hero",
        "txn_type": "PO_RECEIPT", "po_number": "PO-559001", "po_lookup_result": "NOT_FOUND", "qty": 60 },
      rule: "R-002",
      timeline: tl([["Open", "2026-06-06T05:14Z", "batch-validator"], ["In Progress", "2026-06-06T11:00Z", "Sarah Chen"], ["In Review", "2026-06-07T16:45Z", "Sarah Chen"]])
    },
    {
      id: "ERR-24806", runDate: RUN_DATE, errorType: "CONVERSION_FACTOR_OUTLIER", severity: "Medium",
      table: "po_table", facility: "CK-CHI-01", system: "Fishbowl", entityKey: "PO-557998",
      team: "Procurement", assignee: "Lena Ortiz", jira: "WIQ-1029", jiraStatus: "Open",
      created: "2026-05-31", resolved: null, recurrence: 2,
      snapshot: { "po_number": "PO-557998", "supplier": "BlueWave Produce", "supplier_uom": "CASE", "wonder_sku": "SKU-90021",
        "conversion_factor": 4800, "expected_range": "0.01 - 1000", "qty_ordered_case": 12 },
      rule: "R-007",
      timeline: tl([["Open", "2026-05-31T05:20Z", "batch-validator"]])
    },
    {
      id: "ERR-24807", runDate: RUN_DATE, errorType: "MISSING_LOT_EXPIRATION", severity: "Medium",
      table: "unified_ledger", facility: "IK-NYC-01", system: "Pantry", entityKey: "SKU-33820",
      team: "Data Engineering", assignee: "Marcus Webb", jira: "WIQ-1038", jiraStatus: "In Progress",
      created: "2026-06-04", resolved: null, recurrence: 5,
      snapshot: { "txn_id": "L-9910442", "sku": "SKU-33820", "facility": "IK-NYC-01", "system_of_origin": "Pantry",
        "lot_exp_id": "LOT-99999", "lot_lookup_result": "UNRESOLVED", "qty": 18 },
      rule: "R-006",
      timeline: tl([["Open", "2026-06-04T05:25Z", "batch-validator"], ["In Progress", "2026-06-06T10:10Z", "Marcus Webb"]])
    },
    {
      id: "ERR-24808", runDate: RUN_DATE, errorType: "NULL_PO_NUMBER", severity: "High",
      table: "unified_ledger", facility: "DIS-ATL-01", system: "Ship Hero", entityKey: "SKU-10501",
      team: "Data Engineering", assignee: "Pavel Romanov", jira: "WIQ-1043", jiraStatus: "Open",
      created: "2026-06-07", resolved: null, recurrence: 6,
      snapshot: { "txn_id": "L-9912140", "sku": "SKU-10501", "facility": "DIS-ATL-01", "system_of_origin": "Ship Hero",
        "txn_type": "ADD", "po_number": null, "qty": 96, "txn_ts": "2026-06-07T08:05Z" },
      rule: "R-001",
      timeline: tl([["Open", "2026-06-07T08:30Z", "batch-validator"]])
    },
    {
      id: "ERR-24809", runDate: RUN_DATE, errorType: "THREE_WAY_MATCH_VARIANCE", severity: "Critical",
      table: "po_table", facility: "DIS-DAL-02", system: "Fishbowl", entityKey: "PO-558210",
      team: "Procurement", assignee: "Tom Becker", jira: "WIQ-1022", jiraStatus: "Open",
      created: "2026-05-28", resolved: null, recurrence: 3,
      snapshot: { "po_number": "PO-558210", "supplier": "Atlas Foods", "po_qty": 1000, "invoice_qty": 1000,
        "po_price": 1.80, "invoice_price": 2.65, "variance_amt": 850.00, "ledger_received_qty": 1000 },
      rule: "R-004",
      timeline: tl([["Open", "2026-05-28T05:02Z", "batch-validator"], ["In Progress", "2026-05-29T13:00Z", "Tom Becker"], ["Open", "2026-06-02T09:00Z", "Tom Becker"]])
    },
    {
      id: "ERR-24810", runDate: RUN_DATE, errorType: "NEGATIVE_ON_HAND", severity: "Critical",
      table: "unified_ledger", facility: "IK-LA-02", system: "Pantry", entityKey: "SKU-44102",
      team: "Inventory Ops", assignee: "Priya Nair", jira: "WIQ-1044", jiraStatus: "Open",
      created: "2026-06-07", resolved: null, recurrence: 1,
      snapshot: { "txn_id": "L-9912200", "sku": "SKU-44102", "facility": "IK-LA-02", "system_of_origin": "Pantry",
        "txn_type": "CONSUME", "qty": -30, "running_on_hand": -5, "txn_ts": "2026-06-07T09:50Z" },
      rule: "R-005",
      timeline: tl([["Open", "2026-06-07T10:15Z", "batch-validator"]])
    },
    {
      id: "ERR-24811", runDate: RUN_DATE, errorType: "TRANSFER_WAREHOUSE_IMBALANCE", severity: "Medium",
      table: "unified_ledger", facility: "TW-001", system: "Ship Hero", entityKey: "TRF-30190",
      team: "Inventory Ops", assignee: "Diego Alvarez", jira: "WIQ-1039", jiraStatus: "Open",
      created: "2026-06-05", resolved: null, recurrence: 4,
      snapshot: { "transfer_id": "TRF-30190", "from_facility": "DIS-ATL-01", "to_facility": "CK-CHI-01",
        "shipped_qty": 200, "received_qty": 188, "in_transit_aged_days": 3, "facility": "TW-001", "sku": "SKU-22910" },
      rule: "R-003",
      timeline: tl([["Open", "2026-06-05T05:18Z", "batch-validator"]])
    },
    {
      id: "ERR-24812", runDate: RUN_DATE, errorType: "PO_RECORD_MISSING", severity: "High",
      table: "unified_ledger", facility: "DIS-ATL-01", system: "Ship Hero", entityKey: "SKU-77410",
      team: "Data Engineering", assignee: "Sarah Chen", jira: "WIQ-1045", jiraStatus: "Open",
      created: "2026-06-07", resolved: null, recurrence: 2,
      snapshot: { "txn_id": "L-9912260", "sku": "SKU-77410", "facility": "DIS-ATL-01", "system_of_origin": "Ship Hero",
        "txn_type": "PO_RECEIPT", "po_number": "PO-559050", "po_lookup_result": "NOT_FOUND", "qty": 144 },
      rule: "R-002",
      timeline: tl([["Open", "2026-06-07T05:50Z", "batch-validator"]])
    },
    {
      id: "ERR-24813", runDate: RUN_DATE, errorType: "CONVERSION_FACTOR_OUTLIER", severity: "High",
      table: "po_table", facility: "CK-CHI-01", system: "Fishbowl", entityKey: "PO-558001",
      team: "Procurement", assignee: "Lena Ortiz", jira: "WIQ-1025", jiraStatus: "In Progress",
      created: "2026-05-30", resolved: null, recurrence: 2,
      snapshot: { "po_number": "PO-558001", "supplier": "Northwind Dairy", "supplier_uom": "PALLET", "wonder_sku": "SKU-90100",
        "conversion_factor": 0.0001, "expected_range": "0.01 - 1000", "qty_ordered": 4 },
      rule: "R-007",
      timeline: tl([["Open", "2026-05-30T05:30Z", "batch-validator"], ["In Progress", "2026-06-01T08:45Z", "Lena Ortiz"]])
    },
    {
      id: "ERR-24814", runDate: RUN_DATE, errorType: "MISSING_LOT_EXPIRATION", severity: "Low",
      table: "unified_ledger", facility: "IK-LA-02", system: "Pantry", entityKey: "SKU-33990",
      team: "Data Engineering", assignee: "Marcus Webb", jira: "WIQ-1046", jiraStatus: "Open",
      created: "2026-06-07", resolved: null, recurrence: 1,
      snapshot: { "txn_id": "L-9912300", "sku": "SKU-33990", "facility": "IK-LA-02", "system_of_origin": "Pantry",
        "lot_exp_id": "LOT-88888", "lot_lookup_result": "UNRESOLVED", "qty": 6 },
      rule: "R-006",
      timeline: tl([["Open", "2026-06-07T06:05Z", "batch-validator"]])
    },
    {
      id: "ERR-24815", runDate: RUN_DATE, errorType: "NULL_PO_NUMBER", severity: "High",
      table: "unified_ledger", facility: "DIS-DAL-02", system: "Ship Hero", entityKey: "SKU-10888",
      team: "Data Engineering", assignee: "Pavel Romanov", jira: "WIQ-1047", jiraStatus: "Open",
      created: "2026-06-07", resolved: null, recurrence: 3,
      snapshot: { "txn_id": "L-9912330", "sku": "SKU-10888", "facility": "DIS-DAL-02", "system_of_origin": "Ship Hero",
        "txn_type": "PO_RECEIPT", "po_number": null, "qty": 72, "txn_ts": "2026-06-07T07:20Z" },
      rule: "R-001",
      timeline: tl([["Open", "2026-06-07T07:40Z", "batch-validator"]])
    },
    {
      id: "ERR-24816", runDate: RUN_DATE, errorType: "NEGATIVE_ON_HAND", severity: "High",
      table: "unified_ledger", facility: "CK-CHI-01", system: "Fishbowl", entityKey: "SKU-50120",
      team: "Inventory Ops", assignee: "Diego Alvarez", jira: "WIQ-1036", jiraStatus: "In Review",
      created: "2026-06-03", resolved: null, recurrence: 1,
      snapshot: { "txn_id": "L-9911500", "sku": "SKU-50120", "facility": "CK-CHI-01", "system_of_origin": "Fishbowl",
        "txn_type": "PRODUCE_CONSUME", "qty": -120, "running_on_hand": -8, "txn_ts": "2026-06-03T22:10Z" },
      rule: "R-005",
      timeline: tl([["Open", "2026-06-03T05:40Z", "batch-validator"], ["In Progress", "2026-06-04T08:00Z", "Diego Alvarez"], ["In Review", "2026-06-06T15:30Z", "Diego Alvarez"]])
    },
    {
      id: "ERR-24817", runDate: RUN_DATE, errorType: "THREE_WAY_MATCH_VARIANCE", severity: "Medium",
      table: "po_table", facility: "CK-CHI-01", system: "Fishbowl", entityKey: "PO-558300",
      team: "Procurement", assignee: "Lena Ortiz", jira: "WIQ-1027", jiraStatus: "Open",
      created: "2026-05-30", resolved: null, recurrence: 2,
      snapshot: { "po_number": "PO-558300", "supplier": "BlueWave Produce", "po_qty": 300, "invoice_qty": 312,
        "po_price": 0.95, "invoice_price": 0.95, "variance_qty": 12, "variance_amt": 11.40 },
      rule: "R-004",
      timeline: tl([["Open", "2026-05-30T05:45Z", "batch-validator"]])
    },
    {
      id: "ERR-24818", runDate: RUN_DATE, errorType: "TRANSFER_WAREHOUSE_IMBALANCE", severity: "High",
      table: "unified_ledger", facility: "TW-001", system: "Ship Hero", entityKey: "TRF-30150",
      team: "Inventory Ops", assignee: "Priya Nair", jira: "WIQ-1018", jiraStatus: "Open",
      created: "2026-05-27", resolved: null, recurrence: 4,
      snapshot: { "transfer_id": "TRF-30150", "from_facility": "DIS-DAL-02", "to_facility": "IK-NYC-01",
        "shipped_qty": 420, "received_qty": 360, "in_transit_aged_days": 12, "facility": "TW-001", "sku": "SKU-22999" },
      rule: "R-003",
      timeline: tl([["Open", "2026-05-27T05:10Z", "batch-validator"]])
    },
    // ---- Auto-closed (issue no longer reproduced on latest run) — flagship feature ----
    {
      id: "ERR-24790", runDate: "2026-06-06", errorType: "NULL_PO_NUMBER", severity: "High",
      table: "unified_ledger", facility: "DIS-ATL-01", system: "Ship Hero", entityKey: "SKU-10233",
      team: "Data Engineering", assignee: "Pavel Romanov", jira: "WIQ-1033", jiraStatus: "Auto-Closed",
      created: "2026-06-05", resolved: "2026-06-07", recurrence: 6,
      snapshot: { "txn_id": "L-9911201", "sku": "SKU-10233", "facility": "DIS-ATL-01", "system_of_origin": "Ship Hero",
        "txn_type": "PO_RECEIPT", "po_number": null, "qty": 200, "note": "Fixed by DE backfill; not present in 2026-06-07 run." },
      rule: "R-001",
      timeline: tl([["Open", "2026-06-05T05:01Z", "batch-validator"], ["In Progress", "2026-06-05T11:00Z", "Pavel Romanov"], ["Auto-Closed", "2026-06-07T05:30Z", "batch-validator"]])
    },
    {
      id: "ERR-24791", runDate: "2026-06-06", errorType: "MISSING_LOT_EXPIRATION", severity: "Medium",
      table: "unified_ledger", facility: "IK-NYC-01", system: "Pantry", entityKey: "SKU-33820",
      team: "Data Engineering", assignee: "Marcus Webb", jira: "WIQ-1030", jiraStatus: "Auto-Closed",
      created: "2026-06-04", resolved: "2026-06-07", recurrence: 5,
      snapshot: { "txn_id": "L-9910300", "sku": "SKU-33820", "facility": "IK-NYC-01", "system_of_origin": "Pantry",
        "lot_exp_id": "LOT-77777", "note": "lot_master backfilled; resolved on 2026-06-07 run." },
      rule: "R-006",
      timeline: tl([["Open", "2026-06-04T05:10Z", "batch-validator"], ["In Progress", "2026-06-05T10:00Z", "Marcus Webb"], ["Auto-Closed", "2026-06-07T05:30Z", "batch-validator"]])
    },
    {
      id: "ERR-24792", runDate: "2026-06-06", errorType: "PO_RECORD_MISSING", severity: "High",
      table: "unified_ledger", facility: "DIS-DAL-02", system: "Ship Hero", entityKey: "SKU-77310",
      team: "Data Engineering", assignee: "Sarah Chen", jira: "WIQ-1024", jiraStatus: "Resolved",
      created: "2026-06-02", resolved: "2026-06-05", recurrence: 1,
      snapshot: { "txn_id": "L-9909800", "sku": "SKU-77310", "facility": "DIS-DAL-02", "system_of_origin": "Ship Hero",
        "txn_type": "PO_RECEIPT", "po_number": "PO-558900", "note": "PO row created in po_table; verified resolved." },
      rule: "R-002",
      timeline: tl([["Open", "2026-06-02T05:14Z", "batch-validator"], ["In Progress", "2026-06-02T13:00Z", "Sarah Chen"], ["In Review", "2026-06-04T10:00Z", "Sarah Chen"], ["Resolved", "2026-06-05T09:00Z", "Sarah Chen"]])
    },
    {
      id: "ERR-24793", runDate: "2026-06-05", errorType: "NEGATIVE_ON_HAND", severity: "Critical",
      table: "unified_ledger", facility: "DIS-ATL-01", system: "Ship Hero", entityKey: "SKU-44821",
      team: "Inventory Ops", assignee: "Priya Nair", jira: "WIQ-1015", jiraStatus: "Closed",
      created: "2026-06-01", resolved: "2026-06-02", recurrence: 2,
      snapshot: { "txn_id": "L-9908000", "sku": "SKU-44821", "facility": "DIS-ATL-01", "system_of_origin": "Ship Hero",
        "txn_type": "SHIP", "qty": -10, "running_on_hand": -3, "note": "Adjustment txn posted; closed by Inventory Ops." },
      rule: "R-005",
      timeline: tl([["Open", "2026-06-01T05:02Z", "batch-validator"], ["In Progress", "2026-06-01T09:00Z", "Priya Nair"], ["Resolved", "2026-06-02T08:00Z", "Priya Nair"], ["Closed", "2026-06-02T17:00Z", "Priya Nair"]])
    }
  ];

  // ---- Compute age (days) and turnaround from dates ----
  function daysBetween(a, b) {
    const d1 = new Date(a + "T00:00:00Z").getTime();
    const d2 = new Date(b + "T00:00:00Z").getTime();
    return Math.round((d2 - d1) / 86400000);
  }
  exceptions.forEach(function (e) {
    e.age = daysBetween(e.created, TODAY);
    e.turnaround = e.resolved ? daysBetween(e.created, e.resolved) : null;
    e.slaTarget = slaTargets[e.severity];
    // breaching = open & age exceeds target, OR resolved but turnaround exceeded target
    const measure = e.resolved ? e.turnaround : e.age;
    e.withinSla = measure <= e.slaTarget;
    e.isOpen = !(e.jiraStatus === "Closed" || e.jiraStatus === "Auto-Closed" || e.jiraStatus === "Resolved");
    e.autoClosed = e.jiraStatus === "Auto-Closed";
  });

  // ---- Error trend over last 14 days (count of new exceptions per day) ----
  const trend = [
    { date: "2026-05-25", count: 9 }, { date: "2026-05-26", count: 11 }, { date: "2026-05-27", count: 8 },
    { date: "2026-05-28", count: 14 }, { date: "2026-05-29", count: 10 }, { date: "2026-05-30", count: 13 },
    { date: "2026-05-31", count: 7 }, { date: "2026-06-01", count: 12 }, { date: "2026-06-02", count: 9 },
    { date: "2026-06-03", count: 11 }, { date: "2026-06-04", count: 15 }, { date: "2026-06-05", count: 12 },
    { date: "2026-06-06", count: 10 }, { date: "2026-06-07", count: 13 }
  ];

  // ---- Recurring-error leaderboard (fingerprint = errorType @ facility) over 30d ----
  const recurring = [
    { fingerprint: "NULL_PO_NUMBER @ DIS-ATL-01", errorType: "NULL_PO_NUMBER", facility: "DIS-ATL-01", count30d: 6, team: "Data Engineering", lastSeen: "2026-06-07" },
    { fingerprint: "MISSING_LOT_EXPIRATION @ IK-NYC-01", errorType: "MISSING_LOT_EXPIRATION", facility: "IK-NYC-01", count30d: 5, team: "Data Engineering", lastSeen: "2026-06-04" },
    { fingerprint: "TRANSFER_WAREHOUSE_IMBALANCE @ TW-001", errorType: "TRANSFER_WAREHOUSE_IMBALANCE", facility: "TW-001", count30d: 4, team: "Inventory Ops", lastSeen: "2026-06-05" },
    { fingerprint: "THREE_WAY_MATCH_VARIANCE @ CK-CHI-01", errorType: "THREE_WAY_MATCH_VARIANCE", facility: "CK-CHI-01", count30d: 3, team: "Procurement", lastSeen: "2026-06-01" },
    { fingerprint: "NULL_PO_NUMBER @ DIS-DAL-02", errorType: "NULL_PO_NUMBER", facility: "DIS-DAL-02", count30d: 3, team: "Data Engineering", lastSeen: "2026-06-07" },
    { fingerprint: "CONVERSION_FACTOR_OUTLIER @ CK-CHI-01", errorType: "CONVERSION_FACTOR_OUTLIER", facility: "CK-CHI-01", count30d: 2, team: "Procurement", lastSeen: "2026-05-31" }
  ];

  window.DATA = {
    meta: { today: TODAY, runDate: RUN_DATE, jiraProject: "WIQ" },
    facilities: facilities,
    systems: systems,
    sourceTables: sourceTables,
    errorTypes: errorTypes,
    teams: teams,
    slaTargets: slaTargets,
    rules: rules,
    routing: routing,
    exceptions: exceptions,
    trend: trend,
    recurring: recurring
  };
})();
