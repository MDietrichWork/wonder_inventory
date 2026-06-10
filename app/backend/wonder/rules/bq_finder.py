"""BigQuery rule finders — push the rule logic into SQL and return ONLY offending rows.

At 187M-row ledger / 18.8M-row PO scale we can't fetch tables into Python, so the
bigquery data path uses these SQL finders instead of the in-Python engine. Every query
is capped via maximum_bytes_billed so a misfire can never run up a large bill.

Currently implemented: PO-03 over-receipt (the rule that actually fires on real data).
PO-01/PO-02 are kept in the catalog but find nothing on current data; transfer/on-hand
rules need cross-partition cumulative logic (later).
"""
from typing import List, Tuple

from .engine import Finding
from ..config import settings

MAX_GB = 60               # backfill scans more history; daily stays tiny
RESULT_CAP = 500          # per-band ticket cap for a daily run (touched-set is normally far smaller)
BACKFILL_CAP = 10         # per-band cap (genuine / implausible / UoM-mismatch) — ~30 tickets for the demo
RECEIPT_LOOKBACK_DAYS = 30   # daily: how far back to sum cumulative received for a touched PO
BACKFILL_LOOKBACK_DAYS = 14   # initial run: history to sweep for the existing backlog (2 weeks)

# Over-receipt, per Pavel:
#   order join : ledger.ref_order_id  ->  PO `po`
#   item link  : consumable_sku (both tables)
#   received   : SUM(ledger.consumable_quantity_change), ref_order_type='Purchase Order', up to run_date
#   ordered    : PO consumable_sku_qty
# Two run modes:
#   daily    — flag only POs that RECEIVED on the run-date partition, cumulative received vs ordered
#   backfill — flag ALL over-received POs across history (the one-time initial catch-up)


