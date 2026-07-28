"""Build the 'correction applied' record stamped on a ticket when it auto-closes: what the
offending value WAS vs. what it is NOW, so the drawer can show the actual fix + the date it
landed instead of just the stale flagged snapshot. Shared by the live auto-close path
(jobs/validate.py) and the one-time backfill that enriches already-closed tickets
(backfill_resolutions.py). Each builder returns the resolution dict if the entity genuinely
passes now (so the same call decides 'close it' AND 'here's the correction'), else None.
"""
from decimal import Decimal

from ..config import settings
from .. import reference


def _num(v):
    # BigQuery NUMERIC (e.g. ERP standard cost) comes back as Decimal, which the JSON snapshot
    # column can't serialize — coerce to float so the resolution stores/commits cleanly.
    return float(v) if isinstance(v, Decimal) else v


def _res(run_date, summary, fields=None):
    return {"resolved_on": run_date, "summary": summary, "fields": [f for f in (fields or []) if f]}


def _field(label, was, now, unit=None):
    f = {"label": label, "was": _num(was), "now": _num(now)}
    if unit:
        f["unit"] = unit
    return f


def over_receipt(run_date, snap, cur):
    """PO_OVER_RECEIPT family — close only when NEITHER layer of the two-way match is still over and
    the UoMs agree. Layer 1 = the PO's own received_qty vs ims_sku_qty (packaging); Layer 2 = the
    ledger cumulative vs consumable_sku_qty (base)."""
    if not cur:
        return None
    high = settings.over_receipt_high_pct
    po_over = bool(cur.get("ordered_pkg") and cur["ordered_pkg"] > 0
                   and (cur.get("po_recv") or 0) > cur["ordered_pkg"] * (1 + high))
    led_over = bool(cur.get("ordered_base") and cur["ordered_base"] > 0
                    and (cur.get("led_recv") or 0) > cur["ordered_base"] * (1 + high))
    uom_mismatch = bool(cur.get("ouom") and cur.get("ruom") and cur["ouom"] != cur["ruom"])
    # Need at least one ordered side present to judge; if we can't read the current state, stay open.
    if cur.get("ordered_pkg") is None and cur.get("ordered_base") is None:
        return None
    if po_over or led_over or uom_mismatch:
        return None
    ruom = cur.get("ruom") or snap.get("received_uom")
    led_over_pct = (round(((cur.get("led_recv") or 0) / cur["ordered_base"] - 1) * 100, 1)
                    if cur.get("ordered_base") else None)
    return _res(run_date, "Both the PO's own receipts and the ledger cumulative are now within tolerance / UoM reconciled.", [
        _field("received_qty", snap.get("received_qty"), cur.get("led_recv"), ruom),
        _field("over_by_pct", snap.get("over_by_pct"), led_over_pct, "%"),
    ])


def missing_price(run_date, snap, cur):
    if not cur or cur.get("missing"):
        return None
    return _res(run_date, "Vendor price populated on the PO line.",
                [_field("supplier_price", snap.get("supplier_price"), cur.get("price"), "$")])


def no_receipt_overdue(run_date, snap, cur):
    """PO-07 — close once a receipt lands against the PO, or Supply Chain cancels/closes it."""
    if not cur:
        return None
    received = cur.get("received") or 0
    if received > 0:
        return _res(run_date, "Receipt now recorded against the PO.",
                    [_field("received_qty", snap.get("received_qty", 0), received)])
    if cur.get("cancelled"):
        return _res(run_date, "PO marked Cancelled by Supply Chain.")
    if not cur.get("open"):
        return _res(run_date, "PO closed by Supply Chain (no longer open).")
    return None


def partial_not_closed(run_date, snap, cur):
    """PO-08 — close once the PO is fully received, or Supply Chain closes/cancels it."""
    if not cur:
        return None
    if not cur.get("not_closed"):
        return _res(run_date, "PO closed by Supply Chain.")
    received, ordered = cur.get("received") or 0, cur.get("ordered") or 0
    if ordered and received >= ordered - 0.001:
        return _res(run_date, "PO now fully received.",
                    [_field("received_qty", snap.get("received_qty"), received),
                     _field("ordered_qty", snap.get("ordered_qty"), ordered)])
    return None


def consumable_zero_cost(run_date, snap, cur):
    if not cur or cur.get("missing"):
        return None
    return _res(run_date, "Standard cost corrected in the ERP (Dynamics).",
                [_field("standard_unit_cost", snap.get("standard_unit_cost"), cur.get("unit_cost"), "$")])


def waste_sku_no_cost(run_date, snap, cur):
    """cur = {"unit_cost", "cost_uom"} once a cost record exists for the SKU, else None."""
    if not cur:
        return None
    return _res(run_date, "Standard-cost record now exists for this SKU.",
                [_field("standard_unit_cost", None, cur.get("unit_cost"), "$")])


def daily_waste(run_date, snap, cur):
    if cur is None:
        return None
    th = reference.waste_daily_threshold(snap.get("facility_type"))["high"]
    if cur["dollars"] > th:
        return None
    return _res(run_date, "Daily facility waste back under threshold.",
                [_field("waste_dollars", snap.get("waste_dollars"), cur["dollars"], "$")])


def daily_adjust(run_date, snap, cur):
    if cur is None:
        return None
    th = reference.adjust_daily_threshold(snap.get("facility_type"))["high"]
    if cur["dollars"] > th:
        return None
    return _res(run_date, "Daily facility adjustments back under threshold.",
                [_field("adjust_dollars", snap.get("adjust_dollars"), cur["dollars"], "$")])


def populated(run_date, summary):
    """Existence-only fixes (PO number set, SKU now on the PO, transfer order created) — no numeric
    'now' value, just a dated note of what changed."""
    return _res(run_date, summary)
