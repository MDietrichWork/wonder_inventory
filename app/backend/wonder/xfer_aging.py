"""XFER-04 / XFER-07 aging day-thresholds: how many days a transfer order can go with no pick
activity (XFER-04) / with no receipt after being picked (XFER-07) before it's flagged.

DB-backed + editable in the Admin UI (app_setting table), same pattern as retention.py. Finders
read the live values via reference.xfer_no_pick_days() / xfer_not_received_days() (pure, no DB);
wonder.thresholds.refresh(db) loads app_setting into reference's live state at run/bootstrap time.
"""
from .models import AppSetting

NO_PICK_KEY = "xfer_no_pick_days"
NOT_RECEIVED_KEY = "xfer_not_received_days"


def _get_days(db, key: str, default: int) -> int:
    row = db.get(AppSetting, key)
    if row is None:
        return default
    try:
        return max(0, int(row.value))
    except (TypeError, ValueError):
        return default


def _set_days(db, key: str, days: int) -> int:
    days = max(0, int(days))
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=str(days)))
    else:
        row.value = str(days)
    return days


def get_no_pick_days(db) -> int:
    from . import reference
    return _get_days(db, NO_PICK_KEY, reference.XFER_NO_PICK_DAYS_DEFAULT)


def get_not_received_days(db) -> int:
    from . import reference
    return _get_days(db, NOT_RECEIVED_KEY, reference.XFER_NOT_RECEIVED_DAYS_DEFAULT)


def set_no_pick_days(db, days: int) -> int:
    return _set_days(db, NO_PICK_KEY, days)


def set_not_received_days(db, days: int) -> int:
    return _set_days(db, NOT_RECEIVED_KEY, days)