def _build_sql(backfill: bool, lookback: int, high: float, cap: int) -> str:
    proj, dset = settings.gcp_project, settings.bq_dataset
    led, po = settings.bq_ledger_table, settings.bq_po_table
    # Per-receipt event stream (the same rows the daily/backfill modes already scan) carrying a
    # running cumulative received qty per (po, sku) — so we can pinpoint the BREACH date: the
    # receipt at which cumulative received first crossed the ordered threshold = when the error
    # truly began. (daily restricts to POs touched on the run-date; backfill sweeps the window.)
    join = (f"""
  JOIN (SELECT DISTINCT ref_order_id AS po, consumable_sku FROM `{proj}.{dset}.{led}`
        WHERE ref_order_type = 'Purchase Order' AND consumable_sku IS NOT NULL
          AND DATE(datetime_utc) = @run_date) t
    ON l.ref_order_id = t.po AND l.consumable_sku = t.consumable_sku""" if not backfill else "")
    evt = f"""evt AS (
  SELECT l.ref_order_id AS po, l.consumable_sku, l.datetime_utc,
         l.consumable_quantity_change AS q, l.consumable_uom AS ruom,
         l.facility_name AS facility, l.system_of_origin AS system, l.item_name AS item_name,
         l.l1_action AS l1_action, l.l2_action AS l2_action,
         SUM(l.consumable_quantity_change) OVER (
           PARTITION BY l.ref_order_id, l.consumable_sku ORDER BY l.datetime_utc
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_recv
  FROM `{proj}.{dset}.{led}` l{join}
  WHERE l.ref_order_type = 'Purchase Order' AND l.consumable_sku IS NOT NULL
    AND DATE(l.datetime_utc) <= @run_date
    AND l.datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY))"""
    # Rank within each band (genuine over_frac<=1 vs implausible >1) so the cap keeps BOTH
    # populations represented instead of the most-extreme corrupt rows crowding out genuine ones.
    return "WITH " + evt + f""",
received AS (
  SELECT po, consumable_sku, SUM(q) AS received_qty, ANY_VALUE(ruom) AS received_uom,
         ANY_VALUE(facility) AS facility, ANY_VALUE(system) AS system, ANY_VALUE(item_name) AS item_name,
         -- movement action of the largest receipt = the dominant receiving event (l1 / l2)
         ANY_VALUE(l1_action HAVING MAX q) AS move_l1, ANY_VALUE(l2_action HAVING MAX q) AS move_l2
  FROM evt GROUP BY po, consumable_sku),
ordered AS (
  SELECT po, consumable_sku, SUM(consumable_sku_qty) AS ordered_qty,
         ANY_VALUE(consumable_uom) AS ordered_uom,
         ANY_VALUE(supplier_name) AS supplier, ANY_VALUE(status) AS status
  FROM `{proj}.{dset}.{po}`
  WHERE consumable_sku IS NOT NULL AND order_type = 'Purchase'   -- PO-side: purchases only (for now)
  GROUP BY po, consumable_sku),
breach AS (
  SELECT e.po, e.consumable_sku,
         -- first receipt where cumulative crossed the over-receipt threshold
         DATE(MIN(IF(e.running_recv > o.ordered_qty * (1 + {high}), e.datetime_utc, NULL))) AS over_breach_date,
         -- first receipt that introduced a unit different from the order's
         DATE(MIN(IF(o.ordered_uom IS NOT NULL AND e.ruom IS NOT NULL AND e.ruom != o.ordered_uom,
                     e.datetime_utc, NULL))) AS uom_breach_date,
         DATE(MIN(e.datetime_utc)) AS first_receipt_date,
         DATE(MAX(e.datetime_utc)) AS last_receipt_date
  FROM evt e JOIN ordered o USING (po, consumable_sku)
  GROUP BY po, consumable_sku),
flagged AS (
  SELECT r.po, r.consumable_sku, r.item_name, o.ordered_qty, r.received_qty,
         o.ordered_uom, r.received_uom, r.facility, r.system, o.supplier, o.status,
         r.move_l1, r.move_l2,
         SAFE_DIVIDE(r.received_qty, o.ordered_qty) - 1 AS over_frac,
         (o.ordered_uom IS NOT NULL AND r.received_uom IS NOT NULL AND o.ordered_uom != r.received_uom) AS uom_mismatch,
         b.over_breach_date, b.uom_breach_date, b.first_receipt_date, b.last_receipt_date
  FROM received r JOIN ordered o USING (po, consumable_sku)
                  JOIN breach b USING (po, consumable_sku)
  WHERE o.ordered_qty > 0 AND (
        (o.ordered_uom IS NOT NULL AND r.received_uom IS NOT NULL AND o.ordered_uom != r.received_uom)
        OR r.received_qty > o.ordered_qty * (1 + {high})
  )
),
ranked AS (
  SELECT *, COUNT(*) OVER() AS total_matches,
         ROW_NUMBER() OVER (
           PARTITION BY (CASE WHEN uom_mismatch THEN 'uom' WHEN over_frac > 1 THEN 'impl' ELSE 'gen' END)
           ORDER BY over_frac DESC) AS rn
  FROM flagged
)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap}
ORDER BY over_frac DESC"""


def _d(v):
    return str(v) if v else None


def _snap(r, high):
    return {
        "po": r.po, "consumable_sku": r.consumable_sku, "item_name": r.item_name,
        "ordered_qty": r.ordered_qty, "ordered_uom": r.ordered_uom,
        "received_qty": r.received_qty, "received_uom": r.received_uom,
        "uom_match": (r.ordered_uom == r.received_uom),
        "over_by_pct": round((r.over_frac or 0.0) * 100, 1), "tolerance_pct": round(high * 100, 1),
        "status": r.status, "supplier": r.supplier,
        "facility": r.facility or "—", "system": r.system or "—",
        # inventory movement (ledger l1 / l2 of the receiving event) — drives the dashboard breakout
        "movement": ("%s / %s" % (r.move_l1, r.move_l2)) if getattr(r, "move_l1", None) else None,
        # data-derived timeline: when the error actually began vs. last activity
        "first_receipt": _d(r.first_receipt_date), "last_receipt": _d(r.last_receipt_date),
    }


