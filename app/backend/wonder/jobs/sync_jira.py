"""Phase 4 — Jira -> app poller. Reconciles changes made directly in Jira (status moves,
reassignments, resolution) back into the app, so the console reflects Jira reality and
turnaround is measured from real Jira resolution timestamps.

The deployment version is a webhook; this poller works locally / on-demand. Run:
    python -m wonder.jobs.sync_jira
or POST /api/sync.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from ..db import SessionLocal
from ..models import Error, TicketEvent
from ..tickets import get_ticket_sink
from ..status_map import JIRA_TO_APP, CLOSED_STATES


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync_from_jira(db, sink) -> dict:
    states = sink.fetch_issue_states()
    if not states:
        return {"polled": 0, "status_updates": 0, "closed": 0, "reopened": 0}
    updates = closed = reopened = 0
    errs = list(db.scalars(select(Error).where(Error.jira_issue_key.isnot(None))))
    for e in errs:
        st = states.get(e.jira_issue_key)
        if not st:
            continue
        # --- status ---
        app_status = JIRA_TO_APP.get(st["status"], st["status"]) if st.get("status") else None
        if app_status and app_status != e.status:
            prev = e.status
            e.status = app_status
            if app_status in CLOSED_STATES:
                e.resolved_at = st.get("resolutiondate") or _now()  # real Jira resolution time
                closed += 1
            else:
                if e.resolved_at:
                    reopened += 1
                e.resolved_at = None
            db.add(TicketEvent(error_id=e.id, jira_issue_key=e.jira_issue_key, from_status=prev,
                               to_status=app_status, actor="jira-sync", occurred_at=_now(),
                               note="Synced from Jira (status changed there to '%s')." % st["status"]))
            updates += 1
        # NOTE: assignee sync is intentionally omitted until real Jira users are mapped to our
        # owner model + last-known assignee is tracked (otherwise a single-user sandbox, where the
        # Jira assignee never matches the fictional routed names, would false-flag every ticket).
    db.commit()
    return {"polled": len(states), "status_updates": updates, "closed": closed, "reopened": reopened}


if __name__ == "__main__":
    db = SessionLocal()
    try:
        print(sync_from_jira(db, get_ticket_sink()))
    finally:
        db.close()
