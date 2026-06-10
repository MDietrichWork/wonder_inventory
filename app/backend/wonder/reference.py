"""Reference/seed data shared by the seeder and the API bootstrap.

Severity + SLA follow the locked model: Urgent (same day) / High (1d) / Medium (2d) /
Low (5d). Owner groups follow the validation framework (SC Product (IMS), Field Ops,
Procurement, Accounting (Cost Accountant), HDR Field Ops).
"""

FACILITIES = [
    {"id": "IK-NYC-01", "type": "Infinite Kitchen"},
    {"id": "IK-LA-02", "type": "Infinite Kitchen"},
    {"id": "CK-CHI-01", "type": "Central Kitchen"},
    {"id": "DIS-ATL-01", "type": "Distribution"},
    {"id": "DIS-DAL-02", "type": "Distribution"},
    {"id": "TW-001", "type": "Transfer Warehouse"},
]

SYSTEMS = ["Pantry", "Ship Hero", "Fishbowl"]

# The ledger (`system_of_origin`) and the PO table (`po_source_system`) spell the same systems
# differently (e.g. "Shiphero" vs "ShipHero", "Ship Hero"). Canonicalize on read so a system isn't
# split across donut slices / filter options. Unknown systems pass through trimmed.
_SYSTEM_CANON = {
    "shiphero": "ShipHero",
    "fishbowl": "Fishbowl",
    "pantry": "Pantry",
    "extensiv": "Extensiv",
    "extensiv(manual)": "Extensiv (Manual)",
    "ordergrid-external": "OrderGrid - External",
    "eddon": "Ed Don",
    "system": "System",
}


def canon_system(s):
    if not s:
        return s
    return _SYSTEM_CANON.get("".join(s.split()).lower(), s.strip())

TEAMS = {
    "SC Product (IMS)": ["Pavel Romanov", "Sarah Chen", "Marcus Webb"],
    "Field Ops": ["Diego Alvarez", "Priya Nair"],
    "Procurement": ["Tom Becker", "Lena Ortiz"],
    "Accounting (Cost Accountant)": ["Mike Dietrich"],
}

MOVEMENT_TYPES = ["PO Receipt", "Transfer", "Production", "Sales / Outbound", "Expiration", "Adjustment"]

# SLA resolution targets in days (Urgent = same day = 0)
SLA_TARGETS = {"Urgent": 0, "High": 1, "Medium": 2, "Low": 5}

ERROR_TYPES = [
    {"type": "NULL_PO_NUMBER", "rule": "PO number present", "ruleType": "NOT_NULL",
     "owner": "SC Product (IMS)", "desc": "PO-receipt / Add transaction is missing a PO reference."},
    {"type": "PO_RECORD_MISSING", "rule": "PO exists in PO table", "ruleType": "REFERENTIAL",
     "owner": "SC Product (IMS)", "desc": "Ledger PO reference has no matching row in the PO table."},
    {"type": "PO_OVER_RECEIPT", "rule": "Receipt within ordered qty", "ruleType": "RANGE",
     "owner": "Field Ops", "desc": "Received quantity exceeds the quantity ordered on the PO (up to 2x) — a genuine receiving overage."},
    {"type": "PO_IMPLAUSIBLE_QTY", "rule": "Received qty is physically plausible", "ruleType": "RANGE",
     "owner": "SC Product (IMS)", "desc": "Received quantity is more than 2x ordered (often vastly so) — an upstream data-corruption / unit defect, not a real overage."},
    {"type": "PO_UOM_MISMATCH", "rule": "PO/ledger consumable UoM match", "ruleType": "RECONCILIATION",
     "owner": "Procurement", "desc": "Consumable UoM on the PO differs from the ledger receipt — ordered vs received aren't comparable until the UoM/conversion is reconciled (excluded from the over-receipt % rule)."},
    {"type": "TRANSFER_WAREHOUSE_IMBALANCE", "rule": "Transfer Warehouse balances", "ruleType": "RECONCILIATION",
     "owner": "Field Ops", "desc": "Shipped vs received quantity mismatch leaves aged stock in the Transfer Warehouse."},
    {"type": "NEGATIVE_ON_HAND", "rule": "On-hand >= 0", "ruleType": "RANGE",
     "owner": "SC Product (IMS)", "desc": "Cumulative on-hand quantity went negative for an item / location."},
    {"type": "PO_MISSING_PRICE", "rule": "Vendor SKU price present", "ruleType": "NOT_NULL",
     "owner": "Procurement", "desc": "Purchase PO line has a $0.00 or NULL vendor (supplier) price — the receipt can't be costed into the GL until a price is set."},
]