def _over_receipt(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """PO_OVER_RECEIPT (genuine ≤2× → High, Field Ops) and PO_IMPLAUSIBLE_QTY (>2× → Urgent, SC Product)."""
    bq = ds._bq
    high = settings.over_receipt_high_pct
    src = settings.bq_ledger_table
    lookback = BACKFILL_LOOKBACK_DAYS if backfill else RECEIPT_LOOKBACK_DAYS
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    sql = _build_sql(backfill, lookback, high, cap)
    cfg = bq.QueryJobConfig(
        maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
        query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)],
    )
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        ek = f"{r.po}:{r.consumable_sku}"
        s = _snap(r, high)
        if r.uom_mismatch:  # ordered/received in different UoM → over-receipt % is not comparable
            # the error began at the first receipt in the conflicting unit
            s["breached_at"] = _d(r.uom_breach_date) or s["first_receipt"] or s["last_receipt"]
            findings.append(Finding("PO-03", "PO_UOM_MISMATCH", "High", src, ek, s))
        elif (r.over_frac or 0.0) > 1:  # received > 2x ordered
            s["implausible_quantity"] = True
            s["breached_at"] = _d(r.over_breach_date) or s["last_receipt"]
            findings.append(Finding("PO-03", "PO_IMPLAUSIBLE_QTY", "Urgent", src, ek, s))
        else:
            s["breached_at"] = _d(r.over_breach_date) or s["last_receipt"]
            findings.append(Finding("PO-03", "PO_OVER_RECEIPT", "High", src, ek, s))
    return findings, total


def _build_price_sql(backfill: bool, lookback: int, cap: int) -> str:
    """PO-09: CLOSED Purchase PO lines with no usable vendor price (a finalized PO that was never
    priced — can't be costed). Single-table, cheap. Daily flags lines created on the run-date;
    backfill sweeps the lookback window. Age anchors to po_date_utc."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    date_filter = ("AND DATE(po_date_utc) = @run_date" if not backfill else
                   f"AND DATE(po_date_utc) <= @run_date "
                   f"AND po_date_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY)")
    return f"""WITH flagged AS (
  SELECT po, supplier_sku,
         ANY_VALUE(po_source_system) AS system, ANY_VALUE(destination_name) AS facility,
         ANY_VALUE(order_type) AS order_type,
         ANY_VALUE(supplier_name) AS supplier_name, ANY_VALUE(supplier_sku_name) AS supplier_sku_name,
         ANY_VALUE(status) AS status, MIN(supplier_price) AS supplier_price, MIN(po_date_utc) AS po_date_utc
  FROM `{proj}.{dset}.{po}`
  WHERE order_type = 'Purchase' AND (supplier_price IS NULL OR supplier_price = 0)
        AND supplier_sku IS NOT NULL AND UPPER(status) = 'CLOSED' {date_filter}
  GROUP BY po, supplier_sku),
