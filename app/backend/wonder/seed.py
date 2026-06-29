"""Seed the database: load rules/routing/SLA, then run the validator across the last
`history_days` daily partitions to build a realistic history (tickets, recurrence,
auto-closes). Run: python -m wonder.seed
"""
from datetime import date, timedelta

from sqlalchemy import select

from .db import reset_db, SessionLocal
from .models import (Rule, RoutingMap, SlaTarget, FacilityThreshold, WasteActionCombo,
                     ValidationRun, Error, TicketEvent, AuditLog)
from . import reference
from .config import settings
from .datasource import get_datasource
from .tickets import get_ticket_sink
from .jobs import run_validation


def _seed_demo_subassignment(db, run_date: str):
    """Hand off one open ticket to the root-cause team to showcase the ownership-transfer
    concept (primary owner stays accountable; SLA does not reset)."""
    e = db.scalars(
        select(Error).where(Error.error_type.in_(["NULL_PO_NUMBER", "PO_OVER_RECEIPT"]),
                            Error.status == "Open").order_by(Error.recurrence.desc())
    ).first()
    if not e:
        return
    at = run_date + "T15:10:00Z"
    e.sub_team, e.sub_assignee, e.sub_assigned_at = "Procurement", "Tom Becker", at
    db.add(TicketEvent(error_id=e.id, jira_issue_key=e.jira_issue_key, from_status="Open",
                       to_status="Sub-assigned → Procurement (Tom Becker)", actor=e.routed_assignee,
                       occurred_at=at, note="Receipt has no PO — Procurement must create/attach it. SLA does not reset."))
    db.add(AuditLog(actor=e.routed_assignee, action="sub_assign", entity="error", entity_id=str(e.id),
                    before=None, after={"team": "Procurement", "person": "Tom Becker"}, at=at))
    db.commit()


def sync_catalog(db):
    """Idempotently insert any rules / routing / threshold bands defined in reference but missing from
    the DB (e.g. a rule added in code since the last seed). INSERT-MISSING ONLY — never updates or
    deletes existing rows, so Admin edits (enabled toggles, tuned thresholds) are preserved. Runs on
    startup so new code-defined rules become live + visible without a full reseed."""
    added = {"rules": 0, "routing": 0, "thresholds": 0, "waste_combos": 0}
    have_rules = {r for r in db.scalars(select(Rule.id))}
    for r in reference.RULES:
        if r["id"] not in have_rules:
            db.add(Rule(id=r["id"], name=r["name"], primitive=r["primitive"], error_type=r["error_type"],
                        target_table=r["target_table"], params=r["params"], severity=r["severity"],
                        fail_type=r["fail_type"], owner_group=r["owner_group"], expression=r["expression"],
                        enabled=r["enabled"]))
            added["rules"] += 1
    have_routing = {e for e in db.scalars(select(RoutingMap.error_type))}
    for r in reference.ROUTING:
        if r["error_type"] not in have_routing:
            db.add(RoutingMap(error_type=r["error_type"], team=r["team"], assignee=r["assignee"],
                              jira_project=r["jira_project"], jira_component=r["jira_component"]))
            added["routing"] += 1
    have_th = {(t.error_type, t.facility_type) for t in db.scalars(select(FacilityThreshold))}
    for row in reference.default_threshold_rows():
        if (row["error_type"], row["facility_type"]) not in have_th:
            db.add(FacilityThreshold(**row))
            added["thresholds"] += 1
    have_combos = {(c.l1_action, c.l2_action)
                   for c in db.execute(select(WasteActionCombo.l1_action, WasteActionCombo.l2_action)).all()}
    for row in reference.default_waste_combo_rows():
        if (row["l1_action"], row["l2_action"]) not in have_combos:
            db.add(WasteActionCombo(**row))
            added["waste_combos"] += 1
    if any(added.values()):
        db.commit()
    return added


def _run_dates():
    latest = date.fromisoformat(settings.run_date) if settings.run_date else date.today()
    n = settings.history_days
    return [(latest - timedelta(days=k)).isoformat() for k in range(n - 1, -1, -1)]


def seed():
    reset_db()
    db = SessionLocal()
    try:
        for r in reference.RULES:
            db.add(Rule(id=r["id"], name=r["name"], primitive=r["primitive"], error_type=r["error_type"],
                        target_table=r["target_table"], params=r["params"], severity=r["severity"],
                        fail_type=r["fail_type"], owner_group=r["owner_group"], expression=r["expression"],
                        enabled=r["enabled"]))
        for r in reference.ROUTING:
            db.add(RoutingMap(error_type=r["error_type"], team=r["team"], assignee=r["assignee"],
                              jira_project=r["jira_project"], jira_component=r["jira_component"]))
        for sev, days in reference.SLA_TARGETS.items():
            db.add(SlaTarget(severity=sev, resolution_days=days))
        for row in reference.default_threshold_rows():
            db.add(FacilityThreshold(**row))
        for row in reference.default_waste_combo_rows():
            db.add(WasteActionCombo(**row))
        db.commit()

        # Operating model: one initial BACKFILL that catches the existing backlog (BigQuery: a
        # 2-week sweep as-of today), then the DAILY batch (prior-day touched POs) runs going
        # forward via the ↻ Run validation button / cron. Fixtures replay the full history daily.
        is_bq = settings.data_source == "bigquery"
        run_dates = _run_dates()[-1:] if is_bq else _run_dates()
        ds = get_datasource(run_dates)
        sink = get_ticket_sink()
        print("Seeding %s (%s … %s) | source=%s sink=%s"
              % ("backfill (2-week sweep)" if is_bq else "%d daily runs" % len(run_dates),
                 run_dates[0], run_dates[-1], settings.data_source, settings.ticket_sink))
        for i, d in enumerate(run_dates):
            backfill = is_bq and i == 0   # the one-time backlog catch-up (BigQuery)
            run = run_validation(db, d, ds, sink, backfill=backfill)
            print("  %s %-9s considered=%-6d seen=%-4d new=%-4d auto-closed=%-2d"
                  % (d, "BACKFILL" if backfill else "daily", run.rows_scanned, run.error_count,
                     run.new_count, run.autoclosed_count))

        _seed_demo_subassignment(db, run_dates[-1])
        print("Done. Latest run: %s" % run_dates[-1])
    finally:
        db.close()


if __name__ == "__main__":
    seed()
