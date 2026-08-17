"""BigQuery rule finders — push the rule logic into SQL and return ONLY offending rows.

At 187M-row ledger / 18.8M-row PO scale we can't fetch tables into Python, so the
bigquery data path uses these SQL finders instead of the in-Python engine. Every query
is capped via maximum_bytes_billed so a misfire can never run up a large bill.

Currently implemented: PO-03 over-receipt and PO-01 null-PO-on-receipt both fire on real
data (PO-01 catches Fishbowl/CK1 blank-PO receipts). PO-02 is kept in the catalog but finds
nothing on current data. XFER-01 (transfer order missing) also fires on real data, scoped to
exclude the synthetic Digital Transfer Warehouse facility (see _build_transfer_order_missing_sql).
XFER-02 (SKU not on the transfer order) is joined on ims_sku, not consumable_sku — see
_build_sku_not_on_to_sql for why that matters. XFER-05 (received SKU not on the transfer order)
needs a different join still (exact-or-suffixed ims_sku) — see _build_received_sku_not_on_to_sql.
"""
from typing import List, Tuple

from .engine import Finding
from ..config import settings
from .. import reference

MAX_GB = 60               # backfill scans more history; daily stays tiny
RESULT_CAP = 500          # per-band ticket cap for a daily run (touched-set is normally far smaller)
BACKFILL_CAP = 500         # per-band cap for the go-live backfill — high enough to capture the full 7-day backlog
RECEIPT_LOOKBACK_DAYS = 30   # daily: how far back to sum cumulative received for a touched PO
BACKFILL_LOOKBACK_DAYS = 7   # go-live baseline: sweep the last 7 days for the existing backlog
XFER_AGING_LOOKBACK_DAYS = 30  # XFER-04/07: only consider TOs created/picked within this window

# Over-receipt — refined per Jonny Li (data analyst, final SQL sign-off): a TWO-WAY match keyed on
# ims_sku (the raw system id sent to BOTH tables), not the translated consumable_sku.
#   order join : ledger.ref_order_id  ->  PO `po`
#   item link  : ims_sku (both tables)   [was consumable_sku — a translation that fanned one order
#                                          across rows and ~2.5x'd the false-positive count: 109 -> ~34]
#   LAYER 1 (PO's own books): PO.received_qty vs PO.ims_sku_qty — packaging units (cs/pk/ea), one
#            table, fully populated, no conversion. This is the "PO receipt" primary signal.
#   LAYER 2 (ledger cumulative): SUM(ledger.consumable_quantity_change) vs PO.consumable_sku_qty —
#            BASE units (oz/lb/g). Base is the only reliable cross-system ledger measure:
#            consumable_quantity_change is 100% populated, ledger.ims_quantity_change is ALSO stored
#            in the base unit (so it does NOT line up with PO.ims_sku_qty's packaging unit), and
#            ledger.supplier_quantity_change is NULL for Pantry (the biggest receiving flow).
#   Flag if EITHER layer is over the threshold (a two-way match): the PO's books may look clean while
#   the ledger over-books, or vice-versa. Each layer compares like-unit-to-like-unit within itself.
# Two run modes:
#   daily    — flag only POs that RECEIVED on the run-date partition, cumulative received vs ordered
#   backfill — flag ALL over-received POs across history (the one-time initial catch-up)


def _build_sql(backfill: bool, lookback: int, high: float, cap: int, urgent: float = 0.50) -> str:
    proj, dset = settings.gcp_project, settings.bq_dataset
    led, po = settings.bq_ledger_table, settings.bq_po_table
    # Per-receipt event stream (the same rows the daily/backfill modes already scan) carrying a
    # running cumulative received qty per (po, ims_sku) — so we can pinpoint the BREACH date: the
    # receipt at which the ledger cumulative first crossed the ordered threshold = when the error
    # truly began. (daily restricts to POs touched on the run-date; backfill sweeps the window.)
    join = (f"""
  JOIN (SELECT DISTINCT ref_order_id AS po, ims_sku FROM `{proj}.{dset}.{led}`
        WHERE ref_order_type = 'Purchase Order' AND ims_sku IS NOT NULL
          AND DATE(datetime_utc) = @run_date) t
    ON l.ref_order_id = t.po AND l.ims_sku = t.ims_sku""" if not backfill else "")
    evt = f"""evt AS (
  SELECT l.ref_order_id AS po, l.ims_sku, l.consumable_sku, l.datetime_utc,
         l.ims_quantity_change AS q, l.consumable_uom AS ruom,   -- Layer 2 received = IMS qty (per Jonny: consumable qty over-flagged)
         l.facility_name AS facility, l.facility_type AS facility_type,
         l.system_of_origin AS system, l.item_name AS item_name,
         l.l1_action AS l1_action, l.l2_action AS l2_action,
         SUM(l.consumable_quantity_change) OVER (
           PARTITION BY l.ref_order_id, l.ims_sku ORDER BY l.datetime_utc
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_recv,
         -- how many 'Add' receipts share this exact quantity (>=2 = probable double-booking).
         -- Partition key CAST to STRING — BigQuery can't PARTITION BY a FLOAT64.
         SUM(IF(l.l1_action = 'Add' AND l.consumable_quantity_change > 0, 1, 0)) OVER (
           PARTITION BY l.ref_order_id, l.ims_sku, CAST(ROUND(l.consumable_quantity_change, 4) AS STRING)) AS same_qty_receipts
  FROM `{proj}.{dset}.{led}` l{join}
  -- ref_order_type='Purchase Order' INTENTIONALLY captures EVERY ledger line tied to the PO,
  -- positive and negative, so SUM(q) below is a true NET. A receiver may double-log / over-log
  -- a receipt and then a correction is booked back against the same PO — either an auto negative
  -- receipt (l1/l2 = Remove/PO Receipt) or a manual fix (Adjust/Update Received Order). Both are
  -- ref_order_type='Purchase Order', so they net out here. Do NOT narrow this to l1_action='Add'
  -- or l2_action LIKE '%Receipt%' — that would drop the manual corrections and re-break netting.
  -- (Corrections booked as generic Adjust/Cycle-Count carry NO PO ref and are deliberately left
  -- alone: they can't be attributed to a specific PO without a fuzzy SKU+facility+window guess.)
  WHERE l.ref_order_type = 'Purchase Order' AND l.ims_sku IS NOT NULL
    AND DATE(l.datetime_utc) <= @run_date
    AND l.datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY))"""
    # Rank within each band (genuine over_frac<=1 vs implausible >1) so the cap keeps BOTH
    # populations represented instead of the most-extreme corrupt rows crowding out genuine ones.
    return "WITH " + evt + f""",
received AS (   -- LAYER 2 basis: net ledger receipts per (po, ims_sku), BASE units
  SELECT po, ims_sku, SUM(q) AS led_received, ANY_VALUE(ruom) AS received_uom,
         ANY_VALUE(consumable_sku) AS consumable_sku,
         ANY_VALUE(facility) AS facility, ANY_VALUE(facility_type) AS facility_type,
         ANY_VALUE(system) AS system, ANY_VALUE(item_name) AS item_name,
         -- movement action of the largest receipt = the dominant receiving event (l1 / l2)
         ANY_VALUE(l1_action HAVING MAX q) AS move_l1, ANY_VALUE(l2_action HAVING MAX q) AS move_l2,
         MAX(same_qty_receipts) AS dup_receipts   -- >=2 = ledger booked the same receipt twice
  FROM evt GROUP BY po, ims_sku),
ordered AS (   -- ordered in BOTH units + the PO's OWN received_qty (LAYER 1), per (po, ims_sku)
  SELECT po, ims_sku,
         SUM(ims_sku_qty)          AS ordered_pkg,    -- packaging units (cs/pk/ea) — Layer 1 basis
         SUM(consumable_sku_qty)   AS ordered_base,    -- base units (oz/lb/g)       — Layer 2 basis
         SUM(received_qty)         AS po_received,     -- the PO's own cumulative received (packaging)
         ANY_VALUE(consumable_uom) AS ordered_uom, ANY_VALUE(ims_uom) AS ims_uom,
         ANY_VALUE(supplier_name)  AS supplier, ANY_VALUE(status) AS status
  FROM `{proj}.{dset}.{po}`
  WHERE ims_sku IS NOT NULL AND order_type = 'Purchase'   -- PO-side: purchases only (for now)
  GROUP BY po, ims_sku),
breach AS (
  SELECT e.po, e.ims_sku,
         -- first receipt where the ledger cumulative (base) crossed the over-receipt threshold
         DATE(MIN(IF(e.running_recv > o.ordered_base * (1 + {high}), e.datetime_utc, NULL))) AS over_breach_date,
         -- first receipt that introduced a unit different from the order's
         DATE(MIN(IF(o.ordered_uom IS NOT NULL AND e.ruom IS NOT NULL AND e.ruom != o.ordered_uom,
                     e.datetime_utc, NULL))) AS uom_breach_date,
         DATE(MIN(e.datetime_utc)) AS first_receipt_date,
         DATE(MAX(e.datetime_utc)) AS last_receipt_date
  FROM evt e JOIN ordered o USING (po, ims_sku)
  GROUP BY po, ims_sku),
flagged AS (   -- TWO-WAY match: keep a row if the PO's own books OR the ledger cumulative are over
  SELECT r.po, r.ims_sku, r.consumable_sku, r.item_name,
         o.ordered_pkg, o.ordered_base, o.po_received, r.led_received,
         o.ordered_uom, r.received_uom, o.ims_uom,
         r.facility, r.facility_type, r.system, o.supplier, o.status, r.move_l1, r.move_l2, r.dup_receipts,
         (o.ordered_pkg  > 0 AND o.po_received  > o.ordered_pkg  * (1 + {high})) AS po_over,
         (o.ordered_base > 0 AND r.led_received > o.ordered_base * (1 + {high})) AS led_over,
         SAFE_DIVIDE(o.po_received,  NULLIF(o.ordered_pkg, 0))  - 1 AS po_over_frac,
         SAFE_DIVIDE(r.led_received, NULLIF(o.ordered_base, 0)) - 1 AS led_over_frac,
         GREATEST(IFNULL(SAFE_DIVIDE(o.po_received,  NULLIF(o.ordered_pkg, 0))  - 1, -9),
                  IFNULL(SAFE_DIVIDE(r.led_received, NULLIF(o.ordered_base, 0)) - 1, -9)) AS over_frac,
         (o.ordered_uom IS NOT NULL AND r.received_uom IS NOT NULL AND o.ordered_uom != r.received_uom) AS uom_mismatch,
         b.over_breach_date, b.uom_breach_date, b.first_receipt_date, b.last_receipt_date
  FROM received r JOIN ordered o USING (po, ims_sku)
                  JOIN breach b USING (po, ims_sku)
  WHERE (o.ordered_pkg > 0 OR o.ordered_base > 0) AND (
        (o.ordered_uom IS NOT NULL AND r.received_uom IS NOT NULL AND o.ordered_uom != r.received_uom)
        OR (o.ordered_pkg  > 0 AND o.po_received  > o.ordered_pkg  * (1 + {high}))
        OR (o.ordered_base > 0 AND r.led_received > o.ordered_base * (1 + {high}))
  )
),
-- Rank within each band (High 30-99% vs Urgent >=100%) so the per-band cap keeps BOTH
-- populations represented instead of the most-extreme rows crowding out the mid-band ones. A pure
-- UoM mismatch (neither layer over — the over% isn't comparable) gets its own band.
ranked AS (
  SELECT *, COUNT(*) OVER() AS total_matches,
         ROW_NUMBER() OVER (
           PARTITION BY (CASE WHEN uom_mismatch AND NOT (po_over OR led_over) THEN 'uom'
                              WHEN over_frac >= {urgent} THEN 'over_urgent'  -- >=100% over (>=2x ordered): likely error (Urgent)
                              ELSE 'over_high' END)                         -- 30-99% over: supply-chain signal (High)
           ORDER BY over_frac DESC) AS rn
  FROM flagged
)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap}
ORDER BY over_frac DESC"""


def _d(v):
    return str(v) if v else None


def _pct(frac):
    return round(frac * 100, 1) if frac is not None else None


def _layer_str(recv, ordered, uom, pct):
    """One-line human summary of a layer: 'received 27540 of 1620 ea (+1600.0% over)'."""
    if recv is None or ordered is None:
        return None
    u = (" " + uom) if uom else ""
    tail = "" if pct is None else ("  (%+.1f%% over)" % pct)
    return "received %s of %s%s ordered%s" % (recv, ordered, u, tail)


