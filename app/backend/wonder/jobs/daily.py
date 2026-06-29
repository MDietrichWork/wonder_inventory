"""The daily batch: run the prior-day validation. Shared by POST /api/run and the in-process
scheduler so both pick the run date the same way and route through the same datasource/sink."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from sqlalchemy import select

from ..models import ValidationRun
from ..datasource import get_datasource
from ..tickets import get_ticket_sink
from . import run_validation


def yesterday_pst() -> str:
    """The most-recently-completed business day in Pacific time. Wonder's data day closes at midnight
    PST (~03:00 ET), so 'yesterday PST' is the freshly-landed partition at run time."""
    today_pst = datetime.now(ZoneInfo("America/Los_Angeles")).date()
    return (today_pst - timedelta(days=1)).isoformat()


def run_daily(db, run_date: Optional[str] = None) -> ValidationRun:
    """Run validation for `run_date` (explicit) or the daily default = max(yesterday-PST, latest run)
    — the default never regresses behind the latest run, which would spuriously auto-close today's
    issues. Anchors the fixture replay to the target day (no-op for BigQuery)."""
    dates = sorted({d for d in db.scalars(select(ValidationRun.run_date).distinct())})
    if not dates:
        raise RuntimeError("No prior runs; seed the database first.")
    if not run_date:
        run_date = max(yesterday_pst(), dates[-1])
    ds = get_datasource([d for d in dates if d != run_date] + [run_date])
    sink = get_ticket_sink()
    return run_validation(db, run_date, ds, sink)