# Seed validation rules (rule_key drawn from the framework catalog where applicable).
RULES = [
    {"id": "PO-01", "name": "PO number present", "primitive": "NOT_NULL", "error_type": "NULL_PO_NUMBER",
     "target_table": "unified_ledger", "severity": "Urgent", "fail_type": "Hard", "owner_group": "SC Product (IMS)",
     "params": {"column": "po_number", "where": {"txn_type": ["PO_RECEIPT", "ADD"]}},
     "expression": "po_number IS NOT NULL WHERE txn_type IN ('PO_RECEIPT','ADD')", "enabled": True},
    {"id": "PO-02", "name": "PO exists in PO table", "primitive": "REFERENTIAL", "error_type": "PO_RECORD_MISSING",
     "target_table": "unified_ledger", "severity": "High", "fail_type": "Hard", "owner_group": "SC Product (IMS)",
     "params": {"column": "po_number", "ref_table": "po_table", "ref_column": "po_number",
                "where": {"txn_type": ["PO_RECEIPT"]}},
     "expression": "EXISTS (SELECT 1 FROM po_table p WHERE p.po_number = l.po_number)", "enabled": True},
    {"id": "PO-03", "name": "PO receipt within ordered quantity", "primitive": "OVER_RECEIPT",
     "error_type": "PO_OVER_RECEIPT", "target_table": "consolidated_inventory_ledger ⋈ int_ledger_purchase_orders",
     "severity": "High", "fail_type": "Soft", "owner_group": "Field Ops",
     "params": {},  # thresholds come from settings (over_receipt_high_pct / over_receipt_urgent_pct)
     "expression": (
        "-- DAILY BATCH PO over-receipt: flag POs that RECEIVED yesterday, then compare their\n"
        "-- cumulative received-to-date vs ordered. Join ledger.ref_order_id -> PO `po`; item link =\n"
        "-- consumable_sku (both); received = SUM(ledger.consumable_quantity_change), only ref_order_type='Purchase Order'.\n"
        "DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday\n"
        "WITH touched AS (   -- (po, item) received on run_date\n"
        "  SELECT DISTINCT ref_order_id AS po, consumable_sku\n"
        "  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`\n"
        "  WHERE ref_order_type='Purchase Order' AND consumable_sku IS NOT NULL AND DATE(datetime_utc)=run_date),\n"
        "received AS (       -- cumulative received-to-date for those POs (30d lookback)\n"
        "  SELECT l.ref_order_id AS po, l.consumable_sku, SUM(l.consumable_quantity_change) AS received_qty,\n"
        "         ANY_VALUE(l.consumable_uom) AS received_uom\n"
        "  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger` l\n"
        "  JOIN touched t ON l.ref_order_id=t.po AND l.consumable_sku=t.consumable_sku\n"
        "  WHERE l.ref_order_type='Purchase Order' AND DATE(l.datetime_utc)<=run_date\n"
        "    AND l.datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(run_date), INTERVAL 30 DAY)\n"
        "  GROUP BY po, consumable_sku),\n"
        "ordered AS (\n"
        "  SELECT po, consumable_sku, SUM(consumable_sku_qty) AS ordered_qty, ANY_VALUE(consumable_uom) AS ordered_uom\n"
        "  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`\n"
        "  WHERE consumable_sku IS NOT NULL AND order_type = 'Purchase'  -- PO-side: purchases only\n"
        "  GROUP BY po, consumable_sku)\n"
        "SELECT r.po, r.consumable_sku, o.ordered_qty, o.ordered_uom, r.received_qty, r.received_uom,\n"
        "       (o.ordered_uom != r.received_uom) AS uom_mismatch,\n"
        "       ROUND((SAFE_DIVIDE(r.received_qty,o.ordered_qty)-1)*100,1) AS over_by_pct\n"
        "FROM received r JOIN ordered o USING (po, consumable_sku)\n"
        "WHERE o.ordered_qty>0 AND ( (o.ordered_uom != r.received_uom)        -- UoM mismatch -> PO_UOM_MISMATCH\n"
        "   OR r.received_qty > o.ordered_qty*1.05 )  -- else over-receipt: <=2x genuine, >2x implausible\n"
        "ORDER BY over_by_pct DESC"
     ), "enabled": True},
    {"id": "TWH-01", "name": "Transfer Warehouse balances", "primitive": "RECON_TRANSFER",
     "error_type": "TRANSFER_WAREHOUSE_IMBALANCE", "target_table": "unified_ledger", "severity": "High",
     "fail_type": "Soft", "owner_group": "Field Ops",
     "params": {"facility": "TW-001"},
     "expression": "shipped_qty = received_qty GROUP BY transfer_id WHERE facility = 'TW-001'", "enabled": True},
    {"id": "COMPLETE-02", "name": "On-hand non-negative", "primitive": "RANGE", "error_type": "NEGATIVE_ON_HAND",
     "target_table": "unified_ledger", "severity": "Urgent", "fail_type": "Soft", "owner_group": "SC Product (IMS)",
     "params": {"column": "running_on_hand", "op": "<", "value": 0},
     "expression": "running_on_hand >= 0", "enabled": True},
    {"id": "PO-09", "name": "Vendor SKU price present", "primitive": "NOT_NULL", "error_type": "PO_MISSING_PRICE",
     "target_table": "int_ledger_purchase_orders", "severity": "Urgent", "fail_type": "Hard", "owner_group": "Procurement",
     "params": {"column": "supplier_price", "where": {"order_type": ["Purchase"]}},
     "expression": (
        "-- Purchase PO lines with no usable vendor (supplier) price — receipts can't be costed.\n"
        "SELECT po, supplier_sku, consumable_sku, supplier_name, status, supplier_price, po_date_utc\n"
        "FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`\n"
        "WHERE order_type = 'Purchase' AND (supplier_price IS NULL OR supplier_price = 0)"
     ), "enabled": True},
]

