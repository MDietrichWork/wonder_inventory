"""Build the bootstrap payload the (already-approved) console consumes — the same
`window.DATA` shape the prototype used, but computed from the live database.
"""
from datetime import date
from typing import Dict, List

from sqlalchemy import select

from ..models import Error, TicketEvent, ValidationRun
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

    runs = list(db.scalars(select(ValidationRun).order_by(ValidationRun.run_date)))
    trend = [{"date": r.run_date, "count": r.error_count, "autoClosed": r.autoclosed_count} for r in runs]

    # recurring leaderboard: top fingerprints by recurrence
    top = sorted(errors, key=lambda e: e.recurrence, reverse=True)[:6]
    recurring = [{
        "fingerprint": "%s @ %s" % (e.error_type, (e.data_snapshot or {}).get("facility", "—")),
        "errorType": e.error_type, "facility": (e.data_snapshot or {}).get("facility", "—"),
        "count30d": e.recurrence, "team": e.routed_team, "lastSeen": e.last_seen_run,
        "trend": "up" if e.recurrence >= 4 else "flat",
    } for e in top]

    rules = [{
        "id": r["id"], "name": r["name"], "type": PRIMITIVE_DISPLAY.get(r["primitive"], r["primitive"]),
        "errorType": r["error_type"], "target": r["target_table"], "severity": r["severity"],
        "expression": r["expression"], "enabled": r["enabled"],
    } for r in reference.RULES]
    routing = [{
        "errorType": r["error_type"], "team": r["team"], "assignee": r["assignee"],
        "project": r["jira_project"], "component": r["jira_component"],
    } for r in reference.ROUTING]

    return {
        "meta": {"today": today, "runDate": today, "jiraProject": settings.jira_project_key,
                 "jiraBaseUrl": (settings.jira_base_url if settings.ticket_sink == "jira" else None)},
        "facilities": reference.FACILITIES,
        "systems": reference.SYSTEMS,
        "sourceTables": ["unified_ledger", "po_table"],
        "movementTypes": reference.MOVEMENT_TYPES,
        "errorTypes": [dict(et, label=reference.error_label(et["type"])) for et in reference.ERROR_TYPES],
        "teams": reference.TEAMS,
        "slaTargets": reference.SLA_TARGETS,
        "rules": rules,
        "routing": routing,
        "exceptions": exceptions,
        "trend": trend,
        "recurring": recurring,
    }