def _snap(r, high):
    po_pct, led_pct = _pct(r.po_over_frac), _pct(r.led_over_frac)
    po_over, led_over = bool(r.po_over), bool(r.led_over)
    dup = int(getattr(r, "dup_receipts", 0) or 0)
    ledger_error = led_over and not po_over   # PO receipt looks right; the ledger is the one over
    # Two-way-match verdict (which signal(s) tripped) — the headline of a refined PO-03 ticket.
    if po_over and led_over:
        match = "Confirmed by both the PO's own receipts and the ledger cumulative."
    elif led_over:
        match = ("PO receipt appears correct (matched the order); the ledger over-counted — likely a "
                 "duplicate or erroneous ledger entry. Investigate the ledger, not the receiving.")
        if dup >= 2:
            match += " %d identical receipts detected (probable double-booking)." % dup
    elif po_over:
        match = "The PO's own received_qty is over-ordered; the ledger cumulative is within range."
    else:
        match = "Unit-of-measure mismatch — the received unit differs from the ordered unit."
    # Headline = the tripped layer (prefer the ledger cumulative — it's the fuller, cross-system
    # signal and always carries a base unit). Ledger side is base units; PO-books side is packaging.
    if led_over or not po_over:
        ordered_qty, received_qty, ouom, ruom, over_pct = (
            r.ordered_base, r.led_received, r.ordered_uom, r.received_uom, led_pct)
        cross = {"po_receipts_check": _layer_str(r.po_received, r.ordered_pkg, r.ims_uom, po_pct)}
    else:
        ordered_qty, received_qty, ouom, ruom, over_pct = (
            r.ordered_pkg, r.po_received, r.ims_uom, r.ims_uom, po_pct)
        cross = {"ledger_check": _layer_str(r.led_received, r.ordered_base, r.ordered_uom, led_pct)}
    s = {
        "po": r.po, "consumable_sku": r.consumable_sku, "ims_sku": r.ims_sku, "item_name": r.item_name,
        "match": match,
        "ordered_qty": ordered_qty, "ordered_uom": ouom,
        "received_qty": received_qty, "received_uom": ruom,
        "uom_match": (r.ordered_uom == r.received_uom),
        "over_by_pct": over_pct, "tolerance_pct": round(high * 100, 1),
        "status": r.status, "supplier": r.supplier,
        "facility": r.facility or "—", "facility_type": r.facility_type, "system": r.system or "—",
        # inventory movement (ledger l1 / l2 of the receiving event) — drives the dashboard breakout
        "movement": ("%s / %s" % (r.move_l1, r.move_l2)) if getattr(r, "move_l1", None) else None,
        # data-derived timeline: when the error actually began vs. last activity
        "first_receipt": _d(r.first_receipt_date), "last_receipt": _d(r.last_receipt_date),
    }
    s.update(cross)
    if ledger_error:   # machine flag for dashboard grouping (routing unchanged — stays Field Ops)
        s["likely_ledger_error"] = True
    return s


def _over_receipt(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """PO_OVER_RECEIPT — TWO-WAY match (PO's own received_qty AND the ledger cumulative), keyed on
    ims_sku. 30-99% over → High, >=100% over (>=2× ordered) → Urgent. Routed by facility_type at
    assignment time (HDR → Field Ops/IKC, CK/DISH/PRODUCTION → Field Ops/ProdCo). A pure UoM mismatch
    (neither layer over — the overage % isn't comparable) splits off as PO_UOM_MISMATCH."""
    bq = ds._bq
    high = settings.over_receipt_high_pct
    urgent = settings.over_receipt_urgent_pct
    src = settings.bq_ledger_table
    lookback = BACKFILL_LOOKBACK_DAYS if backfill else RECEIPT_LOOKBACK_DAYS
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    sql = _build_sql(backfill, lookback, high, cap, urgent)
    cfg = bq.QueryJobConfig(
        maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
        query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)],
    )
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        ek = f"{r.po}:{r.ims_sku}"
        s = _snap(r, high)
        po_over, led_over = bool(r.po_over), bool(r.led_over)
        if not (po_over or led_over):  # pure UoM mismatch → over-receipt % is not comparable
            # the error began at the first receipt in the conflicting unit
            s["breached_at"] = _d(r.uom_breach_date) or s["first_receipt"] or s["last_receipt"]
            findings.append(Finding("PO-03", "PO_UOM_MISMATCH", "High", src, ek, s))
        else:
            over = r.over_frac or 0.0
            s["breached_at"] = _d(r.over_breach_date) or s["last_receipt"]
            # severity by magnitude: 30-99% over -> High, >=100% over (>=2x ordered) -> Urgent
            sev = "Urgent" if over >= urgent else "High"
            if over >= 1:  # received >=2x ordered — surface a note in the ticket body
                s["implausible_quantity"] = True
            findings.append(Finding("PO-03", "PO_OVER_RECEIPT", sev, src, ek, s))
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
        out[(row.po, row.sku)] = {"missing": (row.price is None or row.price == 0), "price": row.price}
    return out


def _build_no_receipt_overdue_sql(cap: int, overdue_days: int, lookback_days: int = 0) -> str:
    """PO-07: a Purchase PO with NOTHING received against it (SUM(received_qty)=0 across ALL its lines)
    that still has an OPEN line more than `overdue_days` past its expected receipt date — i.e. it's
    still awaiting receipt and hasn't been cancelled/closed. Aggregated to PO grain (one finding per
    PO). 'Nothing received' is judged over the whole PO, so a partially-received PO is NOT flagged
    (that's framework PO-08); the open/overdue test uses the still-OPEN lines. State-based: returns the
    current open-overdue backlog each run (dedup prevents re-tickets; the recheck auto-closes once a
    receipt lands or Supply Chain cancels/closes it). Only the cap differs between daily and backfill;
    ordered oldest-expected first so the most overdue surface within the cap."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    # Optional recency floor: only POs whose expected receipt date is within the last `lookback_days`
    # (keeps the rule on recently-overdue POs, not the full historical backlog). 0 = no floor.
    window = (f"\n    AND expected_date >= DATE_SUB(@run_date, INTERVAL {lookback_days} DAY)"
              if lookback_days and lookback_days > 0 else "")
    return f"""WITH po_agg AS (
  SELECT po,
         ANY_VALUE(destination_name) AS facility,
         ANY_VALUE(destination_id)   AS facility_id,
         ANY_VALUE(supplier_name)    AS supplier_name,
         ANY_VALUE(po_source_system) AS system,
         MIN(po_date_utc)            AS po_date_utc,
         SUM(COALESCE(received_qty, 0)) AS total_received,          -- across ALL lines of the PO
         LOGICAL_OR(UPPER(status) = 'OPEN') AS has_open_line,       -- still awaiting receipt somewhere
         STRING_AGG(DISTINCT status, ', ') AS po_status,            -- the actual PO line status(es)
         COUNT(*) AS line_count,
         -- schedule + ordered qty measured on the OPEN (unreceived) lines only
         MAX(IF(UPPER(status) = 'OPEN', expected_date, NULL)) AS expected_date,
         SUM(IF(UPPER(status) = 'OPEN', COALESCE(consumable_sku_qty, 0), 0)) AS total_ordered,
         COUNTIF(UPPER(status) = 'OPEN') AS open_line_count
  FROM `{proj}.{dset}.{po}`
  WHERE order_type = 'Purchase' AND po IS NOT NULL AND TRIM(po) <> ''
  GROUP BY po),
flagged AS (
  SELECT *,
         DATE_ADD(expected_date, INTERVAL {overdue_days} DAY) AS breach_date,
         DATE_DIFF(@run_date, expected_date, DAY)             AS days_overdue
  FROM po_agg
  WHERE total_received = 0              -- nothing received on the whole PO
    AND has_open_line                  -- still open / not cancelled or closed out
    AND expected_date IS NOT NULL
    AND expected_date < DATE_SUB(@run_date, INTERVAL {overdue_days} DAY){window}),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches,
                  ROW_NUMBER() OVER (ORDER BY expected_date ASC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap} ORDER BY expected_date ASC"""


def _no_receipt_overdue(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """PO_NO_RECEIPT_OVERDUE (Medium, Procurement) — framework PO-07. Open Purchase PO past its
    expected receipt date by settings.po_no_receipt_overdue_days with nothing received and not
    cancelled. One finding per PO; entity_key = PO number."""
    bq = ds._bq
    src = settings.bq_po_table
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    days = settings.po_no_receipt_overdue_days
    sql = _build_no_receipt_overdue_sql(cap, days, settings.po_no_receipt_overdue_lookback_days)
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        snap = {
            "po": r.po, "facility": r.facility or "—",
            "supplier_name": r.supplier_name, "system": r.system,
            "po_status": r.po_status,                                   # e.g. "Open" — still awaiting receipt, not cancelled
            "expected_date": r.expected_date.isoformat() if r.expected_date else None,
            "days_overdue": r.days_overdue, "overdue_days_threshold": days,
            "ordered_qty": r.total_ordered, "received_qty": 0,
            "open_lines": r.open_line_count, "line_count": r.line_count,
            "breached_at": r.breach_date.isoformat() if r.breach_date else run_date,
        }
        if r.facility_id:
            snap["facility_id"] = r.facility_id
        if r.po_date_utc:
            snap["po_date_utc"] = str(r.po_date_utc)
        findings.append(Finding("PO-07", "PO_NO_RECEIPT_OVERDUE", "Medium", src, r.po, snap))
    return findings, total


def recheck_no_receipt_overdue(ds, pos):
    """For each open PO-07 ticket's PO, whether it now PASSES: a receipt has landed, or Supply Chain
    has cancelled/closed it (no longer OPEN). Returns {po: {"received", "open", "cancelled"}}."""
    keys = [p for p in pos if p]
    if not keys:
        return {}
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    sql = f"""SELECT po,
       SUM(COALESCE(received_qty, 0)) AS total_received,
       LOGICAL_OR(UPPER(status) = 'OPEN') AS still_open,
       LOGICAL_OR(UPPER(status) IN ('CANCELLED', 'CANCELED', 'VOIDED')) AS cancelled
    FROM `{proj}.{dset}.{po}`
    WHERE order_type = 'Purchase' AND po IN UNNEST(@pos)
    GROUP BY po"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("pos", "STRING", keys)])
    return {r.po: {"received": r.total_received, "open": bool(r.still_open), "cancelled": bool(r.cancelled)}
            for r in ds.client.query(sql, job_config=cfg).result()}


# Statuses that mean Supply Chain has finished with the PO (nothing left to close out).
_PO_CLOSED_STATES = "('CLOSED', 'COMPLETED', 'CANCELLED', 'CANCELED', 'VOIDED')"


def _build_partial_not_closed_sql(cap: int, overdue_days: int, lookback_days: int = 0) -> str:
    """PO-08: a Purchase PO that received SOMETHING but less than ordered (short by even 1) and is more
    than `overdue_days` past its expected receipt date while still not closed by Supply Chain.
    Aggregated to PO grain: total received vs total ordered are summed over ALL lines; ordered is taken
    in SUPPLIER units (received_qty tracks supplier_sku_qty). 'Not closed' = the PO still has at least
    one line in a non-terminal status. The expected/overdue test uses the non-closed lines' schedule.
    State-based (dedup + recheck handle re-tickets / auto-close); only the cap differs daily vs
    backfill; ordered oldest-expected first so the most overdue surface within the cap."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    window = (f"\n    AND expected_date >= DATE_SUB(@run_date, INTERVAL {lookback_days} DAY)"
              if lookback_days and lookback_days > 0 else "")
    return f"""WITH po_agg AS (
  SELECT po,
         ANY_VALUE(destination_name) AS facility,
         ANY_VALUE(destination_id)   AS facility_id,
         ANY_VALUE(supplier_name)    AS supplier_name,
         ANY_VALUE(po_source_system) AS system,
         MIN(po_date_utc)            AS po_date_utc,
         SUM(COALESCE(received_qty, 0))     AS total_received,   -- supplier units, across ALL lines
         SUM(COALESCE(supplier_sku_qty, 0)) AS total_ordered,   -- supplier units, across ALL lines
         LOGICAL_OR(UPPER(status) NOT IN {_PO_CLOSED_STATES}) AS not_closed,  -- still open somewhere
         STRING_AGG(DISTINCT status, ', ') AS po_status,
         COUNT(*) AS line_count,
         -- schedule measured on the not-yet-closed lines (the outstanding balance)
         MAX(IF(UPPER(status) NOT IN {_PO_CLOSED_STATES}, expected_date, NULL)) AS expected_date,
         COUNTIF(UPPER(status) NOT IN {_PO_CLOSED_STATES}) AS open_line_count
  FROM `{proj}.{dset}.{po}`
  WHERE order_type = 'Purchase' AND po IS NOT NULL AND TRIM(po) <> ''
  GROUP BY po),
flagged AS (
  SELECT *,
         total_ordered - total_received AS shortfall_qty,
         DATE_ADD(expected_date, INTERVAL {overdue_days} DAY) AS breach_date,
         DATE_DIFF(@run_date, expected_date, DAY)             AS days_overdue
  FROM po_agg
  WHERE total_received > 0                       -- received something
    AND total_received < total_ordered - 0.001   -- but under-received (short by even 1)
    AND not_closed                               -- not closed by Supply Chain
    AND expected_date IS NOT NULL
    AND expected_date < DATE_SUB(@run_date, INTERVAL {overdue_days} DAY){window}),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches,
                  ROW_NUMBER() OVER (ORDER BY expected_date ASC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap} ORDER BY expected_date ASC"""


def _partial_not_closed(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """PO_PARTIAL_NOT_CLOSED (Medium, Procurement) — framework PO-08. Under-received Purchase PO
    (received > 0, short by even 1) still not closed past expected + N days. One finding per PO."""
    bq = ds._bq
    src = settings.bq_po_table
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    days = settings.po_partial_not_closed_days
    sql = _build_partial_not_closed_sql(cap, days, settings.po_partial_not_closed_lookback_days)
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        snap = {
            "po": r.po, "facility": r.facility or "—",
            "supplier_name": r.supplier_name, "system": r.system,
            "po_status": r.po_status,                                   # e.g. "Open, Closed" — partly received, not closed
            "expected_date": r.expected_date.isoformat() if r.expected_date else None,
            "days_overdue": r.days_overdue, "overdue_days_threshold": days,
            "ordered_qty": r.total_ordered, "received_qty": r.total_received,
            "shortfall_qty": r.shortfall_qty,
            "open_lines": r.open_line_count, "line_count": r.line_count,
            "breached_at": r.breach_date.isoformat() if r.breach_date else run_date,
        }
        if r.facility_id:
            snap["facility_id"] = r.facility_id
        if r.po_date_utc:
            snap["po_date_utc"] = str(r.po_date_utc)
        findings.append(Finding("PO-08", "PO_PARTIAL_NOT_CLOSED", "Medium", src, r.po, snap))
    return findings, total


def recheck_partial_not_closed(ds, pos):
    """For each open PO-08 ticket's PO, whether it now PASSES: fully received, or Supply Chain closed
    it (no longer any non-terminal line). Returns {po: {"received", "ordered", "not_closed"}}."""
    keys = [p for p in pos if p]
    if not keys:
        return {}
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    sql = f"""SELECT po,
       SUM(COALESCE(received_qty, 0)) AS total_received,
       SUM(COALESCE(supplier_sku_qty, 0)) AS total_ordered,
       LOGICAL_OR(UPPER(status) NOT IN {_PO_CLOSED_STATES}) AS not_closed
    FROM `{proj}.{dset}.{po}`
    WHERE order_type = 'Purchase' AND po IN UNNEST(@pos)
    GROUP BY po"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("pos", "STRING", keys)])
    return {r.po: {"received": r.total_received, "ordered": r.total_ordered, "not_closed": bool(r.not_closed)}
            for r in ds.client.query(sql, job_config=cfg).result()}


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


