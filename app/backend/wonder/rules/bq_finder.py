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
         ANY_VALUE(facility) AS facility, ANY_VALUE(system) AS system, ANY_VALUE(item_name) AS item_name
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


_FINDERS = {"PO-03": _over_receipt}


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