ranked AS (
  SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY po_date_utc DESC) AS rn
  FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap} ORDER BY po_date_utc DESC"""


def _missing_price(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """PO_MISSING_PRICE (Urgent, Procurement) — order_type='Purchase' AND supplier_price IS NULL OR 0."""
    bq = ds._bq
    src = settings.bq_po_table
    lookback = BACKFILL_LOOKBACK_DAYS if backfill else RECEIPT_LOOKBACK_DAYS
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    sql = _build_price_sql(backfill, lookback, cap)
    cfg = bq.QueryJobConfig(
        maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
        query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)],
    )
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        ek = f"{r.po}:{r.supplier_sku}"
        # display fields in the order the detail drawer should show them
        snap = {
            "po": r.po, "system": r.system, "facility": r.facility or "—",  # PO-side facility = destination
            "order_type": r.order_type, "po_date_utc": str(r.po_date_utc) if r.po_date_utc else None,
            "supplier_name": r.supplier_name, "supplier_sku": r.supplier_sku,
            "supplier_sku_name": r.supplier_sku_name,
            "supplier_price": r.supplier_price,   # NULL or 0 — the offending value
            "breached_at": r.po_date_utc.date().isoformat() if r.po_date_utc else None,
        }
        findings.append(Finding("PO-09", "PO_MISSING_PRICE", "Urgent", src, ek, snap))
    return findings, total


def recheck_price(ds, pairs):
    """Current vendor price for a set of (po, supplier_sku) OPEN PO-09 tickets, so the job can
    auto-close the ones that now have a price. Returns {(po, supplier_sku): {"missing": bool}}."""
    if not pairs:
        return {}
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    keys = ["%s~~%s" % (p, s) for (p, s) in pairs if p is not None and s is not None]
    if not keys:
        return {}
    sql = f"""
    SELECT po, supplier_sku AS sku, MIN(supplier_price) AS price
    FROM `{proj}.{dset}.{po}`
    WHERE order_type = 'Purchase' AND CONCAT(po, '~~', supplier_sku) IN UNNEST(@keys)
    GROUP BY po, sku"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("keys", "STRING", keys)])
    out = {}
    for row in ds.client.query(sql, job_config=cfg).result():
        out[(row.po, row.sku)] = {"missing": (row.price is None or row.price == 0)}
    return out


def _build_null_po_sql(backfill: bool, lookback: int, cap: int) -> str:
    """PO-13: a Purchase row in the master PO table with a NULL/blank PO number. Safety-net —
    finds 0 on current data; wired so it tickets + auto-closes if upstream ever degrades."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    date_filter = ("AND DATE(po_date_utc) = @run_date" if not backfill else
                   f"AND (po_date_utc IS NULL OR (DATE(po_date_utc) <= @run_date "
                   f"AND po_date_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY)))")
    return f"""WITH flagged AS (
  SELECT CAST(_id AS STRING) AS id, ANY_VALUE(supplier_name) AS supplier_name,
         ANY_VALUE(supplier_sku) AS supplier_sku, ANY_VALUE(consumable_sku) AS consumable_sku,
         MIN(po_date_utc) AS po_date_utc
  FROM `{proj}.{dset}.{po}`
  WHERE order_type = 'Purchase' AND (po IS NULL OR TRIM(po) = '') {date_filter}
  GROUP BY id),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY po_date_utc DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap}"""


def _null_po(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """PO_MISSING_NUMBER (Urgent, SC Product (IMS)) — PO master row with no PO number."""
    bq = ds._bq
    src = settings.bq_po_table
    lookback = BACKFILL_LOOKBACK_DAYS if backfill else RECEIPT_LOOKBACK_DAYS
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    sql = _build_null_po_sql(backfill, lookback, cap)
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        snap = {
            "po_id": r.id, "po": None, "supplier_name": r.supplier_name, "supplier_sku": r.supplier_sku,
            "consumable_sku": r.consumable_sku,
            "po_date_utc": str(r.po_date_utc) if r.po_date_utc else None,
            "breached_at": (r.po_date_utc.date().isoformat() if r.po_date_utc else run_date),
        }
        findings.append(Finding("PO-13", "PO_MISSING_NUMBER", "Urgent", src, r.id, snap))
    return findings, total


def recheck_null_po(ds, ids):
    """Whether each open PO-13 ticket's PO row still has a null/blank po — close once populated."""
    if not ids:
        return {}
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    sql = f"""SELECT CAST(_id AS STRING) AS id, MAX(IF(po IS NULL OR TRIM(po) = '', 1, 0)) AS still_null
    FROM `{proj}.{dset}.{po}` WHERE CAST(_id AS STRING) IN UNNEST(@ids) GROUP BY id"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("ids", "STRING", [str(i) for i in ids])])
    return {r.id: {"missing": bool(r.still_null)} for r in ds.client.query(sql, job_config=cfg).result()}


def _build_sku_not_on_po_sql(backfill: bool, lookback: int, cap: int) -> str:
    """PO-14 (catalog PO-02): a consumable_sku received against an existing PO that isn't on the
    PO's lines. Ledger-sourced, so it carries the receiving l1/l2 movement."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    led, po = settings.bq_ledger_table, settings.bq_po_table
    date_filter = ("AND DATE(datetime_utc) = @run_date" if not backfill else
                   f"AND DATE(datetime_utc) <= @run_date "
                   f"AND datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY)")
    return f"""WITH led AS (
  SELECT ref_order_id AS po, consumable_sku,
         ANY_VALUE(facility_name) AS facility, ANY_VALUE(system_of_origin) AS system,
         ANY_VALUE(item_name) AS item_name, ANY_VALUE(consumable_uom) AS ruom,
         SUM(consumable_quantity_change) AS received_qty,
         DATE(MIN(datetime_utc)) AS first_receipt_date, DATE(MAX(datetime_utc)) AS last_receipt_date,
         ANY_VALUE(l1_action HAVING MAX consumable_quantity_change) AS move_l1,
         ANY_VALUE(l2_action HAVING MAX consumable_quantity_change) AS move_l2
  FROM `{proj}.{dset}.{led}`
  WHERE ref_order_type = 'Purchase Order' AND consumable_sku IS NOT NULL {date_filter}
  GROUP BY po, consumable_sku),
po_keys AS (SELECT DISTINCT po, consumable_sku FROM `{proj}.{dset}.{po}`
            WHERE order_type = 'Purchase' AND consumable_sku IS NOT NULL),
po_exists AS (SELECT po, ANY_VALUE(supplier_name) AS supplier FROM `{proj}.{dset}.{po}`
              WHERE order_type = 'Purchase' GROUP BY po),
flagged AS (
  SELECT l.*, pe.supplier
  FROM led l JOIN po_exists pe USING (po)
  LEFT JOIN po_keys pk ON l.po = pk.po AND l.consumable_sku = pk.consumable_sku
  WHERE pk.po IS NULL),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches,
                  ROW_NUMBER() OVER (ORDER BY last_receipt_date DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap} ORDER BY last_receipt_date DESC"""


