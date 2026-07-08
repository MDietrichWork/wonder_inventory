"""Closed-ticket retention: how long resolved / auto-closed tickets are kept in the local DB before
they're purged. Jira remains the system of record, and the trend chart is driven by validation_run
(not error), so purging closed errors is safe and doesn't affect history.

The window is a DB-backed, UI-editable setting (app_setting.closed_retention_days); 0 = keep
forever. purge_closed() runs from the daily batch (jobs/daily.py) and the manual Admin button
(POST /api/retention/purge). Deletion is local only — no Jira calls.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .models import AppSetting, Error, AuditLog
from .status_map import CLOSED_STATES

RETENTION_KEY = "closed_retention_days"
DEFAULT_RETENTION_DAYS = 30


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_retention_days(db) -> int:
    """Configured retention window in days (>= 0). Falls back to the code default when unset."""
    row = db.get(AppSetting, RETENTION_KEY)
    if row is None:
        return DEFAULT_RETENTION_DAYS
    try:
        return max(0, int(row.value))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS


def set_retention_days(db, days: int) -> int:
    """Upsert the retention window (0 = keep forever). Caller commits + audits."""
    days = max(0, int(days))
    row = db.get(AppSetting, RETENTION_KEY)
    if row is None:
        db.add(AppSetting(key=RETENTION_KEY, value=str(days)))
    else:
        row.value = str(days)
    return days


def _cutoff(days: int) -> str:
    """ISO-UTC timestamp `days` ago, in the same fixed-width format resolved_at is stored in
    (routes._now / _auto_close), so a string comparison on resolved_at is a valid time comparison."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expired(db, days: int):
    """Closed tickets whose close time is older than the retention window. Empty when days<=0."""
    if days <= 0:
        return []
    cutoff = _cutoff(days)
    stmt = select(Error).where(
        Error.status.in_(CLOSED_STATES),
        Error.resolved_at.is_not(None),
        Error.resolved_at < cutoff,
    )
    return list(db.scalars(stmt))


def closed_past_window(db, days: int) -> int:
    """How many closed tickets are currently past the retention window (Admin display)."""
    return len(_expired(db, days))


def purge_closed(db, days: int) -> int:
    """Delete closed tickets older than the retention window. Deletes the Error objects one by one
    so the Error.events cascade removes their ticket_event rows. Returns the count deleted."""
    expired = _expired(db, days)
    if not expired:
        return 0
    n = len(expired)
    for e in expired:
        db.delete(e)
    db.add(AuditLog(actor="system", action="purge_closed", entity="error", entity_id="*",
                    before=None, after={"deleted": n, "olderThanDays": days}, at=_now()))
    db.commit()
    return n