def _build_null_po_ledger_sql(backfill: bool, lookback: int, cap: int) -> str:
    """PO-01: a PO-receipt ledger row carrying no PO number (ref_order_id is NULL/blank) — so the
    receipt can't be matched to what was ordered. Identify the receipt by its movement ACTION, not by
    ref_order_type: on exactly these degraded rows ref_order_type is itself blank (Fishbowl/CK1
    receipts land with both ref_order_type and ref_order_id NULL), so keying on
    ref_order_type='Purchase Order' misses every one of them. Two receipt actions exist across
    systems: 'PO Receipt' (Fishbowl/Extensiv/Shiphero/RMX) and 'Received' (Pantry). We match all
    'PO Receipt' rows, but scope 'Received' to system_of_origin='Pantry' — a *different* source
    ('System') also emits 'Received' for negative-qty depletion/reversal entries that are ~never
    PO-linked (2/437 over 90d), so an unscoped 'Received' would flood the Urgent queue with noise.
    Ledger sibling of PO-13 (PO master table)."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    led = settings.bq_ledger_table
    date_filter = ("AND DATE(datetime_utc) = @run_date" if not backfill else
                   f"AND DATE(datetime_utc) <= @run_date "
                   f"AND datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY)")
    return f"""WITH flagged AS (
  SELECT CAST(id AS STRING) AS id, ANY_VALUE(facility_name) AS facility,
         ANY_VALUE(system_of_origin) AS system, ANY_VALUE(consumable_sku) AS consumable_sku,
         ANY_VALUE(item_name) AS item_name, ANY_VALUE(l1_action) AS l1_action,
         ANY_VALUE(l2_action) AS l2_action, ANY_VALUE(ref_order_type) AS ref_order_type,
         MIN(datetime_utc) AS datetime_utc
  FROM `{proj}.{dset}.{led}`
  WHERE (l2_action = 'PO Receipt' OR (l2_action = 'Received' AND system_of_origin = 'Pantry'))
    AND (ref_order_id IS NULL OR TRIM(ref_order_id) = '') {date_filter}
  GROUP BY id),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY datetime_utc DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap} ORDER BY datetime_utc DESC"""


def _null_po_ledger(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """NULL_PO_NUMBER (Urgent, SC Product (IMS)) — a PO-receipt ledger row with no PO number."""
    bq = ds._bq
    src = settings.bq_ledger_table
    lookback = BACKFILL_LOOKBACK_DAYS if backfill else RECEIPT_LOOKBACK_DAYS
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    sql = _build_null_po_ledger_sql(backfill, lookback, cap)
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        snap = {
            "ledger_id": r.id, "ref_order_type": r.ref_order_type, "ref_order_id": None,
            "consumable_sku": r.consumable_sku, "item_name": r.item_name,
            "facility": r.facility or "—", "system": r.system or "—",
            "movement": ("%s / %s" % (r.l1_action, r.l2_action)) if r.l1_action else None,
            "datetime_utc": str(r.datetime_utc) if r.datetime_utc else None,
            "breached_at": (r.datetime_utc.date().isoformat() if r.datetime_utc else run_date),
        }
        findings.append(Finding("PO-01", "NULL_PO_NUMBER", "Urgent", src, r.id, snap))
    return findings, total


def recheck_null_po_ledger(ds, ids):
    """Whether each open PO-01 ticket's ledger row still has a null/blank PO number — close once
    a PO number has been populated on that row."""
    if not ids:
        return {}
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    led = settings.bq_ledger_table
    sql = f"""SELECT CAST(id AS STRING) AS id, MAX(IF(ref_order_id IS NULL OR TRIM(ref_order_id) = '', 1, 0)) AS still_null
    FROM `{proj}.{dset}.{led}` WHERE CAST(id AS STRING) IN UNNEST(@ids) GROUP BY id"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("ids", "STRING", [str(i) for i in ids])])
    return {r.id: {"missing": bool(r.still_null)} for r in ds.client.query(sql, job_config=cfg).result()}


def _build_correction_missing_ref_sql(lookback_days: int, cap: int) -> str:
    """PO-11: a ledger 'Correction' transaction (l1_action LIKE '%correct%') with a NULL/blank
    correction_ref_id — a correcting entry that doesn't point at what it fixes. Ledger-row grain
    (entity = ledger id). Scans only the last `lookback_days` days of events (recency window; keeps
    the initial run small). State-based: dedup prevents re-tickets, the recheck auto-closes once the
    ref id is populated. Newest-first, capped."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    led = settings.bq_ledger_table
    return f"""WITH flagged AS (
  SELECT CAST(id AS STRING) AS id, ANY_VALUE(facility_name) AS facility,
         ANY_VALUE(facility_type) AS facility_type, ANY_VALUE(system_of_origin) AS system,
         ANY_VALUE(consumable_sku) AS consumable_sku, ANY_VALUE(item_name) AS item_name,
         ANY_VALUE(l1_action) AS l1_action, ANY_VALUE(l2_action) AS l2_action,
         ANY_VALUE(ref_order_type) AS ref_order_type, ANY_VALUE(ref_order_id) AS ref_order_id,
         MIN(datetime_utc) AS datetime_utc
  FROM `{proj}.{dset}.{led}`
  WHERE LOWER(l1_action) LIKE '%correct%'
    AND (correction_ref_id IS NULL OR TRIM(correction_ref_id) = '')
    AND DATE(datetime_utc) <= @run_date
    AND DATE(datetime_utc) > DATE_SUB(@run_date, INTERVAL {lookback_days} DAY)   -- last N days incl. run_date
  GROUP BY id),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches,
                  ROW_NUMBER() OVER (ORDER BY datetime_utc DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap} ORDER BY datetime_utc DESC"""


def _correction_missing_ref(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """CORRECTION_MISSING_REF (High, SC Product (IMS)) — framework PO-11. A ledger correction with no
    correction_ref_id. One finding per ledger row (entity_key = ledger id)."""
    bq = ds._bq
    src = settings.bq_ledger_table
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    lookback = settings.po_correction_missing_ref_lookback_days
    sql = _build_correction_missing_ref_sql(lookback, cap)
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        snap = {
            "ledger_id": r.id, "l1_action": r.l1_action, "l2_action": r.l2_action,
            "correction_ref_id": None,
            "consumable_sku": r.consumable_sku, "item_name": r.item_name,
            "facility": r.facility or "—", "facility_type": r.facility_type, "system": r.system or "—",
            "ref_order_type": r.ref_order_type, "ref_order_id": r.ref_order_id,
            "occurred_at": str(r.datetime_utc) if r.datetime_utc else None,
            "breached_at": (r.datetime_utc.date().isoformat() if r.datetime_utc else run_date),
        }
        findings.append(Finding("PO-11", "CORRECTION_MISSING_REF", "High", src, r.id, snap))
    return findings, total


def recheck_correction_missing_ref(ds, ids):
    """Whether each open PO-11 ticket's ledger row still lacks a correction_ref_id — close once set."""
    if not ids:
        return {}
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    led = settings.bq_ledger_table
    sql = f"""SELECT CAST(id AS STRING) AS id,
       MAX(IF(correction_ref_id IS NULL OR TRIM(correction_ref_id) = '', 1, 0)) AS still_null
    FROM `{proj}.{dset}.{led}` WHERE CAST(id AS STRING) IN UNNEST(@ids) GROUP BY id"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("ids", "STRING", [str(i) for i in ids])])
    return {r.id: {"missing": bool(r.still_null)} for r in ds.client.query(sql, job_config=cfg).result()}


def _build_missing_uom_conversion_sql(backfill: bool, lookback: int, cap: int) -> str:
    """PO-06: a purchased Wonder-family item whose Consumable SKU <> Vendor SKU can't be resolved to a
    unit conversion in the supply-chain catalog (wonder_products). Two failure modes, both surfaced:
      - no catalog record for the consumable at all (missing_record=TRUE), or
      - the consumable IS in the catalog but the PO's vendor SKU isn't among its linked vendor SKUs
        (missing_record=FALSE) — so there's no packaging/conversion path from that vendor's pack to the
        consumable base unit.
    Join key: PO.consumable_sku = catalog.hdr_product_sku; the catalog's conversion factors are keyed to
    its vendor_product_skus / priority_vendor_product_sku. (PO.wonder_sku is a different ID namespace
    than catalog.wonder_product_sku, so it is NOT a join key.) Scoped to Wonder-family items
    (ims_sku_type WSKU/Pack SKU, or a 40xxxxx consumable) where supplier_uom != consumable_uom — a
    conversion is only needed when the units differ. One row per (consumable_sku, supplier_sku). Daily
    flags items purchased on the run-date; backfill sweeps the lookback window. Age anchors to the first
    in-scope PO date."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    cat = f"{proj}.{settings.bq_catalog_dataset}.{settings.bq_products_table}"
    date_filter = ("AND DATE(po_date_utc) = @run_date" if not backfill else
                   f"AND DATE(po_date_utc) <= @run_date "
                   f"AND po_date_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY)")
    return f"""WITH cat AS (   -- one row per Wonder product; join key hdr_product_sku = PO consumable_sku
  SELECT hdr_product_sku AS hdr,
         ARRAY_CONCAT_AGG(vendor_product_skus) AS vendors,          -- all linked vendor SKUs
         ARRAY_AGG(DISTINCT priority_vendor_product_sku IGNORE NULLS) AS pvendors,
         ANY_VALUE(wonder_product_name) AS product_name
  FROM `{cat}`
  WHERE status = 'ACTIVE' AND hdr_product_sku IS NOT NULL
  GROUP BY hdr_product_sku),
po AS (   -- Wonder-family purchase lines in scope, collapsed to one row per (consumable, vendor)
  SELECT consumable_sku, supplier_sku,
         ANY_VALUE(consumable_uom) AS consumable_uom, ANY_VALUE(supplier_uom) AS supplier_uom,
         ANY_VALUE(supplier_name) AS supplier_name, ANY_VALUE(destination_name) AS facility,
         ANY_VALUE(po_source_system) AS system, ANY_VALUE(ims_sku_type) AS sku_type,
         ANY_VALUE(wonder_sku) AS wonder_sku, ANY_VALUE(po) AS sample_po, COUNT(DISTINCT po) AS po_count,
         MIN(po_date_utc) AS first_po_date, MAX(po_date_utc) AS last_po_date
  FROM `{proj}.{dset}.{po}`
  WHERE order_type = 'Purchase' AND consumable_sku IS NOT NULL AND supplier_sku IS NOT NULL
    AND (ims_sku_type IN ('WSKU','Pack SKU') OR REGEXP_CONTAINS(consumable_sku, r'^40[0-9]{{5}}$'))
    AND NOT REGEXP_CONTAINS(consumable_sku, r'^9[0-9]{{6}}$')  -- exclude 9xxxxxx smallwares/packaging (Uline/Ed Don) — never in the food catalog
    AND consumable_uom != supplier_uom            -- a conversion is genuinely required
    {date_filter}
  GROUP BY consumable_sku, supplier_sku),
flagged AS (
  SELECT p.*, c.product_name, (c.hdr IS NULL) AS missing_record
  FROM po p LEFT JOIN cat c ON p.consumable_sku = c.hdr
  WHERE c.hdr IS NULL                                                     -- no catalog record at all
     OR NOT (p.supplier_sku IN UNNEST(c.vendors)                         -- or vendor SKU not linked
             OR p.supplier_sku IN UNNEST(c.pvendors))),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches,
                  ROW_NUMBER() OVER (ORDER BY last_po_date DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap} ORDER BY last_po_date DESC"""


