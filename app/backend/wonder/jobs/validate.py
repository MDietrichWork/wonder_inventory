"""The daily validation run: detect -> fingerprint -> dedup -> route -> create/update
ticket -> auto-close on non-reproduction. Idempotent: re-running the same run_date
creates no duplicate tickets and leaves counts stable.
"""
import hashlib
from typing import Dict

from sqlalchemy import select

from ..models import ValidationRun, Rule, RoutingMap, Error, TicketEvent, AuditLog
from ..rules import run_rules
from ..schema_map import LEDGER_TABLE, PO_TABLE
from ..config import settings
from .. import reference

OPEN_STATES = ("Open", "In Progress", "In Review")
CLOSED_STATES = ("Resolved", "Closed", "Auto-Closed")


def fingerprint(rule_id: str, entity_key: str) -> str:
    return hashlib.sha256(("%s|%s" % (rule_id, entity_key)).encode()).hexdigest()


def _ts(run_date: str) -> str:
    return run_date + "T05:30:00Z"  # the overnight batch timestamp (deterministic)


def _auto_close(db, e, as_of, sink, note):
    """Mark an open error auto-closed + transition its Jira issue to Done."""
    e.status = "Auto-Closed"
    e.resolved_at = as_of
    db.add(TicketEvent(error_id=e.id, jira_issue_key=e.jira_issue_key, from_status="Open",
                       to_status="Auto-Closed", actor="batch-validator", occurred_at=as_of, note=note))
    db.add(AuditLog(actor="batch-validator", action="auto_close", entity="error",
                    entity_id=str(e.id), before={"status": "Open"}, after={"status": "Auto-Closed"}, at=as_of))
    sink.close(e, note)


