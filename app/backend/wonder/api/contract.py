"""Build the bootstrap payload the (already-approved) console consumes — the same
`window.DATA` shape the prototype used, but computed from the live database.
"""
from datetime import date
from typing import Dict, List

from sqlalchemy import select

from ..models import Error, TicketEvent, ValidationRun
from .. import reference
from ..config import settings

OPEN_STATES = ("Open", "In Progress", "In Review")
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
        is_handoff = "sub-assigned" in (e.to_status or "").lower()
        if is_change or is_handoff:
            out.append({"status": e.to_status, "at": e.occurred_at, "by": e.actor})
    return out


def _exception(e: Error, today: str) -> Dict:
    snap = e.data_snapshot or {}
    resolved_date = e.resolved_at[:10] if e.resolved_at else None
    is_open = e.status in OPEN_STATES
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
        "system": snap.get("system", "—"),
        "entityKey": e.entity_key,
        "team": e.routed_team,
        "assignee": e.routed_assignee,
        "jira": e.jira_issue_key or "—",
        "jiraStatus": e.status,
        "created": e.first_run_date,
        "resolved": resolved_date,
        "recurrence": e.recurrence,
        "snapshot": snap,
        "rule": e.rule_id,
        "timeline": _timeline(e.events),
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
        "errorTypes": reference.ERROR_TYPES,
        "teams": reference.TEAMS,
        "slaTargets": reference.SLA_TARGETS,
        "rules": rules,
        "routing": routing,
        "exceptions": exceptions,
        "trend": trend,
        "recurring": recurring,
    }
