"""Central column-name map for the unified ledger + PO table.

Rules and adapters reference columns through THIS map only. To point the engine at
the real BigQuery tables, edit the names here (or the BQ_* settings) to match the
actual schema — no rule code changes needed.
"""

# Unified inventory ledger columns
LEDGER = {
    "txn_id": "txn_id",
    "txn_date": "txn_date",          # DATE (partition key) — prior-day partition is validated
    "txn_ts": "txn_ts",
    "txn_type": "txn_type",          # PO_RECEIPT, ADD, SHIP, CONSUME, PRODUCE_CONSUME, TRANSFER_*
    "sku": "sku",
    "facility": "facility",
    "facility_type": "facility_type",
    "system": "system_of_origin",    # Pantry | Ship Hero | Fishbowl
    "po_number": "po_number",
    "order_type": "order_type",
    "qty": "qty",
    "running_on_hand": "running_on_hand",
    "transfer_id": "transfer_id",
    "from_facility": "from_facility",
    "to_facility": "to_facility",
    "shipped_qty": "shipped_qty",
    "received_qty": "received_qty",
    "lot_exp_id": "lot_exp_id",
}

# Purchase-order table columns
PO = {
    "po_number": "po_number",
    "sku": "sku",
    "supplier": "supplier",
    "ordered_qty": "ordered_qty",
    "unit_price": "unit_price",
    "supplier_uom": "supplier_uom",
    "wonder_sku": "wonder_sku",
    "conversion_factor": "conversion_factor",
    "status": "status",
}

# Logical table names used internally (the adapter maps these to fixtures / BQ tables)
LEDGER_TABLE = "unified_ledger"
PO_TABLE = "po_table"
