"""Build the bootstrap payload the (already-approved) console consumes — the same
`window.DATA` shape the prototype used, but computed from the live database.
"""
from datetime import date
from typing import Dict, List

from sqlalchemy import select

from ..models import Error, TicketEvent, ValidationRun, Rule, WasteActionCombo
from .. import reference
from ..config import settings

# A ticket is closed once it reaches one of these (covers app + Jira status names).
CLOSED_STATES = ("Resolved", "Closed", "Auto-Closed", "Done")
PRIMITIVE_DISPLAY = {"OVER_RECEIPT": "RANGE", "RECON_TRANSFER": "RECONCILIATION"}


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def _days(a: str, b: str) -> int:
    return (_d(b) - _d(a)).days


def latest_run_date(db) -> str:
    r = db.scalars(select(ValidationRun).order_by(ValidationRun.run_date.desc())).first()
    return r.run_date if r else date.today().isoformat()


def _timeline(events: List[TicketEvent]) -> List[Dict]:
    out = []
    for e in sorted(events, key=lambda x: x.occurred_at):
        # keep creation, status changes, sub-assignments, auto-close — drop pure recurrence pings
        is_change = e.from_status is None or e.from_status != e.to_status
        is_handoff = "handed off" in (e.to_status or "").lower() or "sub-assigned" in (e.to_status or "").lower()
        if is_change or is_handoff:
            out.append({"status": e.to_status, "at": e.occurred_at, "by": e.actor})
    return out


def _exception(e: Error, today: str) -> Dict:
    snap = e.data_snapshot or {}
    resolved_date = e.resolved_at[:10] if e.resolved_at else None
    is_open = e.status not in CLOSED_STATES
    sla = reference.SLA_TARGETS.get(e.severity, 3)
    age = _days(e.first_run_date, today)
    turnaround = _days(e.first_run_date, resolved_date) if resolved_date else None
    within = (age <= sla) if is_open else (turnaround is not None and turnaround <= sla)
    out = {
        "pk": e.id,
        "id": "ERR-%05d" % e.id,
        "runDate": e.last_seen_run,
        "errorType": e.error_type,
        "severity": e.severity,
        "table": e.source_table,
        "facility": snap.get("facility", "—"),
        "system": reference.canon_system(snap.get("system")) or "—",
        "entityKey": e.entity_key,
        "team": e.routed_team,
        "assignee": e.routed_assignee,
        "primaryOwner": e.routed_assignee,                       # accountable, never changes on hand-off
        "currentHolder": e.sub_assignee or e.routed_assignee,    # who's actively working it now
        "heldSince": (e.sub_assigned_at[:10] if e.sub_assigned_at else e.first_run_date),
        "heldDays": _days(e.sub_assigned_at[:10] if e.sub_assigned_at else e.first_run_date, today),
        "jira": e.jira_issue_key or "—",
        "jiraStatus": e.status,
        "created": e.first_run_date,                              # = breach date (when the error began)
        "detectedOn": (e.detected_at or e.first_run_date)[:10],   # when the batch caught it
        "lastReceipt": snap.get("last_receipt"),                  # staleness: most recent receipt activity
        "resolved": resolved_date,
        "recurrence": e.recurrence,
        "snapshot": snap,
        "rule": e.rule_id,
        "timeline": _timeline(e.events),
        # notes = console comments, newest-first (descending) for the drawer
        "notes": [{"by": ev.actor, "at": ev.occurred_at, "text": ev.note}
                  for ev in sorted(e.events, key=lambda x: x.occurred_at, reverse=True) if ev.to_status == "Comment"],
        "age": age,
        "turnaround": turnaround,
        "slaTarget": sla,
        "withinSla": within,
        "isOpen": is_open,
        "autoClosed": e.status == "Auto-Closed",
    }
    if e.sub_team:
        out["subAssign"] = {
            "toTeam": e.sub_team, "toPerson": e.sub_assignee or (e.sub_team + " lead"),
            "at": e.sub_assigned_at or "", "byPerson": e.routed_assignee,
            "slaRemainingDays": max(0, sla - age),
            "note": "Sub-assigned to the root-cause team. Primary owner stays accountable; the original SLA does not reset.",
        }
    return out


