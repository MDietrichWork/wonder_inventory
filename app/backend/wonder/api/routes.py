"""REST API. The console fetches /api/bootstrap once (the full DATA contract) and renders
all screens client-side; the action endpoints persist mock-but-real mutations."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import List, Optional

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from ..db import SessionLocal
from ..models import Error, TicketEvent, AuditLog, ValidationRun
from ..config import settings
from ..datasource import get_datasource
from ..tickets import get_ticket_sink
from ..jobs import run_validation
from ..status_map import APP_TO_JIRA, CLOSED_STATES as CLOSED_AT_STATES
from .contract import build_bootstrap, latest_run_date

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


class CommentBody(BaseModel):
    text: str


class RunBody(BaseModel):
    # Daily batch target. Omit to run the most-recently-completed day (yesterday PST);
    # Cloud Scheduler calls with an empty body. An explicit date is used for backfill / testing.
    run_date: Optional[str] = None


class RulePatch(BaseModel):
    enabled: Optional[bool] = None
    severity: Optional[str] = None
    name: Optional[str] = None


class ThresholdBand(BaseModel):
    errorType: str
    facilityType: str
    high: float
    urgent: float


class ThresholdsBody(BaseModel):
    bands: List[ThresholdBand]


# Ledger action names are short human labels: letters/digits/spaces and a few punctuation marks seen
# in the approved allowlist (e.g. "DISH Issue/Received Damaged", "Self-Directed Location Count"). This
# rejects SQL metacharacters (quotes, backslash, semicolons) as defense-in-depth on top of the bound
# @waste_keys parameter used in bq_finder.
_ACTION_RE = re.compile(r"^[A-Za-z0-9 /&().,-]{1,64}$")


class WasteCombo(BaseModel):
    l1Action: str
    l2Action: str
    enabled: bool = True

    @field_validator("l1Action", "l2Action")
    @classmethod
    def _valid_action(cls, v: str) -> str:
        v = (v or "").strip()
        if not _ACTION_RE.match(v):
            raise ValueError("action must be 1-64 chars of letters, digits, spaces, or / & ( ) . , -")
        return v


class WasteCombosBody(BaseModel):
    combos: List[WasteCombo]


class RetentionBody(BaseModel):
    days: int

    @field_validator("days")
    @classmethod
    def _valid_days(cls, v: int) -> int:
        if v < 0 or v > 3650:
            raise ValueError("days must be between 0 (keep forever) and 3650")
        return v


@router.get("/health")
def health():
    return {"ok": True}


_WASTE_CACHE = {}  # run_date -> waste-by-location (live BQ aggregation; cache so /bootstrap stays fast)


@router.get("/bootstrap")
def bootstrap(db=Depends(get_db)):
    data = build_bootstrap(db)
    data["wasteByLocation"] = _waste_by_location(data["meta"]["runDate"])
    return data


def _waste_by_location(run_date: str):
    """Daily waste $ by location (dashboard metric, not tickets). Live BQ aggregation, cached per
    run_date; resilient (returns [] off-BigQuery or on error)."""
    if settings.data_source != "bigquery":
        return []
    if run_date in _WASTE_CACHE:
        return _WASTE_CACHE[run_date]
    try:
        from ..rules.bq_finder import waste_by_location
        rows = waste_by_location(get_datasource([run_date]), run_date)
    except Exception:  # pragma: no cover - network/perm
        rows = []
    _WASTE_CACHE[run_date] = rows
    return rows


@router.get("/runinfo")
def runinfo(db=Depends(get_db)):
    """Cheap poll target: just the latest run date (the app's 'as-of' day). The console polls
    this and offers a refresh when it advances past the data it's currently showing."""
    return {"runDate": latest_run_date(db)}


@router.post("/run")
def run(body: Optional[RunBody] = None, db=Depends(get_db)):
    from ..jobs.daily import run_daily
    try:
        run = run_daily(db, body.run_date if body else None)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    return {"ran": run.run_date, "scanned": run.rows_scanned, "seen": run.error_count,
            "new": run.new_count, "autoClosed": run.autoclosed_count}


@router.patch("/rules/{rule_id}")
def patch_rule(rule_id: str, body: RulePatch, db=Depends(get_db)):
    """Persist editable Rule fields. `enabled` is the meaningful runtime control (the next validation
    run honors it); `severity`/`name` are metadata. The query LOGIC is code-owned (bq_finder.py) — the
    rule's `expression` is documentation and is not edited here."""
    from ..models import Rule
    r = db.get(Rule, rule_id)
    if not r:
        raise HTTPException(404, "Rule %s not found" % rule_id)
    before = {"enabled": r.enabled, "severity": r.severity, "name": r.name}
    if body.enabled is not None:
        r.enabled = body.enabled
    if body.severity is not None:
        r.severity = body.severity
    if body.name is not None and body.name.strip():
        r.name = body.name.strip()
    after = {"enabled": r.enabled, "severity": r.severity, "name": r.name}
    if before != after:
        db.add(AuditLog(actor="admin", action="edit_rule", entity="rule", entity_id=rule_id,
                        before=before, after=after, at=_now()))
        db.commit()
    return {"id": r.id, "enabled": r.enabled, "severity": r.severity, "name": r.name}


@router.put("/thresholds")
def update_thresholds(body: ThresholdsBody, db=Depends(get_db)):
    """Edit the High/Urgent $ bands for the banded daily rules (Daily Waste / Daily Adjustments).
    Writes the facility_threshold table + an audit log; the next validation run / bootstrap picks
    up the new values via reference's live bands."""
    from ..models import FacilityThreshold
    from .. import thresholds as _thresholds
    changed = 0
    for b in body.bands:
        ft = (b.facilityType or "").strip().upper()
        row = db.get(FacilityThreshold, (b.errorType, ft))
        before = {"high": row.high, "urgent": row.urgent} if row else None
        after = {"high": b.high, "urgent": b.urgent}
        if before == after:
            continue
        if row:
            row.high, row.urgent = b.high, b.urgent
        else:
            db.add(FacilityThreshold(error_type=b.errorType, facility_type=ft, high=b.high, urgent=b.urgent))
        db.add(AuditLog(actor="admin", action="edit_threshold", entity="facility_threshold",
                        entity_id="%s/%s" % (b.errorType, ft), before=before, after=after, at=_now()))
        changed += 1
    db.commit()
    _thresholds.refresh(db)
    return {"updated": changed}


@router.put("/waste-combos")
def update_waste_combos(body: WasteCombosBody, db=Depends(get_db)):
    """Replace the editable Daily-Waste action allowlist (waste_action_combo) with the full set the
    Admin UI submits: insert new (l1_action, l2_action) pairs, drop removed ones, update toggled
    enabled flags. Writes an audit log and refreshes reference's live allowlist so the next run /
    bootstrap uses it. The query LOGIC stays in code (bq_finder.py); only the allowlist is data."""
    from ..models import WasteActionCombo
    from .. import thresholds as _thresholds
    # desired set, keyed by (l1, l2); blanks dropped, later dups win
    desired = {}
    for c in body.combos:
        l1, l2 = (c.l1Action or "").strip(), (c.l2Action or "").strip()
        if l1 and l2:
            desired[(l1, l2)] = bool(c.enabled)
    existing = {(r.l1_action, r.l2_action): r for r in db.scalars(select(WasteActionCombo))}
    added = removed = updated = 0
    for key, enabled in desired.items():
        row = existing.get(key)
        if row is None:
            db.add(WasteActionCombo(l1_action=key[0], l2_action=key[1], enabled=enabled))
            added += 1
        elif row.enabled != enabled:
            row.enabled = enabled
            updated += 1
    for key, row in existing.items():
        if key not in desired:
            db.delete(row)
            removed += 1
    if added or removed or updated:
        db.add(AuditLog(actor="admin", action="edit_waste_combos", entity="waste_action_combo",
                        entity_id="WASTE_DAILY_FACILITY",
                        before={"count": len(existing)},
                        after={"count": len(desired), "added": added, "removed": removed, "updated": updated},
                        at=_now()))
        db.commit()
    _thresholds.refresh(db)
    enabled_count = sum(1 for v in desired.values() if v)
    return {"total": len(desired), "enabled": enabled_count,
            "added": added, "removed": removed, "updated": updated}


@router.put("/retention")
def update_retention(body: RetentionBody, db=Depends(get_db)):
    """Set how many days closed / auto-closed tickets are kept before the daily run purges them
    (0 = keep forever). Persists to app_setting + an audit log."""
    from .. import retention
    before = retention.get_retention_days(db)
    after = retention.set_retention_days(db, body.days)
    if before != after:
        db.add(AuditLog(actor="Mike Dietrich", action="edit_retention", entity="app_setting",
                        entity_id=retention.RETENTION_KEY, before={"days": before},
                        after={"days": after}, at=_now()))
    db.commit()
    return {"days": after}


@router.post("/retention/purge")
def purge_retention(db=Depends(get_db)):
    """Manually purge closed tickets older than the configured retention window (local-only)."""
    from .. import retention
    days = retention.get_retention_days(db)
    n = retention.purge_closed(db, days)
    return {"purged": n, "olderThanDays": days}


@router.post("/sync")
def sync(db=Depends(get_db)):
    """Pull status / assignee / resolution changes made directly in Jira back into the app."""
    from ..jobs.sync_jira import sync_from_jira
    return sync_from_jira(db, get_ticket_sink())


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


@router.post("/exceptions/{pk}/comment")
def comment(pk: int, body: CommentBody, db=Depends(get_db)):
    """Add a note from the console — posts a comment to the Jira issue and records it on the
    ticket timeline (kind 'Comment') so it persists and shows back in the app."""
    e = _get_error(db, pk)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "Empty comment")
    at = _now()
    db.add(TicketEvent(error_id=e.id, jira_issue_key=e.jira_issue_key, from_status="Comment",
                       to_status="Comment", actor="Mike Dietrich", occurred_at=at, note=text))
    db.add(AuditLog(actor="Mike Dietrich", action="comment", entity="error", entity_id=str(e.id),
                    before=None, after={"comment": text}, at=at))
    synced = False
    if e.jira_issue_key:
        try:
            get_ticket_sink().comment(e, "Mike Dietrich (DQ console): " + text)
            synced = True
        except Exception:  # pragma: no cover - network
            synced = False
    db.commit()
    return {"ok": True, "synced": synced}


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
