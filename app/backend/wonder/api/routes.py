"""REST API. The console fetches /api/bootstrap once (the full DATA contract) and renders
all screens client-side; the action endpoints persist mock-but-real mutations."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ..db import SessionLocal
from ..models import Error, TicketEvent, AuditLog, ValidationRun
from ..config import settings
from ..datasource import get_datasource
from ..tickets import get_ticket_sink
from ..jobs import run_validation
from .contract import build_bootstrap

router = APIRouter(prefix="/api")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AssignBody(BaseModel):
    assignee: str


class SubAssignBody(BaseModel):
    person: str                 # the new current holder (who does the actual work)
    team: Optional[str] = None  # optional team context


class TransitionBody(BaseModel):
    to: str


# App-facing statuses ↔ Jira statuses. The app keeps its own friendlier wording (Open/Resolved);
# we translate to the Jira transition name when pushing.
APP_TO_JIRA = {"Open": "To Do", "In Progress": "In Progress", "In Review": "In Review", "Resolved": "Done"}
CLOSED_AT_STATES = ("Resolved", "Closed", "Auto-Closed", "Done")


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/bootstrap")
def bootstrap(db=Depends(get_db)):
    return build_bootstrap(db)


@router.post("/run")
def run(db=Depends(get_db)):
    dates = sorted({d for d in db.scalars(select(ValidationRun.run_date).distinct())})
    if not dates:
        raise HTTPException(400, "No prior runs; seed the database first.")
    ds = get_datasource(dates)
    sink = get_ticket_sink()
    run = run_validation(db, dates[-1], ds, sink)
    return {"ran": run.run_date, "scanned": run.rows_scanned, "seen": run.error_count,
            "new": run.new_count, "autoClosed": run.autoclosed_count}


def _get_error(db, pk: int) -> Error:
    e = db.get(Error, pk)
    if not e:
        raise HTTPException(404, "Error %s not found" % pk)
    return e


_BREAKDOWN_CACHE = {}  # pk -> result; the live BigQuery lookup is slow, so cache per session


@router.get("/exceptions/{pk}/breakdown")
def breakdown(pk: int, db=Depends(get_db)):
    """The 'why it flagged' detail: PO line vs ledger receipt events for this exception."""
    if pk in _BREAKDOWN_CACHE:
        return _BREAKDOWN_CACHE[pk]
    e = _get_error(db, pk)
    snap = e.data_snapshot or {}
    po, sku, sysn = snap.get("po"), snap.get("consumable_sku"), snap.get("system")
    if settings.data_source != "bigquery" or not po or not sku:
        return {"available": False, "rows": []}
    from ..rules.bq_finder import breakdown as bq_breakdown
    try:
        ds = get_datasource([e.last_seen_run])
        rows = bq_breakdown(ds, po, sku, sysn)
    except Exception as ex:  # pragma: no cover - network/perm
        return {"available": False, "error": str(ex)[:200], "rows": []}
    led = [r for r in rows if r["source"] == "LEDGER"]
    # duplicate heuristic: 2+ identical-qty 'Add' receipts → inventory added twice, not adjusted out
    from collections import Counter
    add_qtys = Counter(r["qty"] for r in led if r.get("l1_action") == "Add")
    result = {
        "available": True, "po": po, "consumable_sku": sku,
        "ordered_qty": snap.get("ordered_qty"), "received_qty": snap.get("received_qty"),
        "ordered_uom": snap.get("ordered_uom"), "received_uom": snap.get("received_uom"),
        "uom_match": snap.get("uom_match"), "over_by_pct": snap.get("over_by_pct"),
        "rows": rows, "ledger_count": len(led),
        "duplicate_suspected": any(c >= 2 for c in add_qtys.values()),
    }
    _BREAKDOWN_CACHE[pk] = result
    return result


@router.post("/exceptions/{pk}/transition")
def transition(pk: int, body: TransitionBody, db=Depends(get_db)):
    """Change the ticket's status from the workbench and push the transition to Jira."""
    e = _get_error(db, pk)
    jira_name = APP_TO_JIRA.get(body.to, body.to)
    synced = get_ticket_sink().transition(e, jira_name) if e.jira_issue_key else True
    prev, at = e.status, _now()
    e.status = body.to
    e.resolved_at = (e.resolved_at or at) if body.to in CLOSED_AT_STATES else None  # clear on reopen
    db.add(TicketEvent(error_id=e.id, jira_issue_key=e.jira_issue_key, from_status=prev, to_status=body.to,
                       actor="Mike Dietrich", occurred_at=at, note="Status changed in the workbench."))
    db.add(AuditLog(actor="Mike Dietrich", action="transition", entity="error", entity_id=str(e.id),
                    before={"status": prev}, after={"status": body.to}, at=at))
    db.commit()
    return {"ok": True, "status": e.status, "jiraSynced": synced}