def build_bootstrap(db) -> Dict:
    today = latest_run_date(db)
    errors = list(db.scalars(select(Error).order_by(Error.id)))
    exceptions = [_exception(e, today) for e in errors]

    # One trend point per calendar day. Multiple runs can share a run_date (re-runs, scheduler +
    # manual); keep the latest run of each day (highest id = end-of-day state) so the "per day" chart
    # isn't duplicated per run.
    runs = list(db.scalars(select(ValidationRun).order_by(ValidationRun.run_date, ValidationRun.id)))
    by_day = {r.run_date: r for r in runs}  # ascending id → last write wins = latest run that day
    trend = [{"date": r.run_date, "count": r.error_count, "autoClosed": r.autoclosed_count}
             for r in sorted(by_day.values(), key=lambda r: r.run_date)]

    # recurring leaderboard: top fingerprints by recurrence
    top = sorted(errors, key=lambda e: e.recurrence, reverse=True)[:6]
    recurring = [{
        "fingerprint": "%s @ %s" % (e.error_type, (e.data_snapshot or {}).get("facility", "—")),
        "errorType": e.error_type, "facility": (e.data_snapshot or {}).get("facility", "—"),
        "count30d": e.recurrence, "team": e.routed_team, "lastSeen": e.last_seen_run,
        "trend": "up" if e.recurrence >= 4 else "flat",
    } for e in top]

    # Rules come from the DB (the editable source of truth that validation also reads), ordered by the
    # reference catalog so the Admin list stays in its curated order. Edits via PATCH /api/rules show here.
    _order = {r["id"]: i for i, r in enumerate(reference.RULES)}
    db_rules = sorted(db.scalars(select(Rule)), key=lambda r: _order.get(r.id, 999))
    rules = [{
        "id": r.id, "name": r.name, "type": PRIMITIVE_DISPLAY.get(r.primitive, r.primitive),
        "errorType": r.error_type, "target": r.target_table, "severity": r.severity,
        "expression": r.expression, "enabled": r.enabled,
    } for r in db_rules]
    routing = [{
        "errorType": r["error_type"], "team": r["team"], "assignee": r["assignee"],
        "project": settings.jira_project_key, "component": r["jira_component"],
    } for r in reference.ROUTING]

    # Editable facility threshold bands (DB-backed). refresh() also loads them into reference so the
    # dashboard waste metric computed later in this request uses the current values.
    from .. import thresholds as _thresholds
    threshold_rows = _thresholds.refresh(db)
    thresholds_payload = [{
        "errorType": t.error_type, "errorLabel": reference.error_label(t.error_type),
        "facilityType": t.facility_type, "high": t.high, "urgent": t.urgent,
    } for t in sorted(threshold_rows, key=lambda x: (x.error_type, x.facility_type))]

    # Editable Daily-Waste action allowlist (DB-backed). The Admin UI adds/removes/toggles these
    # (l1_action, l2_action) pairs and the next run honors them (refresh() above reloaded them).
    waste_combos = [{"l1Action": c.l1_action, "l2Action": c.l2_action, "enabled": c.enabled}
                    for c in sorted(db.scalars(select(WasteActionCombo)),
                                    key=lambda c: (c.l1_action, c.l2_action))]
    # The reference SQL is code-owned (read-only in the UI), so always serve it from code rather than
    # the DB copy — sync_catalog only INSERTs new rules, so an existing rule's stored expression goes
    # stale when the code changes. SQL-backed rules show the exact daily query they run (generated from
    # the finders — paste into BigQuery to reproduce that rule's exceptions, reflecting the live
    # waste-action allowlist + facility-type thresholds loaded by refresh() above); catalog-only rules
    # fall back to their hand-written reference SQL.
    _ref_expr = {r["id"]: r["expression"] for r in reference.RULES}
    try:
        from ..rules import bq_finder
        _doc = bq_finder.doc_sql
        _wired = bq_finder.wired_rule_ids()
    except Exception:  # pragma: no cover - keep bootstrap resilient if the finder import fails
        _doc = lambda _id: None
        _wired = set()
    for _r in rules:
        try:
            sql = _doc(_r["id"])
        except Exception:  # pragma: no cover
            sql = None
        sql = sql or _ref_expr.get(_r["id"])
        if sql:
            _r["expression"] = sql
        # Does this rule have a live detector wired in? (False = catalog-only — defined but inert.)
        _r["wired"] = _r["id"] in _wired

    # Closed-ticket retention (DB-backed, Admin-editable). Also surface how many closed tickets are
    # currently past the window so the Admin card can show it without a second request.
    from .. import retention
    retention_days = retention.get_retention_days(db)

    # XFER-04 / XFER-07 aging day-thresholds (DB-backed, Admin-editable).
    from .. import xfer_aging
    xfer_no_pick_days = xfer_aging.get_no_pick_days(db)
    xfer_not_received_days = xfer_aging.get_not_received_days(db)

    return {
        "meta": {"today": today, "runDate": today, "jiraProject": settings.jira_project_key,
                 "jiraBaseUrl": (settings.jira_base_url if settings.ticket_sink == "jira" else None)},
        "settings": {"closedRetentionDays": retention_days,
                     "closedPastWindow": retention.closed_past_window(db, retention_days),
                     "xferNoPickDays": xfer_no_pick_days,
                     "xferNotReceivedDays": xfer_not_received_days},
        "facilities": reference.FACILITIES,
        "systems": reference.SYSTEMS,
        "sourceTables": ["unified_ledger", "po_table"],
        "movementTypes": reference.MOVEMENT_TYPES,
        "errorTypes": [dict(et, label=reference.error_label(et["type"]),
                            plain=reference.error_plain(et["type"])) for et in reference.ERROR_TYPES],
        "teams": reference.TEAMS,
        "slaTargets": reference.SLA_TARGETS,
        "rules": rules,
        "routing": routing,
        "thresholds": thresholds_payload,
        "wasteActionCombos": waste_combos,
        "exceptions": exceptions,
        "trend": trend,
        "recurring": recurring,
    }
