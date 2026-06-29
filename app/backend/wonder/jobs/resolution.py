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
    """PO_OVER_RECEIPT family — received now within tolerance and UoMs agree."""
    if not cur or cur.get("recv") is None or not cur.get("ord"):
        return None
    over = (cur["recv"] / cur["ord"]) - 1
    uom_mismatch = bool(cur.get("ouom") and cur.get("ruom") and cur["ouom"] != cur["ruom"])
    if over > settings.over_receipt_high_pct or uom_mismatch:
        return None
    ruom = cur.get("ruom") or snap.get("received_uom")
    return _res(run_date, "Received quantity now within tolerance / UoM reconciled.", [
        _field("received_qty", snap.get("received_qty"), cur["recv"], ruom),
        _field("over_by_pct", snap.get("over_by_pct"), round(over * 100, 1), "%"),
    ])


def missing_price(run_date, snap, cur):
    if not cur or cur.get("missing"):
        return None
    return _res(run_date, "Vendor price populated on the PO line.",
                [_field("supplier_price", snap.get("supplier_price"), cur.get("price"), "$")])


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
