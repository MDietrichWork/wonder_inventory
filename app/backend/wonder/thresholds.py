"""Bridge the editable config tables (facility_threshold, waste_action_combo) into reference's live
state.

Finders read thresholds via reference.waste_daily_threshold / adjust_daily_threshold and the waste
action allowlist via reference.waste_action_combos (all pure, no DB). Call refresh(db) wherever the
DB is in hand and current values matter — at the start of a validation run and when building the
bootstrap — so edits made in Admin take effect without a restart.
"""
from sqlalchemy import select

from .models import FacilityThreshold, WasteActionCombo
from . import reference


def refresh(db):
    """Load the editable config tables into reference's live state; returns the threshold rows."""
    rows = list(db.scalars(select(FacilityThreshold)))
    reference.set_threshold_bands(rows)
    reference.set_waste_combos(db.scalars(select(WasteActionCombo)))
    return rows