ROUTING = [
    {"error_type": "NULL_PO_NUMBER", "team": "SC Product (IMS)", "assignee": "Sarah Chen",
     "jira_project": "WIQ", "jira_component": "Ledger Ingest"},
    {"error_type": "PO_RECORD_MISSING", "team": "SC Product (IMS)", "assignee": "Marcus Webb",
     "jira_project": "WIQ", "jira_component": "PO Sync"},
    {"error_type": "PO_OVER_RECEIPT", "team": "Field Ops", "assignee": "Diego Alvarez",
     "jira_project": "WIQ", "jira_component": "Receiving"},
    {"error_type": "PO_IMPLAUSIBLE_QTY", "team": "SC Product (IMS)", "assignee": "Sarah Chen",
     "jira_project": "WIQ", "jira_component": "Data Integrity"},
    {"error_type": "PO_UOM_MISMATCH", "team": "Procurement", "assignee": "Lena Ortiz",
     "jira_project": "WIQ", "jira_component": "UoM / Conversions"},
    {"error_type": "TRANSFER_WAREHOUSE_IMBALANCE", "team": "Field Ops", "assignee": "Priya Nair",
     "jira_project": "WIQ", "jira_component": "Transfers"},
    {"error_type": "NEGATIVE_ON_HAND", "team": "SC Product (IMS)", "assignee": "Pavel Romanov",
     "jira_project": "WIQ", "jira_component": "On-Hand Recon"},
    {"error_type": "PO_MISSING_PRICE", "team": "Procurement", "assignee": "Tom Becker",
     "jira_project": "WIQ", "jira_component": "Vendor Pricing"},
]

# Owner group -> Jira routing: a group (for permissions / @mentions / filtering by the team
# label) + a default assignee email. assignee_email=None falls back to the JIRA_EMAIL account
# (handy in a single-user sandbox). The `group` value is also applied as a team label on each
# ticket so Jira can be filtered by team.
JIRA_TEAM_MAP = {
    "Field Ops": {"group": "dq-field-ops", "assignee_email": None},
    "SC Product (IMS)": {"group": "dq-sc-product-ims", "assignee_email": None},
    "Procurement": {"group": "dq-procurement", "assignee_email": None},
    "Accounting (Cost Accountant)": {"group": "dq-accounting", "assignee_email": None},
    "HDR Field Ops": {"group": "dq-hdr-field-ops", "assignee_email": None},
}
