-- PO over-receipt (TWO-WAY match, keyed on ims_sku): flag if the PO's OWN received_qty vs
-- ims_sku_qty (Layer 1, packaging units) OR the ledger cumulative vs consumable_sku_qty
-- (Layer 2, base units) is over the threshold. Pure UoM-mismatch rows (neither layer over)
-- become PO_UOM_MISMATCH; the rest PO_OVER_RECEIPT (over_frac >= 1.00 -> Urgent, else High).
-- daily batch target = the just-closed day (yesterday PST in prod)
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);

WITH t AS (
  SELECT DISTINCT
    ref_order_id AS po,
    ims_sku
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE
    ref_order_type = 'Purchase Order' AND ims_sku IS NOT NULL
    AND DATE(datetime_utc) = run_date
),

evt AS (
  SELECT
    l.ref_order_id AS po,
    l.ims_sku,
    l.consumable_sku,
    l.datetime_utc,
    l.ims_quantity_change AS q,
    l.consumable_uom AS ruom,
    l.facility_name AS facility,
    l.facility_type,
    l.system_of_origin AS system,
    l.item_name,
    l.l1_action,
    l.l2_action,
    SUM(l.consumable_quantity_change) OVER (
      PARTITION BY l.ref_order_id, l.ims_sku ORDER BY l.datetime_utc
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_recv,
    -- how many 'Add' receipts share this exact quantity (>=2 = probable double-booking).
    -- Partition key CAST to STRING — BigQuery can't PARTITION BY a FLOAT64.
    SUM(IF(l.l1_action = 'Add' AND l.consumable_quantity_change > 0, 1, 0)) OVER (
      PARTITION BY l.ref_order_id, l.ims_sku, CAST(ROUND(l.consumable_quantity_change, 4) AS STRING)
    ) AS same_qty_receipts
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger` AS l
  INNER JOIN t
    ON l.ref_order_id = t.po AND l.ims_sku = t.ims_sku
  -- ref_order_type='Purchase Order' INTENTIONALLY captures EVERY ledger line tied to the PO,
  -- positive and negative, so SUM(q) below is a true NET. A receiver may double-log / over-log
  -- a receipt and then a correction is booked back against the same PO — either an auto negative
  -- receipt (l1/l2 = Remove/PO Receipt) or a manual fix (Adjust/Update Received Order). Both are
  -- ref_order_type='Purchase Order', so they net out here. Do NOT narrow this to l1_action='Add'
  -- or l2_action LIKE '%Receipt%' — that would drop the manual corrections and re-break netting.
  -- (Corrections booked as generic Adjust/Cycle-Count carry NO PO ref and are deliberately left
  -- alone: they can't be attributed to a specific PO without a fuzzy SKU+facility+window guess.)
  WHERE
    l.ref_order_type = 'Purchase Order' AND l.ims_sku IS NOT NULL
    AND DATE(l.datetime_utc) <= run_date
    AND l.datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(run_date), INTERVAL 30 DAY)
),

received AS (   -- LAYER 2 basis: net ledger receipts per (po, ims_sku), BASE units
  SELECT
    po,
    ims_sku,
    SUM(q) AS led_received,
    ANY_VALUE(ruom) AS received_uom,
    ANY_VALUE(consumable_sku) AS consumable_sku,
    ANY_VALUE(facility) AS facility,
    ANY_VALUE(facility_type) AS facility_type,
    ANY_VALUE(system) AS system,
    ANY_VALUE(item_name) AS item_name,
    -- movement action of the largest receipt = the dominant receiving event (l1 / l2)
    ANY_VALUE(l1_action HAVING MAX q) AS move_l1,
    ANY_VALUE(l2_action HAVING MAX q) AS move_l2,
    MAX(same_qty_receipts) AS dup_receipts   -- >=2 = ledger booked the same receipt twice
  FROM evt
  GROUP BY po, ims_sku
),

ordered AS (   -- ordered in BOTH units + the PO's OWN received_qty (LAYER 1), per (po, ims_sku)
  SELECT
    po,
    ims_sku,
    SUM(ims_sku_qty) AS ordered_pkg,    -- packaging units (cs/pk/ea) — Layer 1 basis
    SUM(consumable_sku_qty) AS ordered_base,    -- base units (oz/lb/g)       — Layer 2 basis
    SUM(received_qty) AS po_received,     -- the PO's own cumulative received (packaging)
    ANY_VALUE(consumable_uom) AS ordered_uom,
    ANY_VALUE(ims_uom) AS ims_uom,
    ANY_VALUE(supplier_name) AS supplier,
    ANY_VALUE(status) AS status
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE ims_sku IS NOT NULL AND order_type = 'Purchase'   -- PO-side: purchases only (for now)
  GROUP BY po, ims_sku
),

breach AS (
  SELECT
    e.po,
    e.ims_sku,
    -- first receipt where the ledger cumulative (base) crossed the over-receipt threshold
    DATE(MIN(IF(e.running_recv > o.ordered_base * (1 + 0.3), e.datetime_utc, NULL))) AS over_breach_date,
    -- first receipt that introduced a unit different from the order's
    DATE(MIN(IF(
      o.ordered_uom IS NOT NULL AND e.ruom IS NOT NULL AND e.ruom != o.ordered_uom,
      e.datetime_utc, NULL
    ))) AS uom_breach_date,
    DATE(MIN(e.datetime_utc)) AS first_receipt_date,
    DATE(MAX(e.datetime_utc)) AS last_receipt_date
  FROM evt AS e INNER JOIN ordered AS o ON e.po = o.po AND e.ims_sku = o.ims_sku
  GROUP BY po, ims_sku
),

flagged AS (   -- TWO-WAY match: keep a row if the PO's own books OR the ledger cumulative are over
  SELECT
    r.po,
    r.ims_sku,
    r.consumable_sku,
    r.item_name,
    o.ordered_pkg,
    o.ordered_base,
    o.po_received,
    r.led_received,
    o.ordered_uom,
    r.received_uom,
    o.ims_uom,
    r.facility,
    r.facility_type,
    r.system,
    o.supplier,
    o.status,
    r.move_l1,
    r.move_l2,
    r.dup_receipts,
    b.over_breach_date,
    b.uom_breach_date,
    b.first_receipt_date,
    b.last_receipt_date,
    (o.ordered_pkg > 0 AND o.po_received > o.ordered_pkg * (1 + 0.3)) AS po_over,
    (o.ordered_base > 0 AND r.led_received > o.ordered_base * (1 + 0.3)) AS led_over,
    SAFE_DIVIDE(o.po_received, NULLIF(o.ordered_pkg, 0)) - 1 AS po_over_frac,
    SAFE_DIVIDE(r.led_received, NULLIF(o.ordered_base, 0)) - 1 AS led_over_frac,
    GREATEST(
      COALESCE(SAFE_DIVIDE(o.po_received, NULLIF(o.ordered_pkg, 0)) - 1, -9),
      COALESCE(SAFE_DIVIDE(r.led_received, NULLIF(o.ordered_base, 0)) - 1, -9)
    ) AS over_frac,
    (o.ordered_uom IS NOT NULL AND r.received_uom IS NOT NULL AND o.ordered_uom != r.received_uom) AS uom_mismatch
  FROM received AS r INNER JOIN ordered AS o ON r.po = o.po AND r.ims_sku = o.ims_sku
  INNER JOIN breach AS b ON r.po = b.po AND r.ims_sku = b.ims_sku
  WHERE (o.ordered_pkg > 0 OR o.ordered_base > 0) AND (
    (o.ordered_uom IS NOT NULL AND r.received_uom IS NOT NULL AND o.ordered_uom != r.received_uom)
    OR (o.ordered_pkg > 0 AND o.po_received > o.ordered_pkg * (1 + 0.3))
    OR (o.ordered_base > 0 AND r.led_received > o.ordered_base * (1 + 0.3))
  )
),

ranked AS (
  SELECT
    *,
    COUNT(*) OVER () AS total_matches,
    ROW_NUMBER() OVER (
      PARTITION BY (CASE
        WHEN uom_mismatch AND NOT (po_over OR led_over) THEN 'uom'
        WHEN over_frac >= 1.0 THEN 'over_urgent'  -- >=100% over (>=2x ordered): likely error (Urgent)
        ELSE 'over_high'
      END)                         -- 30-99% over: supply-chain signal (High)
      ORDER BY over_frac DESC
    ) AS rn
  FROM flagged
)

SELECT * EXCEPT (rn) FROM ranked
WHERE rn <= 500
ORDER BY over_frac DESC
