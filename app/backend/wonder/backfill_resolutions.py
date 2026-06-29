"""One-time enrichment: stamp the WAS→NOW 'correction applied' resolution onto tickets that were
already auto-closed BEFORE the live auto-close path started recording it. Read-only against
BigQuery (the same recheck queries the validator uses) — only the local app DB is written. Each
ticket is stamped with ITS OWN resolved date, and the value shown is the current corrected value.
Idempotent: skips tickets that already carry a resolution. Run: python -m wonder.backfill_resolutions
"""
from sqlalchemy import select

from .db import SessionLocal
from .models import Error, ValidationRun
from .config import settings
from .datasource import get_datasource
from .jobs import resolution
from .jobs.validate import CLOSED_STATES
from .rules.bq_finder import (recheck, recheck_price, recheck_null_po, recheck_null_po_ledger,
                              recheck_sku_on_po, recheck_to_exists, recheck_daily_waste_facility,
                              recheck_daily_adjust_facility, recheck_waste_sku_no_cost,
                              recheck_consumable_cost)


def _resolved_on(e):
    return (e.resolved_at or e.last_seen_run)[:10]


def _stamp(e, res):
    """Reassign the JSON dict so SQLAlchemy detects the mutation."""
    if not res:
        return False
    snap = dict(e.data_snapshot or {})
    snap["resolution"] = res
    e.data_snapshot = snap
    return True


def backfill():
    if settings.data_source != "bigquery":
        print("data_source is not bigquery — the rechecks need live BigQuery. Aborting.")
        return
    db = SessionLocal()
    try:
        latest = db.scalars(select(ValidationRun).order_by(ValidationRun.run_date.desc())).first()
        ds = get_datasource([latest.run_date] if latest else [])

        closed = [e for e in db.scalars(select(Error).where(Error.status.in_(CLOSED_STATES)))
                  if not (e.data_snapshot or {}).get("resolution")]
        by_type = {}
        for e in closed:
            by_type.setdefault(e.error_type, []).append(e)
        print("Closed tickets missing a resolution: %d (%s)"
              % (len(closed), ", ".join("%s=%d" % (k, len(v)) for k, v in sorted(by_type.items())) or "none"))

        stamped = 0

        def run(errs, recheck_fn, key_fn, build_fn):
            nonlocal stamped
            if not errs:
                return
            keyed = [(e, key_fn(e)) for e in errs]
            cur = recheck_fn(ds, [k for _, k in keyed if k is not None]) if keyed else {}
            for e, _ in keyed:
                if _stamp(e, build_fn(e, cur)):
                    stamped += 1

        snap = lambda e: e.data_snapshot or {}

        # over-receipt family (received-vs-ordered + UoM)
        run([e for e in closed if e.error_type in ("PO_OVER_RECEIPT", "PO_IMPLAUSIBLE_QTY", "PO_UOM_MISMATCH")],
            lambda ds, ks: recheck(ds, list({k for k in ks})),
            lambda e: (snap(e).get("po"), snap(e).get("consumable_sku")) if snap(e).get("po") else None,
            lambda e, cur: resolution.over_receipt(_resolved_on(e), snap(e),
                                                   cur.get((snap(e).get("po"), snap(e).get("consumable_sku")))))

        # missing vendor price
        run([e for e in closed if e.error_type == "PO_MISSING_PRICE"],
            lambda ds, ks: recheck_price(ds, list({k for k in ks})),
            lambda e: (snap(e).get("po"), snap(e).get("supplier_sku")) if snap(e).get("po") else None,
            lambda e, cur: resolution.missing_price(_resolved_on(e), snap(e),
                                                    cur.get((snap(e).get("po"), snap(e).get("supplier_sku")))))

        # consumable zero/null standard cost
        run([e for e in closed if e.error_type == "CONSUMABLE_ZERO_COST"],
            lambda ds, ks: recheck_consumable_cost(ds, list({k for k in ks})),
            lambda e: snap(e).get("consumable_sku"),
            lambda e, cur: resolution.consumable_zero_cost(_resolved_on(e), snap(e),
                                                           cur.get(str(snap(e).get("consumable_sku")))))

        # waste-active SKU without a standard-cost record
        run([e for e in closed if e.error_type == "WASTE_SKU_NO_COST"],
            lambda ds, ks: recheck_waste_sku_no_cost(ds, list({k for k in ks})),
            lambda e: snap(e).get("consumable_sku"),
            lambda e, cur: resolution.waste_sku_no_cost(_resolved_on(e), snap(e),
                                                        cur.get(str(snap(e).get("consumable_sku")))))

        # daily facility waste $
        run([e for e in closed if e.error_type == "WASTE_DAILY_FACILITY"],
            lambda ds, ks: recheck_daily_waste_facility(ds, list({k for k in ks})),
            lambda e: (snap(e).get("facility"), snap(e).get("day")) if snap(e).get("facility") else None,
            lambda e, cur: resolution.daily_waste(_resolved_on(e), snap(e),
                                                  cur.get("%s~~%s" % (snap(e).get("facility"), snap(e).get("day")))))

        # daily facility adjustment $
        run([e for e in closed if e.error_type == "ADJ_DAILY_FACILITY"],
            lambda ds, ks: recheck_daily_adjust_facility(ds, list({k for k in ks})),
            lambda e: (snap(e).get("facility"), snap(e).get("day")) if snap(e).get("facility") else None,
            lambda e, cur: resolution.daily_adjust(_resolved_on(e), snap(e),
                                                   cur.get("%s~~%s" % (snap(e).get("facility"), snap(e).get("day")))))

        # existence-only fixes (PO number / SKU-on-PO / transfer order)
        run([e for e in closed if e.error_type == "PO_MISSING_NUMBER"],
            lambda ds, ks: recheck_null_po(ds, list({k for k in ks})),
            lambda e: snap(e).get("po_id"),
            lambda e, cur: (resolution.populated(_resolved_on(e), "PO number now populated on the PO record.")
                            if (cur.get(str(snap(e).get("po_id"))) or {}).get("missing") is False else None))

        run([e for e in closed if e.error_type == "NULL_PO_NUMBER"],
            lambda ds, ks: recheck_null_po_ledger(ds, list({k for k in ks})),
            lambda e: snap(e).get("ledger_id"),
            lambda e, cur: (resolution.populated(_resolved_on(e), "PO number now populated on the ledger row.")
                            if (cur.get(str(snap(e).get("ledger_id"))) or {}).get("missing") is False else None))

        run([e for e in closed if e.error_type == "PO_SKU_NOT_ON_PO"],
            lambda ds, ks: recheck_sku_on_po(ds, list({k for k in ks})),
            lambda e: (snap(e).get("po"), snap(e).get("consumable_sku")) if snap(e).get("po") else None,
            lambda e, cur: (resolution.populated(_resolved_on(e), "SKU now listed on the PO's lines.")
                            if "%s~~%s" % (snap(e).get("po"), snap(e).get("consumable_sku")) in cur else None))

        run([e for e in closed if e.error_type == "TRANSFER_ORDER_MISSING"],
            lambda ds, ks: recheck_to_exists(ds, list({k for k in ks})),
            lambda e: snap(e).get("transfer_order"),
            lambda e, cur: (resolution.populated(_resolved_on(e), "Transfer order now exists in the population.")
                            if snap(e).get("transfer_order") in cur else None))

        db.commit()
        print("Stamped a resolution onto %d closed ticket(s)." % stamped)
    finally:
        db.close()


if __name__ == "__main__":
    backfill()