def _sku_not_on_po(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """PO_SKU_NOT_ON_PO (High, SC Product (IMS)) — received SKU not on the matching PO."""
    bq = ds._bq
    src = settings.bq_ledger_table
    lookback = BACKFILL_LOOKBACK_DAYS if backfill else RECEIPT_LOOKBACK_DAYS
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    sql = _build_sku_not_on_po_sql(backfill, lookback, cap)
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        ek = f"{r.po}:{r.consumable_sku}"
        snap = {
            "po": r.po, "consumable_sku": r.consumable_sku, "item_name": r.item_name,
            "supplier_name": r.supplier, "on_po": False,
            "received_qty": r.received_qty, "received_uom": r.ruom,
            "facility": r.facility or "—", "system": r.system or "—",
            "movement": ("%s / %s" % (r.move_l1, r.move_l2)) if r.move_l1 else None,
            "first_receipt": _d(r.first_receipt_date), "last_receipt": _d(r.last_receipt_date),
            "breached_at": _d(r.first_receipt_date),  # first received against the PO without being on it
        }
        findings.append(Finding("PO-14", "PO_SKU_NOT_ON_PO", "High", src, ek, snap))
    return findings, total


def recheck_sku_on_po(ds, pairs):
    """Which (po, consumable_sku) tickets are NOW on the PO — those can be auto-closed."""
    if not pairs:
        return set()
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    keys = ["%s~~%s" % (p, s) for (p, s) in pairs if p is not None and s is not None]
    if not keys:
        return set()
    sql = f"""SELECT DISTINCT CONCAT(po, '~~', consumable_sku) AS key
    FROM `{proj}.{dset}.{po}`
    WHERE order_type = 'Purchase' AND CONCAT(po, '~~', consumable_sku) IN UNNEST(@keys)"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("keys", "STRING", keys)])
    return {r.key for r in ds.client.query(sql, job_config=cfg).result()}


def _build_transfer_order_missing_sql(backfill: bool, lookback: int, cap: int) -> str:
    """XFER-01: a Transfer Out pick references a Transfer Order id not in the transfer-order
    population (orders table, order_type='Transfer'). One row per orphan transfer order."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    led, po = settings.bq_ledger_table, settings.bq_po_table
    date_filter = ("AND DATE(datetime_utc) = @run_date" if not backfill else
                   f"AND DATE(datetime_utc) <= @run_date "
                   f"AND datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY)")
    return f"""WITH picks AS (
  SELECT ref_order_id AS to_id,
         COUNT(DISTINCT consumable_sku) AS skus_picked, ANY_VALUE(item_name) AS sample_item,
         ANY_VALUE(facility_name) AS facility, ANY_VALUE(system_of_origin) AS system,
         SUM(consumable_quantity_change) AS net_qty,
         DATE(MIN(datetime_utc)) AS first_seen, DATE(MAX(datetime_utc)) AS last_seen,
         ANY_VALUE(l1_action) AS move_l1, ANY_VALUE(l2_action) AS move_l2
  FROM `{proj}.{dset}.{led}`
  WHERE ref_order_type='Transfer Order' AND l2_action='Transfer Out' AND ref_order_id IS NOT NULL {date_filter}
  GROUP BY to_id),
to_pop AS (SELECT DISTINCT po AS to_id FROM `{proj}.{dset}.{po}` WHERE order_type='Transfer'),
flagged AS (SELECT p.* FROM picks p LEFT JOIN to_pop t USING (to_id) WHERE t.to_id IS NULL),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY last_seen DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap} ORDER BY last_seen DESC"""


def _transfer_order_missing(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """TRANSFER_ORDER_MISSING (High, SC Product (IMS)) — pick against a non-existent transfer order."""
    bq = ds._bq
    src = settings.bq_ledger_table
    lookback = BACKFILL_LOOKBACK_DAYS if backfill else RECEIPT_LOOKBACK_DAYS
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    sql = _build_transfer_order_missing_sql(backfill, lookback, cap)
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        snap = {
            "transfer_order": r.to_id, "transfer_order_exists": False,
            "skus_picked": r.skus_picked, "sample_item": r.sample_item, "net_qty_change": r.net_qty,
            "facility": r.facility or "—", "system": r.system or "—",
            "movement": ("%s / %s" % (r.move_l1, r.move_l2)) if r.move_l1 else None,
            "first_receipt": _d(r.first_seen), "last_receipt": _d(r.last_seen),
            "breached_at": _d(r.first_seen),
        }
        findings.append(Finding("XFER-01", "TRANSFER_ORDER_MISSING", "High", src, r.to_id, snap))
    return findings, total


def recheck_to_exists(ds, to_ids):
    """Which transfer-order ids now exist in the transfer population — those can be auto-closed."""
    if not to_ids:
        return set()
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    ids = [str(i) for i in to_ids if i is not None]
    if not ids:
        return set()
    sql = f"""SELECT DISTINCT po AS id FROM `{proj}.{dset}.{po}`
    WHERE order_type='Transfer' AND po IN UNNEST(@ids)"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("ids", "STRING", ids)])
    return {r.id for r in ds.client.query(sql, job_config=cfg).result()}


_FINDERS = {"PO-03": _over_receipt, "PO-09": _missing_price, "PO-13": _null_po,
            "PO-14": _sku_not_on_po, "XFER-01": _transfer_order_missing}


def find_bigquery(ds, run_date, rules, backfill=False) -> Tuple[List[Finding], int]:
    """Run every supported rule via SQL. Returns (findings, rows_considered)."""
    all_findings: List[Finding] = []
    considered = 0
    supported = [r for r in rules if getattr(r, "enabled", True) and r.id in _FINDERS]
    for rule in supported:
        fnd, total = _FINDERS[rule.id](ds, run_date, backfill=backfill)
        all_findings.extend(fnd)
        considered += total
    return all_findings, considered


def breakdown(ds, po: str, consumable_sku: str, system: str = None):
    """The PO line vs the ledger receipt events for one (po, consumable_sku) — the 'why it
    flagged' detail shown in the drawer. Cluster-pruned by system_of_origin + a date window
    so it stays cheap per click."""
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    led, potbl = settings.bq_ledger_table, settings.bq_po_table
    sys_filter = "AND system_of_origin = @sys" if (system and system != "—") else ""
    sql = f"""
    SELECT 'PO' AS source, consumable_sku_qty AS qty, consumable_uom AS uom, order_type,
           CAST(NULL AS STRING) AS l1_action, CAST(NULL AS STRING) AS l2_action, status,
           CAST(NULL AS STRING) AS facility, po_date_utc AS ts
    FROM `{proj}.{dset}.{potbl}` WHERE po = @po AND consumable_sku = @sku AND order_type = 'Purchase'
    UNION ALL
    SELECT 'LEDGER', consumable_quantity_change, consumable_uom, CAST(NULL AS STRING),
           l1_action, l2_action, CAST(NULL AS STRING), facility_name, datetime_utc
    FROM `{proj}.{dset}.{led}`
    WHERE ref_order_id = @po AND consumable_sku = @sku {sys_filter}
      AND datetime_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {BACKFILL_LOOKBACK_DAYS + 35} DAY)
    ORDER BY (source = 'LEDGER'), ts
    """
    params = [bq.ScalarQueryParameter("po", "STRING", po), bq.ScalarQueryParameter("sku", "STRING", consumable_sku)]
    if sys_filter:
        params.append(bq.ScalarQueryParameter("sys", "STRING", system))
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3), query_parameters=params)
    rows = list(ds.client.query(sql, job_config=cfg).result())
    return [{"source": r.source, "qty": r.qty, "uom": r.uom, "order_type": r.order_type, "l1_action": r.l1_action,
             "l2_action": r.l2_action, "status": r.status, "facility": r.facility,
             "ts": str(r.ts) if r.ts else None} for r in rows]


def recheck(ds, pairs):
    """Current received-vs-ordered + UoM for a set of (po, consumable_sku) OPEN tickets, so the
    job can auto-close the ones that no longer fail. Returns {(po, sku): {recv, ruom, ord, ouom}}.
    Receipts summed over the lookback window (recent fixes show up; very old POs may read as
    'no recent receipts' and are left open rather than risk a false close)."""
    if not pairs:
        return {}
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    led, potbl = settings.bq_ledger_table, settings.bq_po_table
    keys = ["%s~~%s" % (p, s) for (p, s) in pairs if p is not None and s is not None]
    if not keys:
        return {}
    sql = f"""
    WITH received AS (
      SELECT ref_order_id AS po, consumable_sku AS sku, SUM(consumable_quantity_change) AS recv,
             ANY_VALUE(consumable_uom) AS ruom
      FROM `{proj}.{dset}.{led}`
      WHERE ref_order_type = 'Purchase Order' AND consumable_sku IS NOT NULL
        AND CONCAT(ref_order_id, '~~', consumable_sku) IN UNNEST(@keys)
        AND datetime_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {BACKFILL_LOOKBACK_DAYS} DAY)
      GROUP BY po, sku),
    ordered AS (
      SELECT po, consumable_sku AS sku, SUM(consumable_sku_qty) AS ord, ANY_VALUE(consumable_uom) AS ouom
      FROM `{proj}.{dset}.{potbl}`
      WHERE order_type = 'Purchase' AND consumable_sku IS NOT NULL
        AND CONCAT(po, '~~', consumable_sku) IN UNNEST(@keys)
      GROUP BY po, sku)
    SELECT po, sku, r.recv AS recv, r.ruom AS ruom, o.ord AS ord, o.ouom AS ouom
    FROM received r FULL OUTER JOIN ordered o USING (po, sku)
    """
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("keys", "STRING", keys)])
    out = {}
    for row in ds.client.query(sql, job_config=cfg).result():
        out[(row.po, row.sku)] = {"recv": row.recv, "ruom": row.ruom, "ord": row.ord, "ouom": row.ouom}
    return out