def run_validation(db, run_date: str, ds, sink, backfill: bool = False) -> ValidationRun:
    as_of = _ts(run_date)
    run = ValidationRun(run_date=run_date, started_at=as_of, status="running")
    db.add(run)
    db.flush()

    rules = list(db.scalars(select(Rule).where(Rule.enabled.is_(True))))
    routing: Dict[str, RoutingMap] = {r.error_type: r for r in db.scalars(select(RoutingMap))}

    if settings.data_source == "bigquery":
        from ..rules.bq_finder import find_bigquery
        findings, rows_scanned = find_bigquery(ds, run_date, rules, backfill=backfill)
    else:
        rows_scanned = len(ds.fetch_table(LEDGER_TABLE, run_date)) + len(ds.fetch_table(PO_TABLE))
        findings = run_rules(rules, ds, run_date)

    seen = {}
    new_count = 0
    for f in findings:
        fp = fingerprint(f.rule_id, f.entity_key)
        seen[fp] = f
        existing = db.scalars(
            select(Error).where(Error.fingerprint == fp).order_by(Error.id.desc())
        ).first()
        if existing and existing.status in OPEN_STATES:
            existing.data_snapshot = f.snapshot
            existing.severity = f.severity
            if existing.last_seen_run != run_date:
                existing.recurrence += 1
                existing.last_seen_run = run_date
                db.add(TicketEvent(error_id=existing.id, jira_issue_key=existing.jira_issue_key,
                                   from_status=existing.status, to_status=existing.status,
                                   actor="batch-validator", occurred_at=as_of,
                                   note="Recurred on run %s (×%d)." % (run_date, existing.recurrence)))
                sink.comment(existing, "Still reproducing on run %s (recurrence ×%d)." % (run_date, existing.recurrence))
            continue

        route = routing.get(f.error_type)
        routed_team = route.team if route else "Unassigned"
        routed_assignee = route.assignee if route else "Unassigned"
        # Over-receipt and daily-facility-waste route by facility type (HDR -> Field Ops/IKC,
        # CK·DISH·PRODUCTION -> Field Ops/ProdCo) rather than the flat error_type map.
        if f.error_type in ("PO_OVER_RECEIPT", "WASTE_DAILY_FACILITY"):
            routed_team, routed_assignee = reference.field_ops_facility_route((f.snapshot or {}).get("facility_type"))
        # SLA/age anchor = when the error actually began in the data (breach date), not when the
        # batch happened to detect it. detected_at keeps the real detection timestamp.
        anchor = (f.snapshot or {}).get("breached_at") or run_date
        err = Error(
            fingerprint=fp, rule_id=f.rule_id, error_type=f.error_type, source_table=f.source_table,
            entity_key=f.entity_key, data_snapshot=f.snapshot, severity=f.severity,
            routed_team=routed_team,
            routed_assignee=routed_assignee,
            status="Open", detected_at=as_of, first_run_date=anchor, last_seen_run=run_date,
            recurrence=1,
        )
        db.add(err)
        db.flush()  # assign id
        err.jira_issue_key = sink.create(err)
        db.add(TicketEvent(error_id=err.id, jira_issue_key=err.jira_issue_key, from_status=None,
                           to_status="Open", actor="batch-validator", occurred_at=as_of,
                           note="Auto-created and routed to %s / %s." % (err.routed_team, err.routed_assignee)))
        db.add(AuditLog(actor="batch-validator", action="create_ticket", entity="error",
                        entity_id=str(err.id), before=None,
                        after={"fingerprint": fp, "jira": err.jira_issue_key}, at=as_of))
        new_count += 1

    # ---- Auto-close tickets whose issue no longer reproduces (DE fixed it upstream) ----
    autoclosed = 0
    open_errs = list(db.scalars(select(Error).where(Error.status.in_(OPEN_STATES))))
    if settings.data_source != "bigquery":
        # Fixtures: each run re-evaluates the whole partition, so "absent this run" == fixed.
        for e in open_errs:
            if e.fingerprint not in seen and e.last_seen_run < run_date:
                _auto_close(db, e, as_of, sink, "Issue no longer reproduces on run %s — auto-closed." % run_date)
                autoclosed += 1
    else:
        # BigQuery (scoped rules): re-check each open ticket's specific entity against current data
        # and close only the ones that genuinely pass now (cap-independent, no false closes).
        from ..rules.bq_finder import (recheck, recheck_price, recheck_null_po, recheck_sku_on_po,
                                        recheck_to_exists, recheck_daily_waste_facility,
                                        recheck_waste_sku_no_cost, recheck_consumable_cost)
        high = settings.over_receipt_high_pct
        OVER_TYPES = ("PO_OVER_RECEIPT", "PO_IMPLAUSIBLE_QTY", "PO_UOM_MISMATCH")
        over_errs = [e for e in open_errs if e.error_type in OVER_TYPES]
        price_errs = [e for e in open_errs if e.error_type == "PO_MISSING_PRICE"]
        nullpo_errs = [e for e in open_errs if e.error_type == "PO_MISSING_NUMBER"]
        sku_errs = [e for e in open_errs if e.error_type == "PO_SKU_NOT_ON_PO"]
        to_errs = [e for e in open_errs if e.error_type == "TRANSFER_ORDER_MISSING"]
        dwf_errs = [e for e in open_errs if e.error_type == "WASTE_DAILY_FACILITY"]
        nocost_errs = [e for e in open_errs if e.error_type == "WASTE_SKU_NO_COST"]
        zerocost_errs = [e for e in open_errs if e.error_type == "CONSUMABLE_ZERO_COST"]

        # over-receipt family: received-vs-ordered + UoM
        pairs = list({((e.data_snapshot or {}).get("po"), (e.data_snapshot or {}).get("consumable_sku"))
                      for e in over_errs if (e.data_snapshot or {}).get("po")})
        current = recheck(ds, pairs) if pairs else {}
        for e in over_errs:
            snap = e.data_snapshot or {}
            cur = current.get((snap.get("po"), snap.get("consumable_sku")))
            if not cur or cur.get("recv") is None or not cur.get("ord"):
                continue  # no recent receipts / no PO line — can't confirm; leave open
            over = (cur["recv"] / cur["ord"]) - 1
            uom_mismatch = bool(cur.get("ouom") and cur.get("ruom") and cur["ouom"] != cur["ruom"])
            if over <= high and not uom_mismatch:  # received now within tolerance AND UoMs agree
                _auto_close(db, e, as_of, sink,
                            "Re-check on run %s: received now within tolerance / UoM reconciled — auto-closed." % run_date)
                autoclosed += 1

        # missing-price: close once a vendor price has been set
        ppairs = list({((e.data_snapshot or {}).get("po"), (e.data_snapshot or {}).get("supplier_sku"))
                       for e in price_errs if (e.data_snapshot or {}).get("po")})
        pcurrent = recheck_price(ds, ppairs) if ppairs else {}
        for e in price_errs:
            snap = e.data_snapshot or {}
            cur = pcurrent.get((snap.get("po"), snap.get("supplier_sku")))
            if not cur:
                continue  # PO line not found — can't confirm; leave open
            if not cur["missing"]:  # a vendor price has been set
                _auto_close(db, e, as_of, sink,
                            "Re-check on run %s: vendor price now populated — auto-closed." % run_date)
                autoclosed += 1

        # missing PO number (master table): close once a PO number is set
        nids = list({(e.data_snapshot or {}).get("po_id") for e in nullpo_errs if (e.data_snapshot or {}).get("po_id")})
        ncurrent = recheck_null_po(ds, nids) if nids else {}
        for e in nullpo_errs:
            cur = ncurrent.get(str((e.data_snapshot or {}).get("po_id")))
            if cur and not cur["missing"]:
                _auto_close(db, e, as_of, sink,
                            "Re-check on run %s: PO number now populated — auto-closed." % run_date)
                autoclosed += 1

        # received SKU not on the PO: close once the SKU appears on the PO's lines
        spairs = list({((e.data_snapshot or {}).get("po"), (e.data_snapshot or {}).get("consumable_sku"))
                       for e in sku_errs if (e.data_snapshot or {}).get("po")})
        now_on_po = recheck_sku_on_po(ds, spairs) if spairs else set()
        for e in sku_errs:
            snap = e.data_snapshot or {}
            if "%s~~%s" % (snap.get("po"), snap.get("consumable_sku")) in now_on_po:
                _auto_close(db, e, as_of, sink,
                            "Re-check on run %s: SKU now listed on the PO — auto-closed." % run_date)
                autoclosed += 1

        # transfer order missing: close once the transfer order exists in the population
        to_ids = list({(e.data_snapshot or {}).get("transfer_order") for e in to_errs if (e.data_snapshot or {}).get("transfer_order")})
        now_exist = recheck_to_exists(ds, to_ids) if to_ids else set()
        for e in to_errs:
            if (e.data_snapshot or {}).get("transfer_order") in now_exist:
                _auto_close(db, e, as_of, sink,
                            "Re-check on run %s: transfer order now exists — auto-closed." % run_date)
                autoclosed += 1

        # daily facility waste: close once the facility-day NET waste $ is back under its High threshold
        dkeys = list({((e.data_snapshot or {}).get("facility"), (e.data_snapshot or {}).get("day"))
                      for e in dwf_errs if (e.data_snapshot or {}).get("facility")})
        dcur = recheck_daily_waste_facility(ds, dkeys) if dkeys else {}
        for e in dwf_errs:
            snap = e.data_snapshot or {}
            cur = dcur.get("%s~~%s" % (snap.get("facility"), snap.get("day")))
            if cur is None:
                continue  # couldn't recompute — leave open rather than false-close
            threshold = reference.waste_daily_threshold(snap.get("facility_type"))["high"]
            if cur["dollars"] <= threshold:
                _auto_close(db, e, as_of, sink,
                            "Re-check on run %s: daily facility waste back under threshold — auto-closed." % run_date)
                autoclosed += 1

        # waste SKU with no standard-cost record: close once a cost record exists for the SKU
        ncskus = list({(e.data_snapshot or {}).get("consumable_sku") for e in nocost_errs})
        now_costed = recheck_waste_sku_no_cost(ds, ncskus) if ncskus else set()
        for e in nocost_errs:
            if str((e.data_snapshot or {}).get("consumable_sku")) in now_costed:
                _auto_close(db, e, as_of, sink,
                            "Re-check on run %s: standard-cost record now exists — auto-closed." % run_date)
                autoclosed += 1

        # consumable zero/null standard cost: close once a non-zero cost is set
        zcskus = list({(e.data_snapshot or {}).get("consumable_sku") for e in zerocost_errs})
        zccur = recheck_consumable_cost(ds, zcskus) if zcskus else {}
        for e in zerocost_errs:
            cur = zccur.get(str((e.data_snapshot or {}).get("consumable_sku")))
            if cur and not cur["missing"]:  # a non-zero standard cost has been set
                _auto_close(db, e, as_of, sink,
                            "Re-check on run %s: standard cost now populated — auto-closed." % run_date)
                autoclosed += 1

    run.rows_scanned = rows_scanned
    run.error_count = len(seen)
    run.new_count = new_count
    run.autoclosed_count = autoclosed
    run.finished_at = as_of
    run.status = "done"
    db.commit()
    return run