def _missing_uom_conversion(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """PO_MISSING_UOM_CONVERSION (Urgent, Procurement) — framework PO-06. A purchased Wonder-family item
    whose Consumable SKU <> Vendor SKU has no unit conversion in the supply-chain catalog. One finding
    per (consumable_sku, supplier_sku); entity_key = 'consumable_sku:supplier_sku'."""
    bq = ds._bq
    src = settings.bq_po_table
    lookback = settings.po_missing_uom_conversion_lookback_days if backfill else RECEIPT_LOOKBACK_DAYS
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    sql = _build_missing_uom_conversion_sql(backfill, lookback, cap)
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        ek = f"{r.consumable_sku}:{r.supplier_sku}"
        gap = ("No catalog record for this consumable SKU" if r.missing_record
               else "Vendor SKU not linked to this consumable in the catalog")
        snap = {
            "consumable_sku": r.consumable_sku, "wonder_sku": r.wonder_sku, "supplier_sku": r.supplier_sku,
            "item_name": r.product_name, "sku_type": r.sku_type,
            "consumable_uom": r.consumable_uom, "supplier_uom": r.supplier_uom,
            "supplier_name": r.supplier_name, "facility": r.facility or "—", "system": r.system or "—",
            "missing_record": bool(r.missing_record), "gap": gap,
            "po_count": r.po_count, "sample_po": r.sample_po,
            "first_po_date": str(r.first_po_date) if r.first_po_date else None,
            "breached_at": (r.first_po_date.date().isoformat() if r.first_po_date else run_date),
        }
        findings.append(Finding("PO-06", "PO_MISSING_UOM_CONVERSION", "Urgent", src, ek, snap))
    return findings, total


def recheck_missing_uom_conversion(ds, pairs):
    """For each open PO-06 ticket's (consumable_sku, supplier_sku), whether the catalog NOW resolves it
    (a record exists AND the vendor SKU is linked) — those can be auto-closed. Returns
    {(consumable_sku, supplier_sku): {"resolved": bool}}."""
    if not pairs:
        return {}
    bq = ds._bq
    proj = settings.gcp_project
    cat = f"{proj}.{settings.bq_catalog_dataset}.{settings.bq_products_table}"
    keys = ["%s~~%s" % (c, s) for (c, s) in pairs if c is not None and s is not None]
    if not keys:
        return {}
    sql = f"""WITH cat AS (
      SELECT hdr_product_sku AS hdr,
             ARRAY_CONCAT_AGG(vendor_product_skus) AS vendors,
             ARRAY_AGG(DISTINCT priority_vendor_product_sku IGNORE NULLS) AS pvendors
      FROM `{cat}` WHERE status='ACTIVE' AND hdr_product_sku IS NOT NULL GROUP BY hdr_product_sku),
    keys AS (SELECT SPLIT(k, '~~')[OFFSET(0)] AS consumable_sku, SPLIT(k, '~~')[SAFE_OFFSET(1)] AS supplier_sku
             FROM UNNEST(@keys) k)
    SELECT k.consumable_sku, k.supplier_sku,
           (c.hdr IS NOT NULL AND (k.supplier_sku IN UNNEST(c.vendors)
                                   OR k.supplier_sku IN UNNEST(c.pvendors))) AS resolved
    FROM keys k LEFT JOIN cat c ON k.consumable_sku = c.hdr"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("keys", "STRING", keys)])
    return {(r.consumable_sku, r.supplier_sku): {"resolved": bool(r.resolved)}
            for r in ds.client.query(sql, job_config=cfg).result()}


def _build_sku_not_on_po_sql(backfill: bool, lookback: int, cap: int) -> str:
    """PO-14 (catalog PO-02): a consumable_sku received against an existing PO with NO ordered
    quantity for that SKU — either the SKU isn't on the PO's lines at all, or it IS on a line but
    the ordered qty is 0 (COALESCE(SUM(consumable_sku_qty),0) <= 0). Per Jonny Li: Ship Hero can
    auto-create a zero-order receive-line when an unexpected item arrives, so we may never invoice
    the vendor — so 'received against a zero-order line' must flag alongside 'not on the PO'.
    Ledger-sourced, so it carries the receiving l1/l2 movement."""
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
po_lines AS (SELECT po, consumable_sku, SUM(consumable_sku_qty) AS ordered_qty,
                    ANY_VALUE(consumable_uom) AS ordered_uom
             FROM `{proj}.{dset}.{po}`
             WHERE order_type = 'Purchase' AND consumable_sku IS NOT NULL
             GROUP BY po, consumable_sku),
po_exists AS (SELECT po, ANY_VALUE(supplier_name) AS supplier FROM `{proj}.{dset}.{po}`
              WHERE order_type = 'Purchase' GROUP BY po),
flagged AS (
  SELECT l.*, pe.supplier, pl.ordered_qty, pl.ordered_uom,
         (pl.consumable_sku IS NOT NULL) AS on_po
  FROM led l JOIN po_exists pe USING (po)
  LEFT JOIN po_lines pl ON l.po = pl.po AND l.consumable_sku = pl.consumable_sku
  WHERE COALESCE(pl.ordered_qty, 0) <= 0),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches,
                  ROW_NUMBER() OVER (ORDER BY last_receipt_date DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap} ORDER BY last_receipt_date DESC"""


def _sku_not_on_po(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """PO_SKU_NOT_ON_PO (High, SC Product (IMS)) — received SKU with no ordered qty on the matching
    PO: either not on the PO's lines, or on a line ordered for 0 (Ship Hero zero-order receive-line)."""
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
            "supplier_name": r.supplier, "on_po": bool(r.on_po),
            "received_qty": r.received_qty, "received_uom": r.ruom,
            "facility": r.facility or "—", "system": r.system or "—",
            "movement": ("%s / %s" % (r.move_l1, r.move_l2)) if r.move_l1 else None,
            "first_receipt": _d(r.first_receipt_date), "last_receipt": _d(r.last_receipt_date),
            "breached_at": _d(r.first_receipt_date),  # first received against the PO with nothing ordered
        }
        # When the SKU IS on the PO but ordered for 0, surface the ordered qty so the ticket makes the
        # "received against a zero-order line" case explicit (drives the vendor-invoice check).
        if r.on_po:
            snap["ordered_qty"] = r.ordered_qty if r.ordered_qty is not None else 0
            snap["ordered_uom"] = r.ordered_uom
        findings.append(Finding("PO-14", "PO_SKU_NOT_ON_PO", "High", src, ek, snap))
    return findings, total


def recheck_sku_on_po(ds, pairs):
    """Which (po, consumable_sku) tickets are NOW genuinely ordered on the PO (ordered qty > 0) —
    those can be auto-closed. Requires a POSITIVE ordered qty, not just a line: a zero-order line is
    the very thing PO-14 flags, so its mere presence must not close the ticket."""
    if not pairs:
        return set()
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    keys = ["%s~~%s" % (p, s) for (p, s) in pairs if p is not None and s is not None]
    if not keys:
        return set()
    sql = f"""SELECT CONCAT(po, '~~', consumable_sku) AS key
    FROM `{proj}.{dset}.{po}`
    WHERE order_type = 'Purchase' AND CONCAT(po, '~~', consumable_sku) IN UNNEST(@keys)
    GROUP BY po, consumable_sku
    HAVING SUM(consumable_sku_qty) > 0"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("keys", "STRING", keys)])
    return {r.key for r in ds.client.query(sql, job_config=cfg).result()}


def _build_transfer_order_missing_sql(backfill: bool, lookback: int, cap: int) -> str:
    """XFER-01: a Transfer Out pick references a Transfer Order id not in the transfer-order
    population (orders table, order_type='Transfer'). One row per orphan transfer order.

    Excludes the synthetic "Digital Transfer Warehouse" facility (system_of_origin=
    'digital_transfer_warehouse', facility_type='In-Transit'): its Transfer Out rows use
    freetext ad hoc labels (e.g. "Instacart", "Sesame general", "BRFC - <date>") for
    digital-channel/recount movements that never get a master transfer-order record, so
    every one of them would otherwise false-positive as an orphan (verified live: ~80% of
    daily hits before this exclusion, 0 genuine defects). Confirmed live 2026-08-13 — see
    PROCESS.md.
    """
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
  WHERE ref_order_type='Transfer Order' AND l2_action='Transfer Out' AND ref_order_id IS NOT NULL
    AND system_of_origin != 'digital_transfer_warehouse' {date_filter}
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


def _build_sku_not_on_to_sql(backfill: bool, lookback: int, cap: int) -> str:
    """XFER-02: an item picked (Transfer Out) against a Transfer Order that EXISTS, but the TO
    orders none of that item — either it isn't on the TO's lines at all, or it's on a line ordered
    for 0. Excludes Digital Transfer Warehouse (see _build_transfer_order_missing_sql) and TOs that
    don't exist at all (that's XFER-01's job, not this one's).

    Joined on ims_sku, NOT consumable_sku: verified live that consumable_sku is a per-system
    translation that doesn't line up 1:1 between the ledger and the PO/TO table for the same item —
    keying on it produced a ~72% false-positive rate (14,679/20,228 picks on one sample day).
    ims_sku is the raw id shared by both tables and matches cleanly (0 false positives on the same
    day). This is the same lesson as PO-03's ims_sku re-key — see docs/rule-sql-guide.md."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    led, po = settings.bq_ledger_table, settings.bq_po_table
    date_filter = ("AND DATE(datetime_utc) = @run_date" if not backfill else
                   f"AND DATE(datetime_utc) <= @run_date "
                   f"AND datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY)")
    return f"""WITH picks AS (
  SELECT ref_order_id AS to_id, ims_sku,
         ANY_VALUE(consumable_sku) AS consumable_sku, ANY_VALUE(item_name) AS item_name,
         ANY_VALUE(facility_name) AS facility, ANY_VALUE(system_of_origin) AS system,
         SUM(consumable_quantity_change) AS net_qty,
         DATE(MIN(datetime_utc)) AS first_seen, DATE(MAX(datetime_utc)) AS last_seen,
         ANY_VALUE(l1_action) AS move_l1, ANY_VALUE(l2_action) AS move_l2
  FROM `{proj}.{dset}.{led}`
  WHERE ref_order_type='Transfer Order' AND l2_action='Transfer Out' AND ref_order_id IS NOT NULL
    AND ims_sku IS NOT NULL AND system_of_origin != 'digital_transfer_warehouse' {date_filter}
  GROUP BY to_id, ims_sku),
to_lines AS (SELECT po, ims_sku, SUM(consumable_sku_qty) AS ordered_qty
             FROM `{proj}.{dset}.{po}` WHERE order_type='Transfer' AND ims_sku IS NOT NULL
             GROUP BY po, ims_sku),
to_exists AS (SELECT DISTINCT po FROM `{proj}.{dset}.{po}` WHERE order_type='Transfer'),
flagged AS (
  SELECT p.*, (l.ims_sku IS NOT NULL) AS on_to, l.ordered_qty
  FROM picks p JOIN to_exists e ON p.to_id = e.po
  LEFT JOIN to_lines l ON p.to_id = l.po AND p.ims_sku = l.ims_sku
  WHERE COALESCE(l.ordered_qty, 0) <= 0),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY last_seen DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap} ORDER BY last_seen DESC"""