@router.post("/exceptions/{pk}/assign")
def assign(pk: int, body: AssignBody, db=Depends(get_db)):
    e = _get_error(db, pk)
    before = e.routed_assignee
    e.routed_assignee = body.assignee
    db.add(TicketEvent(error_id=e.id, jira_issue_key=e.jira_issue_key, from_status=e.status,
                       to_status=e.status, actor="Mike Dietrich", occurred_at=_now(),
                       note="Assigned to %s (would update the JIRA assignee)." % body.assignee))
    db.add(AuditLog(actor="Mike Dietrich", action="assign", entity="error", entity_id=str(e.id),
                    before={"assignee": before}, after={"assignee": body.assignee}, at=_now()))
    synced = get_ticket_sink().set_assignee(e, body.assignee) if e.jira_issue_key else False
    db.commit()
    return {"ok": True, "assignee": e.routed_assignee, "jiraSynced": synced}


@router.post("/exceptions/{pk}/subassign")
def subassign(pk: int, body: SubAssignBody, db=Depends(get_db)):
    """Hand the work to another person. The primary owner (routed_assignee) stays accountable
    and the SLA does NOT reset; the current holder + hand-off time are recorded, and Jira's
    assignee becomes the holder."""
    e = _get_error(db, pk)
    person, team, at = body.person, body.team, _now()
    primary = e.routed_assignee
    e.sub_team, e.sub_assignee, e.sub_assigned_at = team, person, at
    label = "Handed off → %s%s" % (person, (" (%s)" % team if team else ""))
    db.add(TicketEvent(error_id=e.id, jira_issue_key=e.jira_issue_key, from_status=e.status,
                       to_status=label, actor=primary, occurred_at=at,
                       note="%s handed the work to %s; %s remains primary owner (accountable). SLA does not reset."
                       % (primary, person, primary)))
    db.add(AuditLog(actor=primary, action="handoff", entity="error", entity_id=str(e.id),
                    before={"holder": primary}, after={"holder": person, "team": team}, at=at))
    synced = False
    if e.jira_issue_key:
        sink = get_ticket_sink()
        synced = sink.set_assignee(e, person)   # current holder becomes the Jira assignee
        sink.comment(e, "Handed off from %s to %s. %s remains primary owner (accountable); SLA unchanged."
                     % (primary, person, primary))
    db.commit()
    return {"ok": True, "primaryOwner": primary, "currentHolder": person, "jiraAssigneeSynced": synced}


@router.post("/exceptions/{pk}/resolve")
def resolve(pk: int, db=Depends(get_db)):
    e = _get_error(db, pk)
    at = _now()
    e.status, e.resolved_at = "Resolved", at
    db.add(TicketEvent(error_id=e.id, jira_issue_key=e.jira_issue_key, from_status="Open",
                       to_status="Resolved", actor="Mike Dietrich", occurred_at=at,
                       note="Marked resolved in the workbench."))
    db.add(AuditLog(actor="Mike Dietrich", action="resolve", entity="error", entity_id=str(e.id),
                    before={"status": "Open"}, after={"status": "Resolved"}, at=at))
    if e.jira_issue_key:
        get_ticket_sink().close(e, "Marked resolved in the workbench by Mike Dietrich.")
    db.commit()
    return {"ok": True, "status": e.status}
