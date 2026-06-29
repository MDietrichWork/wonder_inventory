"""In-process daily scheduler — a localhost stand-in for Cloud Scheduler.

When SCHEDULER_ENABLED=true, runs the prior-day validation every night (SCHEDULER_HOUR:MINUTE in
Pacific time) so an always-open console auto-refreshes with the new day's exceptions. Also catches up
once at startup if the latest run is behind yesterday (covers the app being off overnight).

At go-live this stays OFF and Cloud Scheduler drives POST /api/run instead, so the job isn't
double-triggered. The actual run logic is shared with the endpoint via jobs.daily.run_daily.
"""
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import ValidationRun
from .jobs.daily import run_daily, yesterday_pst

log = logging.getLogger("wonder.scheduler")
_PST = ZoneInfo("America/Los_Angeles")
_scheduler = None


def _run_daily_job():
    db = SessionLocal()
    try:
        run = run_daily(db)
        log.info("daily validation ran for %s: scanned=%s seen=%s new=%s autoClosed=%s",
                 run.run_date, run.rows_scanned, run.error_count, run.new_count, run.autoclosed_count)
    except Exception:  # pragma: no cover - logged, never crash the scheduler thread
        log.exception("daily validation job failed")
    finally:
        db.close()


def _catch_up():
    """If the latest run is behind yesterday-PST, run once now (the app was off overnight)."""
    db = SessionLocal()
    try:
        latest = db.scalar(select(ValidationRun.run_date).order_by(ValidationRun.run_date.desc()))
        if latest and latest < yesterday_pst():
            log.info("startup catch-up: latest run %s is behind %s — running now", latest, yesterday_pst())
            _run_daily_job()
    finally:
        db.close()


def start():
    """Start the nightly job (idempotent). No-op when SCHEDULER_ENABLED is false."""
    global _scheduler
    if not settings.scheduler_enabled or _scheduler is not None:
        return
    if settings.scheduler_catchup_on_start:
        _catch_up()
    _scheduler = BackgroundScheduler(timezone=_PST)
    # Pass the tz to the trigger explicitly — scheduler-level tz isn't reliably inherited and the job
    # would otherwise fire in the host's local zone (e.g. 00:15 ET = 21:15 PT, before the data lands).
    _scheduler.add_job(_run_daily_job,
                       CronTrigger(hour=settings.scheduler_hour, minute=settings.scheduler_minute, timezone=_PST),
                       id="daily-validation", replace_existing=True, misfire_grace_time=3600, coalesce=True)
    _scheduler.start()
    log.info("daily scheduler started — runs %02d:%02d America/Los_Angeles",
             settings.scheduler_hour, settings.scheduler_minute)


def shutdown():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