def _sku_not_on_to(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """SKU_NOT_ON_TO (High, Field Ops) — picked against a real Transfer Order that orders none of
    this item: not on the TO's lines, or on a line ordered for 0."""
    bq = ds._bq
    src = settings.bq_ledger_table
    lookback = BACKFILL_LOOKBACK_DAYS if backfill else RECEIPT_LOOKBACK_DAYS
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    sql = _build_sku_not_on_to_sql(backfill, lookback, cap)
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        ek = f"{r.to_id}:{r.ims_sku}"
        snap = {
            "transfer_order": r.to_id, "ims_sku": r.ims_sku, "consumable_sku": r.consumable_sku,
            "item_name": r.item_name, "on_transfer_order": bool(r.on_to),
            "net_qty_change": r.net_qty, "facility": r.facility or "—", "system": r.system or "—",
            "movement": ("%s / %s" % (r.move_l1, r.move_l2)) if r.move_l1 else None,
            "first_receipt": _d(r.first_seen), "last_receipt": _d(r.last_seen),
            "breached_at": _d(r.first_seen),
        }
        if r.on_to:
            snap["ordered_qty"] = r.ordered_qty if r.ordered_qty is not None else 0
        findings.append(Finding("XFER-02", "SKU_NOT_ON_TO", "High", src, ek, snap))
    return findings, total


def recheck_sku_on_to(ds, pairs):
    """Which (transfer_order, ims_sku) tickets are NOW genuinely ordered on the TO (ordered qty
    > 0) — those can be auto-closed. Requires a POSITIVE ordered qty; a zero-order line is the very
    thing this rule flags, so its mere presence must not close the ticket."""
    if not pairs:
        return set()
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    keys = ["%s~~%s" % (t, s) for (t, s) in pairs if t is not None and s is not None]
    if not keys:
        return set()
    sql = f"""SELECT CONCAT(po, '~~', ims_sku) AS key
    FROM `{proj}.{dset}.{po}`
    WHERE order_type = 'Transfer' AND CONCAT(po, '~~', ims_sku) IN UNNEST(@keys)
    GROUP BY po, ims_sku
    HAVING SUM(consumable_sku_qty) > 0"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("keys", "STRING", keys)])
    return {r.key for r in ds.client.query(sql, job_config=cfg).result()}


def _build_received_sku_not_on_to_sql(backfill: bool, lookback: int, cap: int) -> str:
    """XFER-05: an item RECEIVED (Transfer In, or Received-at-Pantry/HDR) against a Transfer Order
    that EXISTS, but the TO orders none of that item. The receiving-side sibling of XFER-02.

    Join predicate is `l.ims_sku = p.ims_sku OR l.ims_sku LIKE CONCAT(p.ims_sku, '-%')`, NOT a plain
    ims_sku match and NOT a stripped-suffix match. Verified live: a meaningful slice of TO lines
    (827k/22.48M, concentrated in Pantry/HDR frozen "F" items) carry a "-N" case-multiplier suffix
    on ims_sku (e.g. line ims_sku "4200584F-2" for a bare ledger ims_sku "4200584F") that the
    receiving leg reports without. Without this, EVERY HDR selling unit false-positived at a
    15-70% rate on live data. But blindly stripping the suffix on the TO side (GROUP BY the base
    sku) also broke the picking side (XFER-02): it merges genuinely distinct suffixed lines into
    one bucket and introduced 67,755 new false orphans on a 30-day picking-side test. The
    exact-OR-prefix join fixes receiving (0 false positives, same as stripping) without merging
    anything, and is a no-op on the picking side (still 0/512,802 on the same 30-day window) —
    so it's the correct predicate for this direction; XFER-02 doesn't need it and wasn't changed."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    led, po = settings.bq_ledger_table, settings.bq_po_table
    date_filter = ("AND DATE(datetime_utc) = @run_date" if not backfill else
                   f"AND DATE(datetime_utc) <= @run_date "
                   f"AND datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY)")
    return f"""WITH picks AS (
  SELECT ref_order_id AS to_id, ims_sku,
         ANY_VALUE(consumable_sku) AS consumable_sku, ANY_VALUE(item_name) AS item_name,
         ANY_VALUE(facility_name) AS facility, ANY_VALUE(system_of_origin) AS system,
         SUM(consumable_quantity_change) AS net_qty,
         DATE(MIN(datetime_utc)) AS first_seen, DATE(MAX(datetime_utc)) AS last_seen,
         ANY_VALUE(l1_action) AS move_l1, ANY_VALUE(l2_action) AS move_l2
  FROM `{proj}.{dset}.{led}`
  WHERE ref_order_type='Transfer Order' AND l2_action IN ('Transfer In','Received') AND ref_order_id IS NOT NULL
    AND ims_sku IS NOT NULL AND system_of_origin != 'digital_transfer_warehouse' {date_filter}
  GROUP BY to_id, ims_sku),
to_exists AS (SELECT DISTINCT po FROM `{proj}.{dset}.{po}` WHERE order_type='Transfer'),
joined AS (
  SELECT p.to_id, p.ims_sku, p.consumable_sku, p.item_name, p.facility, p.system, p.net_qty,
         p.first_seen, p.last_seen, p.move_l1, p.move_l2, l.consumable_sku_qty
  FROM picks p JOIN to_exists e ON p.to_id = e.po
  LEFT JOIN `{proj}.{dset}.{po}` l ON l.po = p.to_id AND l.order_type='Transfer'
    AND (l.ims_sku = p.ims_sku OR l.ims_sku LIKE CONCAT(p.ims_sku, '-%'))),
agg AS (
  SELECT to_id, ims_sku, ANY_VALUE(consumable_sku) AS consumable_sku, ANY_VALUE(item_name) AS item_name,
         ANY_VALUE(facility) AS facility, ANY_VALUE(system) AS system, ANY_VALUE(net_qty) AS net_qty,
         ANY_VALUE(first_seen) AS first_seen, ANY_VALUE(last_seen) AS last_seen,
         ANY_VALUE(move_l1) AS move_l1, ANY_VALUE(move_l2) AS move_l2,
         SUM(consumable_sku_qty) AS ordered_qty, LOGICAL_OR(consumable_sku_qty IS NOT NULL) AS on_to
  FROM joined GROUP BY to_id, ims_sku),
flagged AS (SELECT * FROM agg WHERE COALESCE(ordered_qty, 0) <= 0),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY last_seen DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap} ORDER BY last_seen DESC"""


def _received_sku_not_on_to(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """RECEIVED_SKU_NOT_ON_TO (High, SC Product (IMS)) — received (Transfer In / Received) against
    a real Transfer Order that orders none of this item: not on the TO's lines, or on a line
    ordered for 0."""
    bq = ds._bq
    src = settings.bq_ledger_table
    lookback = BACKFILL_LOOKBACK_DAYS if backfill else RECEIPT_LOOKBACK_DAYS
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    sql = _build_received_sku_not_on_to_sql(backfill, lookback, cap)
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        ek = f"{r.to_id}:{r.ims_sku}"
        snap = {
            "transfer_order": r.to_id, "ims_sku": r.ims_sku, "consumable_sku": r.consumable_sku,
            "item_name": r.item_name, "on_transfer_order": bool(r.on_to),
            "net_qty_change": r.net_qty, "facility": r.facility or "—", "system": r.system or "—",
            "movement": ("%s / %s" % (r.move_l1, r.move_l2)) if r.move_l1 else None,
            "first_receipt": _d(r.first_seen), "last_receipt": _d(r.last_seen),
            "breached_at": _d(r.first_seen),
        }
        if r.on_to:
            snap["ordered_qty"] = r.ordered_qty if r.ordered_qty is not None else 0
        findings.append(Finding("XFER-05", "RECEIVED_SKU_NOT_ON_TO", "High", src, ek, snap))
    return findings, total


def recheck_received_sku_on_to(ds, pairs):
    """Which (transfer_order, ims_sku) receiving tickets are NOW genuinely ordered on the TO
    (ordered qty > 0, exact-or-suffixed ims_sku match) — those can be auto-closed."""
    if not pairs:
        return set()
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    po = settings.bq_po_table
    pairs = [(t, s) for (t, s) in pairs if t is not None and s is not None]
    if not pairs:
        return set()
    to_ids = list({t for t, _ in pairs})
    sql = f"""SELECT po, ims_sku, SUM(consumable_sku_qty) AS ordered_qty
    FROM `{proj}.{dset}.{po}`
    WHERE order_type = 'Transfer' AND po IN UNNEST(@to_ids)
    GROUP BY po, ims_sku
    HAVING SUM(consumable_sku_qty) > 0"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("to_ids", "STRING", to_ids)])
    lines = list(ds.client.query(sql, job_config=cfg).result())
    resolved = set()
    for (to_id, ims_sku) in pairs:
        for r in lines:
            if r.po == to_id and (r.ims_sku == ims_sku or r.ims_sku.startswith(ims_sku + "-")):
                resolved.add("%s~~%s" % (to_id, ims_sku))
                break
    return resolved


# Statuses that mean a Transfer Order has already moved past "waiting to be picked" — treated as
# already-picked even with zero matching ledger rows (see _build_no_pick_activity_sql docstring for
# why ledger presence alone false-positives ~94% of the time). Terminal/dead statuses are excluded
# from consideration entirely (not "no pick activity", just not a candidate either way).
_TO_ALREADY_PICKED_STATUSES = ("SHIPPED", "PARTIALLY_SHIPPED", "RECEIVED", "PARTIALLY_RECEIVED",
                               "CLOSED", "PICKED", "PACKED", "PACKING", "PLACED")
_TO_DEAD_STATUSES = ("CANCELLED", "CANCELED", "VOIDED", "VENDOR_REJECTED")
_TO_EXCLUDED_STATUSES = _TO_ALREADY_PICKED_STATUSES + _TO_DEAD_STATUSES


def _build_no_pick_activity_sql(cap: int, no_pick_days: int, lookback_days: int = 30) -> str:
    """XFER-04: a Transfer Order still in an early lifecycle status with ZERO Transfer Out ledger
    activity more than `no_pick_days` after it was created.

    Ledger presence alone is NOT reliable: verified live that ~94% of TOs with zero matching
    Transfer-Out rows are already status=CLOSED or RECEIVED — a real gap in what syncs into
    consolidated_inventory_ledger for a meaningful slice of transfers (one example, PO-431527,
    status CLOSED, has ZERO rows in the ledger under any action, ever — not a join-key formatting
    issue like the ims_sku cases, a genuine feed-coverage gap). So a TO counts as already-picked if
    EITHER a ledger Transfer Out row exists OR its own status has advanced past picking
    (_TO_ALREADY_PICKED_STATUSES); dead orders (_TO_DEAD_STATUSES) are excluded entirely. With that
    filter, live volume is a believable ~10/day (current backlog: 150 over a 30-day window)."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    led, po = settings.bq_ledger_table, settings.bq_po_table
    excluded = ",".join("'%s'" % s for s in _TO_EXCLUDED_STATUSES)
    window = (f"\n    AND t.order_date >= DATE_SUB(@run_date, INTERVAL {lookback_days} DAY)"
              if lookback_days and lookback_days > 0 else "")
    return f"""WITH to_agg AS (
  SELECT po, MAX(DATE(po_date_utc)) AS order_date,
         ARRAY_AGG(DISTINCT status IGNORE NULLS) AS statuses,
         ANY_VALUE(destination_name) AS facility, ANY_VALUE(destination_id) AS facility_id,
         ANY_VALUE(po_source_system) AS system
  FROM `{proj}.{dset}.{po}`
  WHERE order_type='Transfer' AND po IS NOT NULL AND TRIM(po) <> ''
  GROUP BY po),
picked AS (SELECT DISTINCT ref_order_id AS po FROM `{proj}.{dset}.{led}`
  WHERE ref_order_type='Transfer Order' AND l2_action='Transfer Out' AND ref_order_id IS NOT NULL),
flagged AS (
  SELECT t.*, DATE_ADD(t.order_date, INTERVAL {no_pick_days} DAY) AS breach_date,
         DATE_DIFF(@run_date, t.order_date, DAY) AS days_since_order
  FROM to_agg t LEFT JOIN picked p USING(po)
  WHERE p.po IS NULL
    AND NOT EXISTS (SELECT 1 FROM UNNEST(t.statuses) s WHERE UPPER(s) IN ({excluded}))
    AND t.order_date IS NOT NULL
    AND t.order_date < DATE_SUB(@run_date, INTERVAL {no_pick_days} DAY){window}),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY order_date ASC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap} ORDER BY order_date ASC"""


def _no_pick_activity(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """TRANSFER_NO_PICK_ACTIVITY (Medium, Field Ops) — framework XFER-04. Current backlog of
    still-early-status Transfer Orders with no pick activity `no_pick_days` after creation."""
    bq = ds._bq
    src = settings.bq_po_table
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    days = reference.xfer_no_pick_days()
    sql = _build_no_pick_activity_sql(cap, days, XFER_AGING_LOOKBACK_DAYS)
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        snap = {
            "transfer_order": r.po, "facility": r.facility or "—", "system": r.system,
            "to_status": ", ".join(r.statuses) if r.statuses else None,
            "order_date": r.order_date.isoformat() if r.order_date else None,
            "days_since_order": r.days_since_order, "no_pick_days_threshold": days,
            "breached_at": r.breach_date.isoformat() if r.breach_date else run_date,
        }
        if r.facility_id:
            snap["facility_id"] = r.facility_id
        findings.append(Finding("XFER-04", "TRANSFER_NO_PICK_ACTIVITY", "Medium", src, r.po, snap))
    return findings, total


def recheck_no_pick_activity(ds, to_ids):
    """Which transfer orders NOW have pick activity (a ledger Transfer Out row) or a status that's
    advanced past picking — those can be auto-closed."""
    if not to_ids:
        return set()
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    led, po = settings.bq_ledger_table, settings.bq_po_table
    ids = [str(i) for i in to_ids if i is not None]
    if not ids:
        return set()
    excluded = ",".join("'%s'" % s for s in _TO_ALREADY_PICKED_STATUSES)
    sql = f"""WITH picked AS (SELECT DISTINCT ref_order_id AS po FROM `{proj}.{dset}.{led}`
  WHERE ref_order_type='Transfer Order' AND l2_action='Transfer Out' AND ref_order_id IN UNNEST(@ids)),
advanced AS (SELECT DISTINCT po FROM `{proj}.{dset}.{po}`
  WHERE order_type='Transfer' AND po IN UNNEST(@ids) AND UPPER(status) IN ({excluded}))
SELECT po FROM picked UNION DISTINCT SELECT po FROM advanced"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("ids", "STRING", ids)])
    return {r.po for r in ds.client.query(sql, job_config=cfg).result()}


def _build_picked_not_received_sql(cap: int, not_received_days: int, lookback_days: int = 30) -> str:
    """XFER-07: a real Transfer Order (exists in the population) that WAS picked (a Transfer Out
    ledger row exists) but has no Transfer In / Received ledger row more than `not_received_days`
    after the first pick. Excludes cancelled/voided orders. Unlike XFER-04, ledger-only is reliable
    here: verified live that 0 of 76,035 picked, non-cancelled transfer orders in a 90-day window
    lack a matching receiving-leg row."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    led, po = settings.bq_ledger_table, settings.bq_po_table
    window = (f"\n    AND pk.first_pick >= DATE_SUB(@run_date, INTERVAL {lookback_days} DAY)"
              if lookback_days and lookback_days > 0 else "")
    return f"""WITH picked AS (
  SELECT ref_order_id AS po, MIN(DATE(datetime_utc)) AS first_pick,
         ANY_VALUE(facility_name) AS facility, ANY_VALUE(system_of_origin) AS system
  FROM `{proj}.{dset}.{led}`
  WHERE ref_order_type='Transfer Order' AND l2_action='Transfer Out' AND ref_order_id IS NOT NULL
  GROUP BY ref_order_id),
received AS (SELECT DISTINCT ref_order_id AS po FROM `{proj}.{dset}.{led}`
  WHERE ref_order_type='Transfer Order' AND l2_action IN ('Transfer In','Received') AND ref_order_id IS NOT NULL),
to_exists AS (SELECT po, ARRAY_AGG(DISTINCT status IGNORE NULLS) AS statuses
  FROM `{proj}.{dset}.{po}` WHERE order_type='Transfer' GROUP BY po),
flagged AS (
  SELECT pk.*, DATE_ADD(pk.first_pick, INTERVAL {not_received_days} DAY) AS breach_date,
         DATE_DIFF(@run_date, pk.first_pick, DAY) AS days_since_pick
  FROM picked pk JOIN to_exists e USING(po) LEFT JOIN received r USING(po)
  WHERE r.po IS NULL
    AND NOT EXISTS (SELECT 1 FROM UNNEST(e.statuses) s WHERE UPPER(s) IN ('CANCELLED','CANCELED','VOIDED'))
    AND pk.first_pick < DATE_SUB(@run_date, INTERVAL {not_received_days} DAY){window}),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY first_pick ASC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {cap} ORDER BY first_pick ASC"""


def _picked_not_received(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """TRANSFER_PICKED_NOT_RECEIVED (Medium, Field Ops) — framework XFER-07. Current backlog of
    picked Transfer Orders with no receipt `not_received_days` after the first pick."""
    bq = ds._bq
    src = settings.bq_ledger_table
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    days = reference.xfer_not_received_days()
    sql = _build_picked_not_received_sql(cap, days, XFER_AGING_LOOKBACK_DAYS)
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(sql, job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        snap = {
            "transfer_order": r.po, "facility": r.facility or "—", "system": r.system or "—",
            "first_pick": r.first_pick.isoformat() if r.first_pick else None,
            "days_since_pick": r.days_since_pick, "not_received_days_threshold": days,
            "breached_at": r.breach_date.isoformat() if r.breach_date else run_date,
        }
        findings.append(Finding("XFER-07", "TRANSFER_PICKED_NOT_RECEIVED", "Medium", src, r.po, snap))
    return findings, total


def recheck_picked_not_received(ds, to_ids):
    """Which picked transfer orders NOW have a Transfer In / Received ledger row — those can be
    auto-closed."""
    if not to_ids:
        return set()
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    led = settings.bq_ledger_table
    ids = [str(i) for i in to_ids if i is not None]
    if not ids:
        return set()
    sql = f"""SELECT DISTINCT ref_order_id AS po FROM `{proj}.{dset}.{led}`
    WHERE ref_order_type='Transfer Order' AND l2_action IN ('Transfer In','Received')
      AND ref_order_id IN UNNEST(@ids)"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("ids", "STRING", ids)])
    return {r.po for r in ds.client.query(sql, job_config=cfg).result()}


# Daily ADJUSTMENT churn (ADJ_DAILY_FACILITY) + the waste-SKU-without-cost rule still scope to all
# l1='Adjust' activity minus location transfers (Move From/To) and receiving/admin corrections.
# (Daily WASTE no longer uses this — see _waste_combo_sql / reference.waste_action_combos.)
NON_WASTE_ADJUST_L2 = ("Move From", "Move To", "Update Received Order", "Shelf Life Extension")


def _waste_combo_keys() -> list:
    """The editable Daily-Waste allowlist as CONCAT keys ('l1||l2'), bound as the @waste_keys array
    parameter (see _daily_waste_rows) so the values are NEVER interpolated into SQL."""
    return ["%s||%s" % (l1, l2) for (l1, l2) in reference.waste_action_combos()]


def _waste_combo_sql() -> str:
    """SQL predicate selecting ledger rows whose (l1_action, l2_action) is in the editable Daily-Waste
    allowlist (reference.waste_action_combos; Pavel-approved defaults, DB-overridable in Admin). The
    pairs are matched via CONCAT-key against the @waste_keys array parameter (bound in _daily_waste_rows)
    — user-editable values are parameterized, never interpolated, so this is injection-safe. A row with
    a NULL action CONCATs to NULL and is naturally excluded. Empty allowlist -> FALSE (nothing counts
    as waste)."""
    if not reference.waste_action_combos():
        return "FALSE"
    return "CONCAT(l1_action, '||', l2_action) IN UNNEST(@waste_keys)"


def _cost_cte() -> str:
    """SQL CTE `cost` = latest-activated ERP (Dynamics) standard cost per ITEMID (= consumable_sku)
    at the 'control' inventory site. unit_cost = PRICE/PRICEUNIT; cost_uom = UNITID. One row per
    ITEMID. Provided by Pavel (see SCHEMA_NOTES.md); cross-project to settings.erp_project."""
    ep, ed = settings.erp_project, settings.erp_dataset
    return f"""cost AS (
  SELECT ITEMID, AVG(UnitPrice) AS unit_cost, ANY_VALUE(UNITID) AS cost_uom FROM (
    SELECT p.ITEMID, SAFE_DIVIDE(p.PRICE, p.PRICEUNIT) AS UnitPrice, p.UNITID
    FROM `{ep}.{ed}.inventitempriceftistaging` AS p
    INNER JOIN (
      SELECT MAX(price.ActivationDate) AS ActivationDate, MAX(price.CREATEDTIME) AS CREATEDTIME,
             price.ITEMID, price.INVENTDIMID, price.DATAAREAID
      FROM `{ep}.{ed}.inventitempriceftistaging` AS price
      INNER JOIN `{ep}.{ed}.inventdimftistaging` AS dim
        ON dim.INVENTDIMID = price.INVENTDIMID AND LOWER(dim.INVENTDIMDATAAREAID) = LOWER(price.DATAAREAID)
        AND LOWER(dim.INVENTSITEID) = 'control'
      GROUP BY price.ITEMID, price.DATAAREAID, price.INVENTDIMID
    ) m ON m.ITEMID = p.ITEMID AND m.ActivationDate = p.ActivationDate AND m.CREATEDTIME = p.CREATEDTIME
       AND LOWER(m.INVENTDIMID) = LOWER(p.INVENTDIMID) AND LOWER(m.DATAAREAID) = LOWER(p.DATAAREAID))
  GROUP BY ITEMID)"""


def _daily_waste_sql(backfill=False) -> str:
    """The per (facility, facility_type, day) NET waste $ query (parameterized by @run_date). Extracted
    so the finder and the copy-paste reference SQL (doc_sql) share one source of truth — what the app
    runs IS what the Admin SQL box shows."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    led = settings.bq_ledger_table
    lookback = BACKFILL_LOOKBACK_DAYS if backfill else RECEIPT_LOOKBACK_DAYS
    date_filter = ("AND DATE(datetime_utc) = @run_date" if not backfill else
                   f"AND DATE(datetime_utc) <= @run_date "
                   f"AND datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY)")
    return f"""WITH {_cost_cte()},
adj AS (   -- signed net per (facility, sku, day): losses (-) net against Found / recoveries (+)
  SELECT facility_name, facility_type, DATE(datetime_utc) AS day, consumable_sku,
         ANY_VALUE(consumable_uom) AS consumable_uom,
         SUM(consumable_quantity_change) AS net_change
  FROM `{proj}.{dset}.{led}`
  WHERE {_waste_combo_sql()} {date_filter}
  GROUP BY facility_name, facility_type, day, consumable_sku),
costed AS (   -- net lost value per sku (positive = net loss); only valued when cost UoM matches
  SELECT a.facility_name, a.facility_type, a.day, a.consumable_sku, a.net_change,
         -a.net_change * c.unit_cost AS dollars,
         (c.unit_cost IS NOT NULL AND LOWER(c.cost_uom) = LOWER(a.consumable_uom)) AS uom_ok
  FROM adj a LEFT JOIN cost c ON CAST(a.consumable_sku AS STRING) = c.ITEMID)
SELECT facility_name, facility_type, CAST(day AS STRING) AS day,
       ROUND(SUM(IF(uom_ok, dollars, 0)), 0) AS dollars,          -- only UoM-matched items valued
       COUNTIF(uom_ok AND dollars > 0) AS skus,                   -- # net-loss SKUs valued
       COUNTIF(NOT uom_ok AND net_change < 0) AS uom_mismatch_skus,  -- net-loss items we couldn't value
       ARRAY_AGG(IF(uom_ok AND dollars > 0, STRUCT(consumable_sku AS sku, ROUND(dollars, 0) AS d), NULL)
                 IGNORE NULLS ORDER BY IF(uom_ok, dollars, 0) DESC LIMIT 5) AS top,
       ARRAY_AGG(IF(NOT uom_ok AND net_change < 0, consumable_sku, NULL)
                 IGNORE NULLS LIMIT 8) AS mismatch_skus
FROM costed GROUP BY facility_name, facility_type, day
HAVING dollars > 0 ORDER BY dollars DESC"""


def _daily_waste_rows(ds, run_date, backfill=False):
    """Per (facility, facility_type, day) NET waste $ for the run_date (or backfill window), valued
    at the derived consumable-unit cost. NET over the editable waste-action allowlist
    (reference.waste_action_combos — Pavel-approved (l1_action, l2_action) pairs, DB-overridable in
    Admin): losses are negative, Found / cycle-count recoveries positive, so a same-day loss+find of
    an item cancels. waste_dollars > 0 means net lost value. Each row carries the top loss-contributing
    SKUs (sorted). Shared by the dashboard metric + the exception."""
    bq = ds._bq
    params = [bq.ScalarQueryParameter("run_date", "DATE", run_date)]
    keys = _waste_combo_keys()
    if keys:  # only bound when the allowlist is non-empty (else the predicate is a literal FALSE)
        params.append(bq.ArrayQueryParameter("waste_keys", "STRING", keys))
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3), query_parameters=params)
    return list(ds.client.query(_daily_waste_sql(backfill), job_config=cfg).result())


def _top_contributors(top):
    """ARRAY<STRUCT<sku, d>> -> a readable, single-line string for the drawer/ticket."""
    return "; ".join("%s ($%s)" % (t["sku"], "{:,.0f}".format(t["d"] or 0)) for t in (top or []))


def waste_by_location(ds, run_date):
    """Dashboard metric (NOT a ticket): facilities whose daily waste $ is over their facility-type
    High threshold, biggest first."""
    rows = _daily_waste_rows(ds, run_date, backfill=False)
    out = []
    for r in rows:
        th = reference.waste_daily_threshold(r.facility_type)
        if r.dollars > th["high"]:
            out.append({"facility": r.facility_name or "—", "facilityType": r.facility_type,
                        "day": r.day, "dollars": r.dollars, "skus": r.skus,
                        "band": "Urgent" if r.dollars > th["urgent"] else "High"})
    return out


def _daily_waste_facility(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """WASTE_DAILY_FACILITY — a facility's net waste $ for a day over its facility-type threshold.
    Banded High/Urgent; routed by facility_type (Field Ops IKC/ProdCo) at assignment time."""
    src = settings.bq_ledger_table
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    rows = _daily_waste_rows(ds, run_date, backfill=backfill)
    findings, total, per_band = [], 0, {"High": 0, "Urgent": 0}
    for r in rows:
        th = reference.waste_daily_threshold(r.facility_type)
        if r.dollars <= th["high"]:
            continue
        total += 1
        sev = "Urgent" if r.dollars > th["urgent"] else "High"
        if per_band[sev] >= cap:   # cap PER band so both High and Urgent stay represented
            continue
        per_band[sev] += 1
        ek = f"{r.facility_name}:{r.day}"
        snap = {
            "facility": r.facility_name or "—", "facility_type": r.facility_type, "day": r.day,
            "waste_dollars": r.dollars, "sku_count": r.skus,
            "high_threshold": th["high"], "urgent_threshold": th["urgent"],
            "top_contributors": _top_contributors(r.top),
            "breached_at": r.day,
        }
        # UoM mismatch callout: net-loss SKUs whose ERP cost UoM != ledger consumable_uom — NOT
        # valued in the $ above (would be wrong), surfaced so the team can reconcile the conversion.
        if r.uom_mismatch_skus:
            snap["uom_mismatch_count"] = r.uom_mismatch_skus
            shown = list(r.mismatch_skus or [])
            snap["uom_mismatch_note"] = ("%d net-loss SKU(s) not valued — ERP cost UoM ≠ waste UoM (reconcile): %s%s"
                                         % (r.uom_mismatch_skus, ", ".join(shown),
                                            " …" if r.uom_mismatch_skus > len(shown) else ""))
        findings.append(Finding("WASTE-DAILY", "WASTE_DAILY_FACILITY", sev, src, ek, snap))
    return findings, total


def recheck_daily_waste_facility(ds, keys):
    """Current net waste $ for each open (facility, day) ticket — close once back under threshold."""
    if not keys:
        return {}
    want = {"%s~~%s" % (f, d) for (f, d) in keys if f is not None and d is not None}
    days = [d for (_, d) in keys if d]
    if not want or not days:
        return {}
    # day-scoped, so recompute over the backfill window and pick out the wanted facility-days.
    out = {}
    for r in _daily_waste_rows(ds, max(days), backfill=True):
        k = "%s~~%s" % (r.facility_name, r.day)
        if k in want:
            out[k] = {"dollars": r.dollars, "facility_type": r.facility_type}
    return out


# ---- Daily ABSOLUTE adjustments by facility (ADJ_DAILY_FACILITY) ---------------------------------
# Same Adjust activity / cost as daily waste, but the MAGNITUDE: SUM(|per-SKU net x cost|) at the
# facility level instead of the signed net. So a same-day loss + offsetting recovery still counts as
# adjustment churn (waste nets them to ~$0). Per-SKU netting is kept (a same-item loss+find within a
# day is a reversal, not churn). Mirrors _daily_waste_rows so the cost/UoM handling is identical.
def _daily_adjust_sql(backfill=False) -> str:
    """The per (facility, facility_type, day) ABSOLUTE adjustment $ query (parameterized by @run_date).
    Extracted so the finder and the copy-paste reference SQL (doc_sql) share one source of truth."""
    proj, dset = settings.gcp_project, settings.bq_dataset
    led = settings.bq_ledger_table
    excl = ", ".join("'%s'" % w for w in NON_WASTE_ADJUST_L2)
    lookback = BACKFILL_LOOKBACK_DAYS if backfill else RECEIPT_LOOKBACK_DAYS
    date_filter = ("AND DATE(datetime_utc) = @run_date" if not backfill else
                   f"AND DATE(datetime_utc) <= @run_date "
                   f"AND datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY)")
    return f"""WITH {_cost_cte()},
adj AS (   -- per (facility, sku, day): signed net Adjust qty (same grain as waste)
  SELECT facility_name, facility_type, DATE(datetime_utc) AS day, consumable_sku,
         ANY_VALUE(consumable_uom) AS consumable_uom,
         SUM(consumable_quantity_change) AS net_change
  FROM `{proj}.{dset}.{led}`
  WHERE l1_action = 'Adjust' AND l2_action NOT IN ({excl}) {date_filter}
  GROUP BY facility_name, facility_type, day, consumable_sku),
costed AS (   -- absolute adjustment value per sku; only valued when cost UoM matches the ledger UoM
  SELECT a.facility_name, a.facility_type, a.day, a.consumable_sku, a.net_change,
         ABS(a.net_change * c.unit_cost) AS dollars,
         (c.unit_cost IS NOT NULL AND LOWER(c.cost_uom) = LOWER(a.consumable_uom)) AS uom_ok
  FROM adj a LEFT JOIN cost c ON CAST(a.consumable_sku AS STRING) = c.ITEMID)
SELECT facility_name, facility_type, CAST(day AS STRING) AS day,
       ROUND(SUM(IF(uom_ok, dollars, 0)), 0) AS dollars,            -- only UoM-matched items valued
       COUNTIF(uom_ok AND dollars > 0) AS skus,                     -- # adjusted SKUs valued
       COUNTIF(NOT uom_ok AND net_change <> 0) AS uom_mismatch_skus,  -- adjusted items we couldn't value
       ARRAY_AGG(IF(uom_ok AND dollars > 0, STRUCT(consumable_sku AS sku, ROUND(dollars, 0) AS d), NULL)
                 IGNORE NULLS ORDER BY IF(uom_ok, dollars, 0) DESC LIMIT 5) AS top,
       ARRAY_AGG(IF(NOT uom_ok AND net_change <> 0, consumable_sku, NULL)
                 IGNORE NULLS LIMIT 8) AS mismatch_skus
FROM costed GROUP BY facility_name, facility_type, day
HAVING dollars > 0 ORDER BY dollars DESC"""


def _daily_adjust_rows(ds, run_date, backfill=False):
    """Per (facility, facility_type, day) ABSOLUTE adjustment $ for the run_date (or backfill window),
    valued at the derived consumable-unit cost. dollars = SUM over SKUs of |net_change x cost|; only
    UoM-matched SKUs are valued. Each row carries the top contributing SKUs (by absolute $)."""
    bq = ds._bq
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    return list(ds.client.query(_daily_adjust_sql(backfill), job_config=cfg).result())


def _daily_adjust_facility(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """ADJ_DAILY_FACILITY — a facility's absolute adjustment $ for a day over its facility-type
    threshold. Banded High/Urgent; routed by facility_type (Field Ops IKC/ProdCo) at assignment."""
    src = settings.bq_ledger_table
    cap = BACKFILL_CAP if backfill else RESULT_CAP
    rows = _daily_adjust_rows(ds, run_date, backfill=backfill)
    findings, total, per_band = [], 0, {"High": 0, "Urgent": 0}
    for r in rows:
        th = reference.adjust_daily_threshold(r.facility_type)
        if r.dollars <= th["high"]:
            continue
        total += 1
        sev = "Urgent" if r.dollars > th["urgent"] else "High"
        if per_band[sev] >= cap:
            continue
        per_band[sev] += 1
        ek = f"{r.facility_name}:{r.day}"
        snap = {
            "facility": r.facility_name or "—", "facility_type": r.facility_type, "day": r.day,
            "adjust_dollars": r.dollars, "sku_count": r.skus,
            "high_threshold": th["high"], "urgent_threshold": th["urgent"],
            "top_contributors": _top_contributors(r.top),
            "breached_at": r.day,
        }
        if r.uom_mismatch_skus:
            snap["uom_mismatch_count"] = r.uom_mismatch_skus
            shown = list(r.mismatch_skus or [])
            snap["uom_mismatch_note"] = ("%d adjusted SKU(s) not valued — ERP cost UoM ≠ ledger UoM (reconcile): %s%s"
                                         % (r.uom_mismatch_skus, ", ".join(shown),
                                            " …" if r.uom_mismatch_skus > len(shown) else ""))
        findings.append(Finding("ADJ-DAILY", "ADJ_DAILY_FACILITY", sev, src, ek, snap))
    return findings, total


def recheck_daily_adjust_facility(ds, keys):
    """Current absolute adjustment $ for each open (facility, day) ticket — close once back under
    its facility-type High threshold."""
    if not keys:
        return {}
    want = {"%s~~%s" % (f, d) for (f, d) in keys if f is not None and d is not None}
    days = [d for (_, d) in keys if d]
    if not want or not days:
        return {}
    out = {}
    for r in _daily_adjust_rows(ds, max(days), backfill=True):
        k = "%s~~%s" % (r.facility_name, r.day)
        if k in want:
            out[k] = {"dollars": r.dollars, "facility_type": r.facility_type}
    return out


ZERO_COST_TEST_CAP = 5   # CONSUMABLE_ZERO_COST: 600+ backlog; ticket a small sample while testing


def _waste_sku_no_cost_sql(backfill=False) -> str:
    """The waste-active-SKU-without-cost query (parameterized by @run_date). Extracted so the finder
    and the copy-paste reference SQL share one source of truth."""
    proj, dset, led = settings.gcp_project, settings.bq_dataset, settings.bq_ledger_table
    excl = ", ".join("'%s'" % w for w in NON_WASTE_ADJUST_L2)
    lookback = BACKFILL_LOOKBACK_DAYS if backfill else RECEIPT_LOOKBACK_DAYS
    date_filter = ("AND DATE(datetime_utc) = @run_date" if not backfill else
                   f"AND DATE(datetime_utc) <= @run_date "
                   f"AND datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY)")
    return f"""WITH {_cost_cte()},
waste AS (
  SELECT consumable_sku, ANY_VALUE(item_name) AS item_name, ANY_VALUE(consumable_uom) AS consumable_uom,
         ANY_VALUE(facility_name) AS facility, ANY_VALUE(facility_type) AS facility_type,
         ANY_VALUE(system_of_origin) AS system,
         SUM(IF(consumable_quantity_change < 0, -consumable_quantity_change, 0)) AS waste_qty,
         DATE(MIN(datetime_utc)) AS first_seen, DATE(MAX(datetime_utc)) AS last_seen
  FROM `{proj}.{dset}.{led}`
  WHERE l1_action = 'Adjust' AND l2_action NOT IN ({excl}) AND consumable_sku IS NOT NULL {date_filter}
  GROUP BY consumable_sku),
flagged AS (
  SELECT w.* FROM waste w LEFT JOIN cost c ON CAST(w.consumable_sku AS STRING) = c.ITEMID
  WHERE c.ITEMID IS NULL),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY waste_qty DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked ORDER BY waste_qty DESC"""


def _waste_sku_no_cost(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """WASTE_SKU_NO_COST (High, Accounting) — a waste-active consumable_sku with NO ERP standard-cost
    record (no ITEMID match), so its waste can't be valued. Small population — all are ticketed."""
    bq = ds._bq
    src = settings.bq_ledger_table
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(_waste_sku_no_cost_sql(backfill), job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        snap = {
            "consumable_sku": r.consumable_sku, "item_name": r.item_name, "consumable_uom": r.consumable_uom,
            "facility": r.facility or "—", "facility_type": r.facility_type, "system": r.system or "—",
            "waste_qty_window": r.waste_qty, "first_seen": _d(r.first_seen), "last_seen": _d(r.last_seen),
            "why_flagged": ("This consumable SKU has waste/adjustment activity but NO standard-cost record "
                            "in the ERP cost table (no matching ITEMID), so its waste cannot be valued and it "
                            "drops out of the waste $. Fix: set up a standard cost for this item in Dynamics."),
            "breached_at": _d(r.first_seen) or run_date,
        }
        findings.append(Finding("COST-01", "WASTE_SKU_NO_COST", "High", src, r.consumable_sku, snap))
    return findings, total


def _consumable_zero_cost_sql(backfill=False) -> str:
    """The ledger-active-SKU-with-zero/NULL-cost query (parameterized by @run_date). Extracted so the
    finder and the copy-paste reference SQL share one source of truth."""
    proj, dset, led = settings.gcp_project, settings.bq_dataset, settings.bq_ledger_table
    lookback = BACKFILL_LOOKBACK_DAYS if backfill else RECEIPT_LOOKBACK_DAYS
    date_filter = ("AND DATE(datetime_utc) = @run_date" if not backfill else
                   f"AND DATE(datetime_utc) <= @run_date "
                   f"AND datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(@run_date), INTERVAL {lookback} DAY)")
    return f"""WITH {_cost_cte()},
led AS (
  SELECT consumable_sku, ANY_VALUE(item_name) AS item_name, ANY_VALUE(consumable_uom) AS consumable_uom,
         ANY_VALUE(facility_name) AS facility, ANY_VALUE(facility_type) AS facility_type,
         ANY_VALUE(system_of_origin) AS system, DATE(MAX(datetime_utc)) AS last_seen
  FROM `{proj}.{dset}.{led}`
  WHERE consumable_sku IS NOT NULL {date_filter}
  GROUP BY consumable_sku),
flagged AS (
  SELECT l.*, c.unit_cost, c.cost_uom
  FROM led l JOIN cost c ON CAST(l.consumable_sku AS STRING) = c.ITEMID
  WHERE c.unit_cost IS NULL OR c.unit_cost = 0),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY last_seen DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= {ZERO_COST_TEST_CAP} ORDER BY last_seen DESC"""


def _consumable_zero_cost(ds, run_date, backfill=False) -> Tuple[List[Finding], int]:
    """CONSUMABLE_ZERO_COST (High, Accounting) — framework #66. A ledger-active consumable_sku that
    HAS an ERP cost record whose standard cost is 0/NULL. 600+ backlog; ticket a sample (TEST_CAP)."""
    bq = ds._bq
    src = settings.bq_ledger_table
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("run_date", "DATE", run_date)])
    rows = list(ds.client.query(_consumable_zero_cost_sql(backfill), job_config=cfg).result())
    findings, total = [], (rows[0].total_matches if rows else 0)
    for r in rows:
        snap = {
            "consumable_sku": r.consumable_sku, "item_name": r.item_name, "consumable_uom": r.consumable_uom,
            "facility": r.facility or "—", "facility_type": r.facility_type, "system": r.system or "—",
            "standard_unit_cost": (0 if r.unit_cost == 0 else None), "cost_uom": r.cost_uom,
            "last_seen": _d(r.last_seen),
            "why_flagged": ("This consumable SKU is active in the ledger and HAS an ERP standard-cost record, "
                            "but the standard cost is $0.00 / NULL — so waste, on-hand and COGS valuations for "
                            "it are zero/wrong. Fix: correct the standard cost for this item in Dynamics. "
                            "(One of 600+ in the backlog; a sample is ticketed for now.)"),
            "breached_at": run_date,
        }
        findings.append(Finding("COST-02", "CONSUMABLE_ZERO_COST", "High", src, r.consumable_sku, snap))
    return findings, total


def recheck_waste_sku_no_cost(ds, skus):
    """Which of these SKUs NOW have a standard-cost record — {ITEMID: {unit_cost, cost_uom}} for the
    ones that do (auto-closeable); absent = still no cost record. Carries the new cost so the
    resolution can show what the now-costed item is valued at."""
    if not skus:
        return {}
    bq = ds._bq
    ids = [str(s) for s in skus if s is not None]
    if not ids:
        return {}
    sql = f"""WITH {_cost_cte()}
    SELECT ITEMID, unit_cost, cost_uom FROM cost WHERE ITEMID IN UNNEST(@ids)"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("ids", "STRING", ids)])
    return {r.ITEMID: {"unit_cost": r.unit_cost, "cost_uom": r.cost_uom}
            for r in ds.client.query(sql, job_config=cfg).result()}


def recheck_consumable_cost(ds, skus):
    """Current standard cost for these SKUs — {sku: still_zero_or_null bool}. Close once costed."""
    if not skus:
        return {}
    bq = ds._bq
    ids = [str(s) for s in skus if s is not None]
    if not ids:
        return {}
    sql = f"""WITH {_cost_cte()}
    SELECT ITEMID, unit_cost, cost_uom FROM cost WHERE ITEMID IN UNNEST(@ids)"""
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("ids", "STRING", ids)])
    return {r.ITEMID: {"missing": (r.unit_cost is None or r.unit_cost == 0),
                       "unit_cost": r.unit_cost, "cost_uom": r.cost_uom}
            for r in ds.client.query(sql, job_config=cfg).result()}


# ---- Copy-paste reference SQL (Admin → rule editor) ---------------------------------------------
# The exact daily query each SQL-backed rule runs, made standalone: @run_date becomes a DECLARE so
# the whole thing pastes into the BigQuery console and returns the offending rows that become this
# rule's exceptions. Generated from the SAME builders the validator uses, so doc == reality. The
# per-band 500-row cap (RESULT_CAP) the finders apply is reflected where it lives in SQL; for the
# banded daily rules the facility-type threshold (applied in Python) is injected here too, so the
# pasted query returns exactly the flagged facility-days.
_RUN_DATE_DECL = ("DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);"
                  "  -- daily batch target = the just-closed day (yesterday PST in prod)\n\n")


def _standalone(note, body):
    """Prepend the rule note + a run_date DECLARE and bind @run_date so the query runs as-is."""
    return note + _RUN_DATE_DECL + body.replace("@run_date", "run_date")


def _banded_daily_doc(error_type, inner_sql, what):
    """Wrap a daily waste/adjust aggregate (column `dollars`) with the live facility-type threshold so
    the pasted query returns only the flagged facility-days, tagged with the severity band."""
    high = reference.threshold_case_sql(error_type, "t.facility_type", "high")
    urgent = reference.threshold_case_sql(error_type, "t.facility_type", "urgent")
    note = ("-- %s.\n"
            "-- Flagged when the day's $ is above the facility-type HIGH threshold; above the URGENT\n"
            "-- threshold is Urgent, else High. Thresholds are the live Admin values. The app also caps\n"
            "-- each band at %d rows/run (not shown here).\n" % (what, RESULT_CAP))
    body = (f"SELECT t.*, IF(t.dollars > {urgent}, 'Urgent', 'High') AS severity_band,\n"
            f"       {high} AS high_threshold,\n"
            f"       {urgent} AS urgent_threshold\n"
            f"FROM (\n{inner_sql}\n) t\n"
            f"WHERE t.dollars > {high}\n"
            f"ORDER BY t.dollars DESC")
    return _standalone(note, body)


def doc_sql(rule_id):
    """Standalone, copy-paste BigQuery SQL for a SQL-backed rule (the daily query it runs, returning
    the offending rows). None for catalog-only rules with no finder — their reference SQL stays the
    hand-written documentation in reference.RULES."""
    lb, cap = RECEIPT_LOOKBACK_DAYS, RESULT_CAP
    if rule_id == "PO-01":
        return _standalone("-- A PO-order-type receiving row in the ledger with a NULL/blank PO number (safety-net).\n",
                           _build_null_po_ledger_sql(False, lb, cap))
    if rule_id == "PO-03":
        return _standalone(
            "-- PO over-receipt (TWO-WAY match, keyed on ims_sku): flag if the PO's OWN received_qty vs\n"
            "-- ims_sku_qty (Layer 1, packaging units) OR the ledger cumulative vs consumable_sku_qty\n"
            "-- (Layer 2, base units) is over the threshold. Pure UoM-mismatch rows (neither layer over)\n"
            "-- become PO_UOM_MISMATCH; the rest PO_OVER_RECEIPT (over_frac >= %.2f -> Urgent, else High).\n"
            % settings.over_receipt_urgent_pct,
            _build_sql(False, lb, settings.over_receipt_high_pct, cap, settings.over_receipt_urgent_pct))
    if rule_id == "PO-07":
        lbk = settings.po_no_receipt_overdue_lookback_days
        return _standalone(
            "-- Open Purchase PO past expected_date + %d days with nothing received and not cancelled\n"
            "-- (framework PO-07)%s. One row per PO; auto-closes once received or cancelled/closed.\n"
            % (settings.po_no_receipt_overdue_days,
               (", limited to the last %d days" % lbk) if lbk and lbk > 0 else ""),
            _build_no_receipt_overdue_sql(cap, settings.po_no_receipt_overdue_days, lbk))
    if rule_id == "PO-08":
        lbk = settings.po_partial_not_closed_lookback_days
        return _standalone(
            "-- Under-received Purchase PO (received>0 but < ordered) still not closed %d days past\n"
            "-- expected_date (framework PO-08)%s. One row per PO; auto-closes once fully received or closed.\n"
            % (settings.po_partial_not_closed_days,
               (", limited to the last %d days" % lbk) if lbk and lbk > 0 else ""),
            _build_partial_not_closed_sql(cap, settings.po_partial_not_closed_days, lbk))
    if rule_id == "PO-06":
        return _standalone(
            "-- Purchased Wonder-family item whose Consumable SKU <> Vendor SKU has no unit conversion\n"
            "-- in the supply-chain catalog (framework PO-06): no catalog record, or the PO's vendor SKU\n"
            "-- isn't linked. Scoped to items where supplier_uom != consumable_uom (a conversion is\n"
            "-- actually needed). One row per (consumable_sku, supplier_sku); auto-closes once resolved.\n",
            _build_missing_uom_conversion_sql(False, lb, cap))
    if rule_id == "PO-09":
        return _standalone("-- CLOSED Purchase PO lines with a $0/NULL vendor price (can't be costed).\n",
                           _build_price_sql(False, lb, cap))
    if rule_id == "PO-11":
        return _standalone(
            "-- Ledger 'Correction' transaction (l1_action LIKE '%%correct%%') with no correction_ref_id\n"
            "-- (framework PO-11), last %d days. One row per ledger event; auto-closes once the ref is set.\n"
            % settings.po_correction_missing_ref_lookback_days,
            _build_correction_missing_ref_sql(settings.po_correction_missing_ref_lookback_days, cap))
    if rule_id == "PO-13":
        return _standalone("-- Purchase rows in the PO master with a NULL/blank PO number (safety-net).\n",
                           _build_null_po_sql(False, lb, cap))
    if rule_id == "PO-14":
        return _standalone("-- 3-way match: a consumable_sku received against an existing PO with no ordered qty\n"
                           "-- (not on the PO's lines, OR on a line ordered for 0 — a Ship Hero zero-order receive-line).\n",
                           _build_sku_not_on_po_sql(False, lb, cap))
    if rule_id == "XFER-01":
        return _standalone("-- A Transfer Out pick against a Transfer Order id absent from the transfer population.\n",
                           _build_transfer_order_missing_sql(False, lb, cap))
    if rule_id == "XFER-02":
        return _standalone("-- A Transfer Out pick against a real Transfer Order that orders none of this item\n"
                           "-- (not on the TO's lines, OR on a line ordered for 0). Joined on ims_sku.\n",
                           _build_sku_not_on_to_sql(False, lb, cap))
    if rule_id == "XFER-05":
        return _standalone("-- An item received (Transfer In / Received) against a real Transfer Order that\n"
                           "-- orders none of this item. Joined on ims_sku, exact-or-suffixed (see docstring).\n",
                           _build_received_sku_not_on_to_sql(False, lb, cap))
    if rule_id == "XFER-04":
        return _standalone("-- A still-early-status Transfer Order with zero Transfer Out ledger activity\n"
                           "-- more than Y days after creation (also already-picked-per-status is excluded).\n",
                           _build_no_pick_activity_sql(cap, reference.xfer_no_pick_days(), XFER_AGING_LOOKBACK_DAYS))
    if rule_id == "XFER-07":
        return _standalone("-- A picked Transfer Order with no Transfer In / Received ledger row more than\n"
                           "-- Z days after the first pick.\n",
                           _build_picked_not_received_sql(cap, reference.xfer_not_received_days(), XFER_AGING_LOOKBACK_DAYS))
    if rule_id == "WASTE-DAILY":
        return _banded_daily_doc("WASTE_DAILY_FACILITY", _daily_waste_sql(False),
                                 "Daily facility NET waste $ (net over the editable waste-action allowlist, "
                                 "valued at ERP standard cost)")
    if rule_id == "ADJ-DAILY":
        return _banded_daily_doc("ADJ_DAILY_FACILITY", _daily_adjust_sql(False),
                                 "Daily facility ABSOLUTE adjustment $ (SUM of |per-SKU net x cost|)")
    if rule_id == "COST-01":
        return _standalone("-- Waste-active consumable_sku with NO ERP standard-cost record (no ITEMID match).\n",
                           _waste_sku_no_cost_sql(False))
    if rule_id == "COST-02":
        return _standalone("-- Ledger-active consumable_sku whose ERP standard cost is 0/NULL "
                           "(sample of %d of the 600+ backlog).\n" % ZERO_COST_TEST_CAP,
                           _consumable_zero_cost_sql(False))
    return None


_FINDERS = {"PO-01": _null_po_ledger, "PO-03": _over_receipt, "PO-06": _missing_uom_conversion,
            "PO-07": _no_receipt_overdue,
            "PO-08": _partial_not_closed, "PO-09": _missing_price, "PO-11": _correction_missing_ref,
            "PO-13": _null_po,
            "PO-14": _sku_not_on_po, "XFER-01": _transfer_order_missing, "XFER-02": _sku_not_on_to,
            "XFER-05": _received_sku_not_on_to,
            "XFER-04": _no_pick_activity, "XFER-07": _picked_not_received,
            "WASTE-DAILY": _daily_waste_facility, "ADJ-DAILY": _daily_adjust_facility,
            "COST-01": _waste_sku_no_cost, "COST-02": _consumable_zero_cost}


def wired_rule_ids():
    """Rule IDs that have a live SQL finder (i.e. actually run in the daily job and can create
    exceptions). Rules NOT in this set are catalog-only: defined/documented but with no detector
    wired yet, so they produce nothing even when enabled."""
    return set(_FINDERS.keys())


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


def breakdown(ds, po: str, ims_sku: str, system: str = None):
    """The PO line vs the ledger receipt events for one (po, ims_sku) — the 'why it flagged' detail
    shown in the drawer. Keyed on ims_sku to match the finder's grain; quantities shown in the base
    (consumable) unit, so the running balance ties out to the flagged ledger cumulative (Layer 2).
    Cluster-pruned by system_of_origin + a date window so it stays cheap per click."""
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    led, potbl = settings.bq_ledger_table, settings.bq_po_table
    sys_filter = "AND system_of_origin = @sys" if (system and system != "—") else ""
    sql = f"""
    SELECT 'PO' AS source, consumable_sku_qty AS qty, consumable_uom AS uom, order_type,
           CAST(NULL AS STRING) AS l1_action, CAST(NULL AS STRING) AS l2_action, status,
           CAST(NULL AS STRING) AS facility, po_date_utc AS ts
    FROM `{proj}.{dset}.{potbl}` WHERE po = @po AND ims_sku = @sku AND order_type = 'Purchase'
    UNION ALL
    SELECT 'LEDGER', consumable_quantity_change, consumable_uom, CAST(NULL AS STRING),
           l1_action, l2_action, CAST(NULL AS STRING), facility_name, datetime_utc
    FROM `{proj}.{dset}.{led}`
    -- ref_order_type='Purchase Order' = the exact rows the finder nets, so the movement shown here
    -- (positive receipts + negative corrections) sums to the flagged net received_qty. Don't drop it,
    -- or the drawer's running balance won't tie out to the flagged total.
    WHERE ref_order_id = @po AND ims_sku = @sku AND ref_order_type = 'Purchase Order' {sys_filter}
      AND datetime_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {BACKFILL_LOOKBACK_DAYS + 35} DAY)
    ORDER BY (source = 'LEDGER'), ts
    """
    params = [bq.ScalarQueryParameter("po", "STRING", po), bq.ScalarQueryParameter("sku", "STRING", ims_sku)]
    if sys_filter:
        params.append(bq.ScalarQueryParameter("sys", "STRING", system))
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3), query_parameters=params)
    rows = list(ds.client.query(sql, job_config=cfg).result())
    return [{"source": r.source, "qty": r.qty, "uom": r.uom, "order_type": r.order_type, "l1_action": r.l1_action,
             "l2_action": r.l2_action, "status": r.status, "facility": r.facility,
             "ts": str(r.ts) if r.ts else None} for r in rows]


def transfer_breakdown(ds, transfer_order: str):
    """Every ledger movement against one Transfer Order — every Transfer Out ('picked') row
    followed by every Transfer In / Received ('received') row — the 'what went out vs what came
    in' detail shown in the drawer for XFER-family tickets."""
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    led = settings.bq_ledger_table
    sql = f"""
    SELECT
      CASE WHEN l2_action = 'Transfer Out' THEN 'OUT' ELSE 'IN' END AS leg,
      item_name, consumable_sku, ims_sku, consumable_quantity_change AS qty, consumable_uom AS uom,
      facility_name AS facility, system_of_origin AS system, l1_action, l2_action, datetime_utc AS ts
    FROM `{proj}.{dset}.{led}`
    WHERE ref_order_type = 'Transfer Order' AND ref_order_id = @to_id
      AND l2_action IN ('Transfer Out', 'Transfer In', 'Received')
    ORDER BY (l2_action != 'Transfer Out'), datetime_utc ASC
    LIMIT 500
    """
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ScalarQueryParameter("to_id", "STRING", transfer_order)])
    rows = list(ds.client.query(sql, job_config=cfg).result())
    return [{"leg": r.leg, "item_name": r.item_name, "consumable_sku": r.consumable_sku,
             "ims_sku": r.ims_sku, "qty": r.qty, "uom": r.uom, "facility": r.facility,
             "system": r.system, "movement": ("%s / %s" % (r.l1_action, r.l2_action)) if r.l1_action else None,
             "ts": str(r.ts) if r.ts else None} for r in rows]


def recheck(ds, pairs):
    """Current two-way over-receipt state for a set of (po, ims_sku) OPEN tickets, so the job can
    auto-close the ones that no longer fail on EITHER layer. Returns
    {(po, ims_sku): {po_recv, ordered_pkg, led_recv, ordered_base, ruom, ouom}} — Layer 1 (the PO's
    own received_qty vs ims_sku_qty, packaging) and Layer 2 (ledger cumulative vs consumable_sku_qty,
    base). Ledger receipts summed over the lookback window (recent fixes show up; very old POs may
    read as 'no recent receipts' and are left open rather than risk a false close)."""
    if not pairs:
        return {}
    bq = ds._bq
    proj, dset = settings.gcp_project, settings.bq_dataset
    led, potbl = settings.bq_ledger_table, settings.bq_po_table
    keys = ["%s~~%s" % (p, s) for (p, s) in pairs if p is not None and s is not None]
    if not keys:
        return {}
    sql = f"""
    WITH received AS (   -- LAYER 2: net ledger cumulative in base units
      SELECT ref_order_id AS po, ims_sku AS sku, SUM(consumable_quantity_change) AS led_recv,
             ANY_VALUE(consumable_uom) AS ruom
      FROM `{proj}.{dset}.{led}`
      WHERE ref_order_type = 'Purchase Order' AND ims_sku IS NOT NULL
        AND CONCAT(ref_order_id, '~~', ims_sku) IN UNNEST(@keys)
        AND datetime_utc >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {BACKFILL_LOOKBACK_DAYS} DAY)
      GROUP BY po, sku),
    ordered AS (   -- LAYER 1 basis (po_recv vs ordered_pkg) + Layer 2 denominator (ordered_base)
      SELECT po, ims_sku AS sku, SUM(ims_sku_qty) AS ordered_pkg, SUM(consumable_sku_qty) AS ordered_base,
             SUM(received_qty) AS po_recv, ANY_VALUE(consumable_uom) AS ouom
      FROM `{proj}.{dset}.{potbl}`
      WHERE order_type = 'Purchase' AND ims_sku IS NOT NULL
        AND CONCAT(po, '~~', ims_sku) IN UNNEST(@keys)
      GROUP BY po, sku)
    SELECT po, sku, r.led_recv AS led_recv, r.ruom AS ruom,
           o.ordered_pkg AS ordered_pkg, o.ordered_base AS ordered_base, o.po_recv AS po_recv, o.ouom AS ouom
    FROM received r FULL OUTER JOIN ordered o USING (po, sku)
    """
    cfg = bq.QueryJobConfig(maximum_bytes_billed=int(MAX_GB * 1024 ** 3),
                            query_parameters=[bq.ArrayQueryParameter("keys", "STRING", keys)])
    out = {}
    for row in ds.client.query(sql, job_config=cfg).result():
        out[(row.po, row.sku)] = {"po_recv": row.po_recv, "ordered_pkg": row.ordered_pkg,
                                  "led_recv": row.led_recv, "ordered_base": row.ordered_base,
                                  "ruom": row.ruom, "ouom": row.ouom}
    return out
