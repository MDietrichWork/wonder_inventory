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
        err = Error(
            fingerprint=fp, rule_id=f.rule_id, error_type=f.error_type, source_table=f.source_table,
            entity_key=f.entity_key, data_snapshot=f.snapshot, severity=f.severity,
            routed_team=route.team if route else "Unassigned",
            routed_assignee=route.assignee if route else "Unassigned",
            status="Open", detected_at=as_of, first_run_date=run_date, last_seen_run=run_date,
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
        # BigQuery (scoped rule): re-check each open ticket's specific entity against current data
        # and close only the ones that genuinely pass now (cap-independent, no false closes).
        from ..rules.bq_finder import recheck
        high = settings.over_receipt_high_pct
        pairs = list({((e.data_snapshot or {}).get("po"), (e.data_snapshot or {}).get("consumable_sku"))
                      for e in open_errs if (e.data_snapshot or {}).get("po")})
        current = recheck(ds, pairs) if pairs else {}
        for e in open_errs:
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

    run.rows_scanned = rows_scanned
    run.error_count = len(seen)
    run.new_count = new_count
    run.autoclosed_count = autoclosed
    run.finished_at = as_of
    run.status = "done"
    db.commit()
    return run
