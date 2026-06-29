  The logic (validated against real data, exactly as you and Pavel specified):
  - Join ledger ref_order_id → PO table po (the po column, confirmed)
  - Item link = consumable_sku on both tables (not ims_sku)
  - Compare SUM(consumable_quantity_change) (received, from the logs) vs consumable_sku_qty (ordered)
  - Only ledger rows where ref_order_type = 'Purchase Order'

  Live results now in the console (http://127.0.0.1:8000):
  - 158 real exceptions: 67 genuine over-receipts (PO_OVER_RECEIPT, High → Field Ops) + 91 implausible (PO_IMPLAUSIBLE_QTY, >2× ordered, Urgent → SC Product / Data Integrity)
  - Each row carries po, consumable_sku, item_name, ordered vs received, over %, real facility (CK1, …) and system (Fishbowl, …) — all filterable 
  - Filter Error type = PO_OVER_RECEIPT → just the 67 genuine ones
  - Rule & Routing Admin → PO-03 now shows the corrected join SQL, copy-paste ready for BigQuery

  Worth noting: the dominant pattern is received = exactly 2× ordered (e.g. FB-7591: ordered 100 → received 200) — a strong signal of double-logged receipts, which is a concrete, actionable defect to raise.

  Two honest caveats, both tunable:
  - Scoped to the last 30 days of receipts (partition pruning for cost — scans ~1 GB/run). Widen the INTERVAL 30 DAY for full-history reconciliation; I can switch it to a daily-scoped run for the batch model.
  - received is a net sum over that window (returns/corrections net out) — usually what you want vs ordered, but flag if you'd rather count gross receipts only.