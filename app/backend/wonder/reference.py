"""Reference/seed data shared by the seeder and the API bootstrap.

Severity + SLA follow the locked model: Urgent (same day) / High (1d) / Medium (2d) /
Low (5d). Owner groups follow the validation framework (SC Product (IMS), Field Ops,
Procurement, Accounting (Cost Accountant), HDR Field Ops).
"""

FACILITIES = [
    {"id": "IK-NYC-01", "type": "Infinite Kitchen"},
    {"id": "IK-LA-02", "type": "Infinite Kitchen"},
    {"id": "CK-CHI-01", "type": "Central Kitchen"},
    {"id": "DIS-ATL-01", "type": "Distribution"},
    {"id": "DIS-DAL-02", "type": "Distribution"},
    {"id": "TW-001", "type": "Transfer Warehouse"},
]

SYSTEMS = ["Pantry", "Ship Hero", "Fishbowl"]

# The ledger (`system_of_origin`) and the PO table (`po_source_system`) spell the same systems
# differently (e.g. "Shiphero" vs "ShipHero", "Ship Hero"). Canonicalize on read so a system isn't
# split across donut slices / filter options. Unknown systems pass through trimmed.
_SYSTEM_CANON = {
    "shiphero": "ShipHero",
    "fishbowl": "Fishbowl",
    "pantry": "Pantry",
    "extensiv": "Extensiv",
    "extensiv(manual)": "Extensiv (Manual)",
    "ordergrid-external": "OrderGrid - External",
    "eddon": "Ed Don",
    "system": "System",
}


def canon_system(s):
    if not s:
        return s
    return _SYSTEM_CANON.get("".join(s.split()).lower(), s.strip())

TEAMS = {
    "SC Product (IMS)": ["Pavel Romanov", "Sarah Chen", "Marcus Webb"],
    "Field Ops": ["Diego Alvarez", "Priya Nair"],
    "Field Ops — IKC": ["Diego Alvarez"],        # selling units (facility_type HDR)
    "Field Ops — ProdCo": ["Priya Nair"],         # Central Kitchen + Distribution (facility_type CK/DISH/PRODUCTION)
    "Procurement": ["Tom Becker", "Lena Ortiz"],
    "Accounting (Cost Accountant)": ["Mike Dietrich"],
}

# Over-receipt routing is facility-type-aware (Pavel): the selling IKC units (facility_type 'HDR')
# go to Field Ops — IKC; Central Kitchen / Distribution / Production go to Field Ops — ProdCo.
# Anything unrecognized falls through to ProdCo. facility_type is read from the finding snapshot.
FACILITY_TYPE_TEAM = {
    "HDR": "Field Ops — IKC",
    "CK": "Field Ops — ProdCo",
    "DISH": "Field Ops — ProdCo",
    "PRODUCTION": "Field Ops — ProdCo",
}
_DEFAULT_OVER_RECEIPT_TEAM = "Field Ops — ProdCo"


def field_ops_facility_route(facility_type):
    """(team, assignee) for a facility-scoped Field Ops finding, chosen by facility_type bucket.
    Used by over-receipt and daily-waste routing."""
    team = FACILITY_TYPE_TEAM.get((facility_type or "").strip().upper(), _DEFAULT_OVER_RECEIPT_TEAM)
    assignee = (TEAMS.get(team) or ["Unassigned"])[0]
    return team, assignee


# Back-compat alias (PO_OVER_RECEIPT routing).
over_receipt_route = field_ops_facility_route


# Daily waste $ per facility per day -> exception (WASTE_DAILY_FACILITY), by facility_type bucket,
# with two severity bands (High / Urgent). Tuned 2026-06-11 to the observed net-waste $ distribution
# at the REAL ERP standard cost (14-day): High ≈ p90, Urgent ≈ p99/extreme per type, so only outlier
# days flag, not routine ones. Revisit as more days accrue / volume scales (Pavel may add effectivity
# dates later). HDR = small selling units; DISH = distribution; CK/PRODUCTION = kitchens.
WASTE_DAILY_THRESHOLDS = {
    "HDR":        {"high": 1_000,  "urgent": 3_000},    # p90 $398 / p99 $950 / max $5.4k
    "DISH":       {"high": 40_000, "urgent": 65_000},   # p50 $15.8k / max $67.8k
    "CK":         {"high": 15_000, "urgent": 30_000},   # mirrors PRODUCTION (no CK-tagged days observed)
    "PRODUCTION": {"high": 15_000, "urgent": 30_000},   # p50 $4.2k / p90 $25.9k
}
_DEFAULT_WASTE_THRESHOLD = {"high": 10_000, "urgent": 25_000}

# Daily ABSOLUTE adjustment $ per facility per day -> exception (ADJ_DAILY_FACILITY). Same Adjust
# activity / cost as waste, but the magnitude (SUM |per-SKU net x cost|) instead of the signed net,
# so a loss + offsetting recovery still counts as churn. Seeded 2026-06-16 to the observed 5-day
# distribution (06-11..06-15) at real ERP cost: High ≈ p90, Urgent ≈ p99 per facility type. HDR is
# the solid sample (130 facilities); DISH/PRODUCTION are provisional (1-2 facilities) — revisit as
# days accrue. (One $8M single-day DISH spike — Shawnee 06-11 — is the kind of event this catches.)
ADJ_DAILY_THRESHOLDS = {
    "HDR":        {"high": 750,    "urgent": 1_600},    # p90 $746 / p99 $1,636 / max $1,968 (n=650)
    "DISH":       {"high": 90_000, "urgent": 150_000},  # normal facility $24k-$93k/day; provisional
    "CK":         {"high": 30_000, "urgent": 40_000},   # mirrors PRODUCTION (no CK-tagged days observed)
    "PRODUCTION": {"high": 30_000, "urgent": 40_000},   # CK1 $2k-$38k/day, UoM-undercounted; provisional
}
_DEFAULT_ADJ_THRESHOLD = {"high": 10_000, "urgent": 25_000}

# error_type -> (per-facility_type default bands, global fallback band). The code defaults; the live
# values can be edited in the Admin UI and are stored in the facility_threshold table (see
# wonder.thresholds.refresh, which loads them into _THRESHOLD_BANDS at run/bootstrap time).
_THRESHOLD_DEFAULTS = {
    "WASTE_DAILY_FACILITY": (WASTE_DAILY_THRESHOLDS, _DEFAULT_WASTE_THRESHOLD),
    "ADJ_DAILY_FACILITY":   (ADJ_DAILY_THRESHOLDS,  _DEFAULT_ADJ_THRESHOLD),
}


def _default_bands():
    import copy
    return {et: copy.deepcopy(per_ft) for et, (per_ft, _g) in _THRESHOLD_DEFAULTS.items()}


# Live, possibly DB-overridden bands: {error_type: {FACILITY_TYPE: {"high","urgent"}}}. Starts at the
# code defaults; wonder.thresholds.refresh(db) replaces it from the facility_threshold table.
_THRESHOLD_BANDS = _default_bands()


def set_threshold_bands(rows):
    """Replace the live bands from DB rows (each having .error_type/.facility_type/.high/.urgent),
    starting from the code defaults so any gap still resolves."""
    global _THRESHOLD_BANDS
    bands = _default_bands()
    for r in rows:
        ft = (r.facility_type or "").strip().upper()
        bands.setdefault(r.error_type, {})[ft] = {"high": r.high, "urgent": r.urgent}
    _THRESHOLD_BANDS = bands


def default_threshold_rows():
    """Seed rows for the facility_threshold table: every defined (error_type, facility_type) band."""
    for et, (per_ft, _g) in _THRESHOLD_DEFAULTS.items():
        for ft, band in per_ft.items():
            yield {"error_type": et, "facility_type": ft, "high": band["high"], "urgent": band["urgent"]}


def daily_threshold(error_type, facility_type):
    """{'high': X, 'urgent': Y} daily $ bands for an (error_type, facility_type) bucket — live values
    (DB-editable) with the code default as the fallback for an unknown facility type."""
    ft = (facility_type or "").strip().upper()
    et_bands = _THRESHOLD_BANDS.get(error_type, {})
    if ft in et_bands:
        return et_bands[ft]
    _per_ft, glob = _THRESHOLD_DEFAULTS.get(error_type, (None, _DEFAULT_WASTE_THRESHOLD))
    return glob


# ---- Daily-waste action allowlist -----------------------------------------------------------------
# The explicit set of ledger (l1_action, l2_action) movements that count as "waste" for the Daily
# Waste rule, approved by Pavel 2026-06-17. This REPLACES the earlier definition (l1_action='Adjust'
# minus a few transfer/admin l2s) with a curated allowlist so the team can add/remove specific
# actions in Admin as the upstream action taxonomy is cleaned up. DB-backed + editable in the Admin
# UI (waste_action_combo table); this list is the code default / seed. The net-$ math is unchanged —
# losses (negative qty change) net against recoveries (positive), valued at standard cost.
WASTE_ACTION_COMBOS = [
    ("Add", "Find for Removal"),
    ("Add", "Found During Move"),
    ("Add", "Serial discovery during move"),
    ("Adjust", "Adjusted Partial"),
    ("Adjust", "Clear Location"),
    ("Adjust", "Cycle Count"),
    ("Adjust", "Cycle Counted"),
    ("Adjust", "DISH Issue/Received Damaged"),
    ("Adjust", "Damage"),
    ("Adjust", "Expiration"),
    ("Adjust", "Found"),
    ("Adjust", "Found Items"),
    ("Adjust", "Hot Hold Request Shortage Reported"),
    ("Adjust", "Hot Hold Shortage Reported upon Cook Request"),
    ("Adjust", "Location Counted"),
    ("Adjust", "Lost"),
    ("Adjust", "Missing Items"),
    ("Adjust", "Partials Conversion"),
    ("Adjust", "Recall"),
    ("Adjust", "Recall Production"),
    ("Adjust", "Self-Directed Location Count"),
    ("Cycle Count", "Sent to Virtual from IMSWeb"),
    ("Cycle Count", "Unload Clear LP"),
    ("Remove", "3.0 Conversion"),
    ("Remove", "Auto-Expired"),
    ("Remove", "Batch Purge"),
    ("Remove", "Clear Location"),
    ("Remove", "Cleared from IMS Web"),
    ("Remove", "Cycle Count"),
    ("Remove", "DISH Issue/Received Damaged"),
    ("Remove", "Damage"),
    ("Remove", "Damaged"),
    ("Remove", "Donation"),
    ("Remove", "Dropped"),
    ("Remove", "Error"),
    ("Remove", "Expiration"),
    ("Remove", "Expire"),
    ("Remove", "Expire Transformed Item"),
    ("Remove", "Expired"),
    ("Remove", "Expired Prepped Item"),
    ("Remove", "Faulty Kit"),
    ("Remove", "Food Quality"),
    ("Remove", "Food Quality Issue"),
    ("Remove", "Hot Holding"),
    ("Remove", "Hot Holding Expiration"),
    ("Remove", "I made an error"),
    ("Remove", "Inventory Inspection"),
    ("Remove", "Item not in Stockable BOMs"),
    ("Remove", "Items Not Present"),
    ("Remove", "Items not Present - Web"),
    ("Remove", "Lost"),
    ("Remove", "Marked OOS on KOM"),
    ("Remove", "Misfire"),
    ("Remove", "Non-Food SKU Purge"),
    ("Remove", "Not Received"),
    ("Remove", "Not in hot holding"),
    ("Remove", "Poor Quality"),
    ("Remove", "Purge"),
    ("Remove", "QA"),
    ("Remove", "Received Damaged"),
    ("Remove", "Received Damaged from DISH"),
    ("Remove", "Received Mislabeled"),
    ("Remove", "Received Spoiled"),
    ("Remove", "Received in Error"),
    ("Remove", "Received with Other Quality Issue"),
    ("Remove", "Received without Label"),
    ("Remove", "Seal is Damaged"),
    ("Remove", "Shortage when Moving to Hot Holding"),
    ("Remove", "Spoiled"),
    ("Remove", "Temperature Breach"),
]

# Live, possibly DB-overridden allowlist (list of (l1_action, l2_action) tuples). Starts at the code
# default; wonder.thresholds.refresh(db) replaces it from the waste_action_combo table (enabled rows).
_WASTE_COMBOS = list(WASTE_ACTION_COMBOS)


def set_waste_combos(rows):
    """Replace the live waste-action allowlist from DB rows (each having .l1_action/.l2_action and
    an .enabled flag); only enabled combos are kept. An empty table (un-migrated/un-seeded DB) falls
    back to the code defaults so the waste rule never silently goes dark; a populated table with every
    combo disabled is honored as-is (the user turned them all off)."""
    global _WASTE_COMBOS
    rows = list(rows)
    enabled = [(r.l1_action, r.l2_action) for r in rows if getattr(r, "enabled", True)]
    _WASTE_COMBOS = enabled if rows else list(WASTE_ACTION_COMBOS)


def default_waste_combo_rows():
    """Seed rows for the waste_action_combo table: every approved (l1_action, l2_action), enabled."""
    for l1, l2 in WASTE_ACTION_COMBOS:
        yield {"l1_action": l1, "l2_action": l2, "enabled": True}


def waste_action_combos():
    """The live allowlist of (l1_action, l2_action) movements that count as waste (DB-editable)."""
    return list(_WASTE_COMBOS)


def waste_daily_sql(combos=None):
    """Render the read-only reference SQL shown for the Daily Waste rule, listing the given waste-action
    combos (defaults to the approved set). Mirrors the real finder (bq_finder._daily_waste_rows): the
    NET of the allowlisted movements per (facility, day), valued at ERP standard cost, flagged when the
    net loss clears the facility-type threshold. The live predicate is built the same way — a
    CONCAT(l1_action,'||',l2_action) IN (...) match over exactly these pairs."""
    combos = list(WASTE_ACTION_COMBOS if combos is None else combos)
    pairs = ",\n".join("       '%s||%s'" % (l1, l2) for (l1, l2) in combos) \
        or "       -- (allowlist empty — nothing counts as waste)"
    return (
        "-- A facility's total NET waste $ for a day vs its facility-type threshold, banded High/Urgent\n"
        "-- (reference.WASTE_DAILY_THRESHOLDS). 'Waste' = an editable allowlist of (l1_action, l2_action)\n"
        "-- movements approved by Pavel — add/remove/toggle them under this rule in Admin. NET over those\n"
        "-- movements (losses net against Found / cycle-count recoveries), valued at ERP standard cost;\n"
        "-- only facility-days whose net loss clears the threshold flag.\n"
        "WITH cost AS ( /* latest-activated ERP standard cost per ITEMID (= consumable_sku) */ )\n"
        "SELECT l.facility_name, l.facility_type, DATE(l.datetime_utc) AS day,\n"
        "       ROUND(SUM(-l.consumable_quantity_change * cost.unit_cost), 0) AS waste_dollars\n"
        "FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger` l\n"
        "LEFT JOIN cost ON CAST(l.consumable_sku AS STRING) = cost.ITEMID\n"
        "WHERE CONCAT(l.l1_action, '||', l.l2_action) IN (   -- %d approved waste actions (editable in Admin)\n"
        % len(combos)
        + pairs + "\n"
        ")\n"
        "GROUP BY l.facility_name, l.facility_type, day\n"
        "HAVING waste_dollars > 0   -- net loss only\n"
        "ORDER BY waste_dollars DESC"
    )


def _fmt_money(v):
    return ("%d" % v) if float(v).is_integer() else ("%g" % v)


def threshold_case_sql(error_type, facility_type_col, field):
    """A BigQuery CASE expression mapping facility_type -> the live `field` ('high'/'urgent') $
    threshold for `error_type`, with the global default as ELSE. Lets the copy-paste reference SQL
    apply the same per-facility-type bands the validator applies in Python."""
    bands = _THRESHOLD_BANDS.get(error_type, {})
    whens = "".join(" WHEN '%s' THEN %s" % (ft, _fmt_money(band[field])) for ft, band in bands.items())
    _per_ft, glob = _THRESHOLD_DEFAULTS.get(error_type, (None, _DEFAULT_WASTE_THRESHOLD))
    return "CASE UPPER(%s)%s ELSE %s END" % (facility_type_col, whens, _fmt_money(glob[field]))


def waste_daily_threshold(facility_type):
    """{'high': X, 'urgent': Y} daily-waste $ thresholds for a facility_type bucket."""
    return daily_threshold("WASTE_DAILY_FACILITY", facility_type)


def adjust_daily_threshold(facility_type):
    """{'high': X, 'urgent': Y} daily absolute-adjustment $ thresholds for a facility_type bucket."""
    return daily_threshold("ADJ_DAILY_FACILITY", facility_type)

MOVEMENT_TYPES = ["PO Receipt", "Transfer", "Production", "Sales / Outbound", "Expiration", "Adjustment"]

# SLA resolution targets in days (Urgent = same day = 0)
SLA_TARGETS = {"Urgent": 0, "High": 1, "Medium": 2, "Low": 5}

ERROR_TYPES = [
    {"type": "NULL_PO_NUMBER", "rule": "PO number present", "ruleType": "NOT_NULL",
     "owner": "SC Product (IMS)", "desc": "PO-receipt / Add transaction is missing a PO reference."},
    {"type": "PO_RECORD_MISSING", "rule": "PO exists in PO table", "ruleType": "REFERENTIAL",
     "owner": "SC Product (IMS)", "desc": "Ledger PO reference has no matching row in the PO table."},
    {"type": "PO_OVER_RECEIPT", "rule": "Receipt within ordered qty", "ruleType": "RANGE",
     "owner": "Field Ops", "desc": "Received quantity exceeds the quantity ordered on the PO. Severity by magnitude: 30–99% over → High (a supply-chain signal — possible unsolicited / over-shipment), ≥100% over (received ≥2× ordered) → Urgent (a likely receiving error — double-receive / fat-finger). Routed by facility type: HDR (selling units) → Field Ops — IKC; CK / DISH / Production → Field Ops — ProdCo."},
    {"type": "PO_IMPLAUSIBLE_QTY", "rule": "Received qty is physically plausible", "ruleType": "RANGE",
     "owner": "SC Product (IMS)", "desc": "DEPRECATED — folded into PO_OVER_RECEIPT (≥100% over → Urgent) as of the facility-routing change. Kept so historical tickets still render; no longer emitted."},
    {"type": "PO_UOM_MISMATCH", "rule": "PO/ledger consumable UoM match", "ruleType": "RECONCILIATION",
     "owner": "Procurement", "desc": "Consumable UoM on the PO differs from the ledger receipt — ordered vs received aren't comparable until the UoM/conversion is reconciled (excluded from the over-receipt % rule)."},
    {"type": "TRANSFER_WAREHOUSE_IMBALANCE", "rule": "Transfer Warehouse balances", "ruleType": "RECONCILIATION",
     "owner": "Field Ops", "desc": "Shipped vs received quantity mismatch leaves aged stock in the Transfer Warehouse."},
    {"type": "NEGATIVE_ON_HAND", "rule": "On-hand >= 0", "ruleType": "RANGE",
     "owner": "SC Product (IMS)", "desc": "Cumulative on-hand quantity went negative for an item / location."},
    {"type": "PO_MISSING_PRICE", "rule": "Vendor SKU price present", "ruleType": "NOT_NULL",
     "owner": "Procurement", "desc": "Purchase PO line has a $0.00 or NULL vendor (supplier) price — the receipt can't be costed into the GL until a price is set."},
    {"type": "PO_MISSING_NUMBER", "rule": "PO number present (master table)", "ruleType": "NOT_NULL",
     "owner": "SC Product (IMS)", "desc": "A row in the PO master table has a NULL/blank PO number — a broken master record with nothing to receive against. Safety-net rule: currently finds 0 on live data, kept to catch upstream degradation."},
    {"type": "PO_SKU_NOT_ON_PO", "rule": "Received SKU listed on the PO", "ruleType": "REFERENTIAL",
     "owner": "SC Product (IMS)", "desc": "A consumable SKU was received against a PO (ledger ref_order_id) that exists, but that SKU isn't on the PO's lines — a 3-way-match break: wrong item received, an undocumented substitution, or a PO line never set up. (Framework catalog PO-02.)"},
    {"type": "TRANSFER_ORDER_MISSING", "rule": "Picked Transfer Order exists", "ruleType": "REFERENTIAL",
     "owner": "SC Product (IMS)", "desc": "Items were picked (Transfer Out) against a Transfer Order whose ID is not in the transfer-order population (the orders table, order_type='Transfer') — picking against a non-existent transfer order. (Framework catalog XFER-01.)"},
    {"type": "WASTE_DAILY_FACILITY", "rule": "Daily facility waste within threshold", "ruleType": "RANGE",
     "owner": "Field Ops", "desc": "A facility's total NET waste $ for a day exceeds its facility-type threshold (small for IKC/HDR selling units, larger for CK/DISH/Production). NET over an editable allowlist of (l1_action, l2_action) movements that count as waste — approved by Pavel and editable in Admin (Add/remove/toggle combos under the Daily Waste rule) — so losses (Lost, Expiration, Damage, Recall, spoilage, cycle-count shrink, …) net against Found / cycle-count recoveries of the same item; valued at standard cost. Two bands: over the High threshold → High, over the Urgent threshold → Urgent. The drawer lists the top loss-contributing SKUs (sorted) — investigation is the team's job. Routed by facility type (HDR → Field Ops/IKC; CK/DISH/PRODUCTION → Field Ops/ProdCo)."},
    {"type": "ADJ_DAILY_FACILITY", "rule": "Daily facility adjustments within threshold", "ruleType": "RANGE",
     "owner": "Field Ops", "desc": "A facility's total ABSOLUTE adjustment $ for a day exceeds its facility-type threshold. Same Adjust activity and standard cost as Daily Waste, but the magnitude — SUM(|per-SKU net x cost|) — instead of the signed net, so a same-day loss and an offsetting recovery still count as adjustment churn (waste would net them to ~$0). Catches abnormal adjustment volume even when it nets out. Two bands: over High → High, over Urgent → Urgent. Routed by facility type (HDR → Field Ops/IKC; CK/DISH/PRODUCTION → Field Ops/ProdCo). Thresholds are editable in Admin."},
    {"type": "WASTE_SKU_NO_COST", "rule": "Waste SKU has a standard-cost record", "ruleType": "RECONCILIATION",
     "owner": "Accounting (Cost Accountant)", "desc": "A consumable SKU with waste/adjustment activity has NO matching standard-cost record in the ERP cost table (no ITEMID match) — its waste cannot be valued at all, so it silently drops out of the waste $. A standard cost must be set up in Dynamics for this item."},
    {"type": "CONSUMABLE_ZERO_COST", "rule": "Consumable SKU has a non-zero standard cost", "ruleType": "NOT_NULL",
     "owner": "Accounting (Cost Accountant)", "desc": "A consumable SKU active in the ledger HAS a standard-cost record, but its ERP standard cost is $0.00 or NULL — so any valuation (waste, on-hand, COGS) for this item is wrong/zero. The standard cost must be corrected in Dynamics. (Framework catalog #66.)"},
]

# Human-readable display labels for each error_type code. The code stays the stable internal key
# (DB, routing, fingerprints, auto-close filters); these labels are what the console + Jira titles
# show. Keep domain acronyms (PO, SKU, UoM) — users know them.
ERROR_TYPE_LABELS = {
    "NULL_PO_NUMBER": "Inventory Log Missing PO Number",
    "PO_RECORD_MISSING": "PO Record Missing",
    "PO_OVER_RECEIPT": "PO Over Receipt",
    "PO_IMPLAUSIBLE_QTY": "PO Implausible Quantity",
    "PO_UOM_MISMATCH": "PO UoM Mismatch",
    "TRANSFER_WAREHOUSE_IMBALANCE": "Transfer Warehouse Imbalance (WIP)",
    "NEGATIVE_ON_HAND": "Negative On-Hand",
    "PO_MISSING_PRICE": "PO Missing Price",
    "PO_MISSING_NUMBER": "PO Table Missing PO Number",
    "PO_SKU_NOT_ON_PO": "SKU Not on PO",
    "TRANSFER_ORDER_MISSING": "Transfer Order Missing (WIP)",
    "WASTE_DAILY_FACILITY": "Daily Waste (Facility)",
    "ADJ_DAILY_FACILITY": "Daily Adjustments (Facility)",
    "WASTE_SKU_NO_COST": "Waste SKU Without Cost",
    "CONSUMABLE_ZERO_COST": "Consumable Missing Cost",
}


def error_label(error_type):
    """Human-readable name for an error_type code (falls back to the code itself)."""
    return ERROR_TYPE_LABELS.get(error_type, error_type)


# Plain-English, jargon-free explanation of each exception — what it means in one or two sentences,
# for someone who doesn't know the data model. Shown in the rule editor ("What this checks"). Kept
# separate from `desc` (which carries the fuller, more technical detail shown in the ticket drawer).
ERROR_TYPE_PLAIN = {
    "NULL_PO_NUMBER": "A receiving record came in with no purchase-order number attached, so we can't tell which order it belongs to.",
    "PO_RECORD_MISSING": "We received items against a purchase-order number that isn't in our PO records — the receipt points at a PO we can't find.",
    "PO_OVER_RECEIPT": "We received more of an item than the purchase order actually ordered. A little over can be an over-shipment; a lot over (2× or more) is usually a receiving mistake like a double-scan.",
    "PO_IMPLAUSIBLE_QTY": "No longer used on its own — these are now reported as PO Over Receipt.",
    "PO_UOM_MISMATCH": "The unit of measure on the purchase order (say, cases) doesn't match the unit it was received in (say, eaches), so ordered vs received can't be compared until the units are lined up.",
    "TRANSFER_WAREHOUSE_IMBALANCE": "What shipped out of the transfer warehouse doesn't equal what was received, so stock is stuck in limbo between locations.",
    "NEGATIVE_ON_HAND": "Our records say there's less than zero of an item on hand — physically impossible, so a transaction is missing or wrong.",
    "PO_MISSING_PRICE": "A purchase-order line has no vendor price (it's blank or $0), so the receipt can't be costed into the books.",
    "PO_MISSING_NUMBER": "A row in the purchase-order master table has no PO number at all — a broken record with nothing to receive against.",
    "PO_SKU_NOT_ON_PO": "An item was received against a real purchase order, but that item isn't listed on the PO — a wrong item, an undocumented substitution, or a PO line that was never set up.",
    "TRANSFER_ORDER_MISSING": "Items were picked for a transfer order that doesn't exist in our records.",
    "WASTE_DAILY_FACILITY": "One facility's net waste in dollars for a single day is unusually high — above what's normal for that type of facility.",
    "ADJ_DAILY_FACILITY": "A facility made an unusually large dollar amount of inventory adjustments in one day (even ones that cancel out) — a sign of abnormal counting or correction activity.",
    "WASTE_SKU_NO_COST": "An item that's being wasted has no standard cost set up, so we can't put a dollar value on its waste — it silently drops out of the totals.",
    "CONSUMABLE_ZERO_COST": "An item's standard cost is $0 or blank, so every dollar figure we calculate for it — waste, on-hand, cost of goods — comes out wrong.",
}


def error_plain(error_type):
    """Plain-English explanation of an error_type (falls back to the detailed desc, then the code)."""
    if error_type in ERROR_TYPE_PLAIN:
        return ERROR_TYPE_PLAIN[error_type]
    for et in ERROR_TYPES:
        if et["type"] == error_type:
            return et["desc"]
    return error_type


# Seed validation rules (rule_key drawn from the framework catalog where applicable).
RULES = [
    {"id": "PO-01", "name": "PO number present", "primitive": "NOT_NULL", "error_type": "NULL_PO_NUMBER",
     "target_table": "unified_ledger", "severity": "Urgent", "fail_type": "Hard", "owner_group": "SC Product (IMS)",
     "params": {"column": "po_number", "where": {"txn_type": ["PO_RECEIPT", "ADD"]}},
     "expression": (
        "-- Catalog rule (framework PO-01). Documents the check; NOT yet wired into the daily finder,\n"
        "-- so it produces no exceptions today. A PO-order-type receiving row that carries no PO id.\n"
        "DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);\n"
        "SELECT _id, datetime_utc, facility_name, system_of_origin, l1_action, l2_action,\n"
        "       consumable_sku, item_name, ref_order_type, ref_order_id\n"
        "FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`\n"
        "WHERE ref_order_type = 'Purchase Order'\n"
        "  AND (ref_order_id IS NULL OR TRIM(ref_order_id) = '')\n"
        "  AND DATE(datetime_utc) = run_date\n"
        "ORDER BY datetime_utc DESC"
     ), "enabled": True},
    {"id": "PO-02", "name": "PO exists in PO table", "primitive": "REFERENTIAL", "error_type": "PO_RECORD_MISSING",
     "target_table": "unified_ledger", "severity": "High", "fail_type": "Hard", "owner_group": "SC Product (IMS)",
     "params": {"column": "po_number", "ref_table": "po_table", "ref_column": "po_number",
                "where": {"txn_type": ["PO_RECEIPT"]}},
     "expression": (
        "-- Catalog rule (framework PO-02). NOT yet wired into the daily finder. A ledger PO receipt\n"
        "-- whose PO id has no matching row in the PO master (orphan reference). See PO-14 for the\n"
        "-- SKU-level 3-way match that IS live.\n"
        "DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);\n"
        "WITH po_master AS (\n"
        "  SELECT DISTINCT po FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`\n"
        "  WHERE order_type = 'Purchase' AND po IS NOT NULL\n"
        ")\n"
        "SELECT l.ref_order_id AS po, ANY_VALUE(l.facility_name) AS facility,\n"
        "       ANY_VALUE(l.system_of_origin) AS system, COUNT(*) AS receipt_rows,\n"
        "       MIN(DATE(l.datetime_utc)) AS first_seen, MAX(DATE(l.datetime_utc)) AS last_seen\n"
        "FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger` l\n"
        "LEFT JOIN po_master m ON l.ref_order_id = m.po\n"
        "WHERE l.ref_order_type = 'Purchase Order' AND l.ref_order_id IS NOT NULL\n"
        "  AND m.po IS NULL AND DATE(l.datetime_utc) = run_date\n"
        "GROUP BY po\n"
        "ORDER BY receipt_rows DESC"
     ), "enabled": True},
    {"id": "PO-03", "name": "PO receipt within ordered quantity", "primitive": "OVER_RECEIPT",
     "error_type": "PO_OVER_RECEIPT", "target_table": "consolidated_inventory_ledger ⋈ int_ledger_purchase_orders",
     "severity": "High", "fail_type": "Soft", "owner_group": "Field Ops",
     "params": {},  # thresholds come from settings (over_receipt_high_pct / over_receipt_urgent_pct)
     "expression": (
        "-- DAILY BATCH PO over-receipt: flag POs that RECEIVED yesterday, then compare their\n"
        "-- cumulative received-to-date vs ordered. Join ledger.ref_order_id -> PO `po`; item link =\n"
        "-- consumable_sku (both); received = SUM(ledger.consumable_quantity_change), only ref_order_type='Purchase Order'.\n"
        "DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday\n"
        "WITH touched AS (   -- (po, item) received on run_date\n"
        "  SELECT DISTINCT ref_order_id AS po, consumable_sku\n"
        "  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`\n"
        "  WHERE ref_order_type='Purchase Order' AND consumable_sku IS NOT NULL AND DATE(datetime_utc)=run_date),\n"
        "received AS (       -- cumulative received-to-date for those POs (30d lookback)\n"
        "  SELECT l.ref_order_id AS po, l.consumable_sku, SUM(l.consumable_quantity_change) AS received_qty,\n"
        "         ANY_VALUE(l.consumable_uom) AS received_uom\n"
        "  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger` l\n"
        "  JOIN touched t ON l.ref_order_id=t.po AND l.consumable_sku=t.consumable_sku\n"
        "  WHERE l.ref_order_type='Purchase Order' AND DATE(l.datetime_utc)<=run_date\n"
        "    AND l.datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(run_date), INTERVAL 30 DAY)\n"
        "  GROUP BY po, consumable_sku),\n"
        "ordered AS (\n"
        "  SELECT po, consumable_sku, SUM(consumable_sku_qty) AS ordered_qty, ANY_VALUE(consumable_uom) AS ordered_uom\n"
        "  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`\n"
        "  WHERE consumable_sku IS NOT NULL AND order_type = 'Purchase'  -- PO-side: purchases only\n"
        "  GROUP BY po, consumable_sku)\n"
        "SELECT r.po, r.consumable_sku, o.ordered_qty, o.ordered_uom, r.received_qty, r.received_uom,\n"
        "       (o.ordered_uom != r.received_uom) AS uom_mismatch,\n"
        "       ROUND((SAFE_DIVIDE(r.received_qty,o.ordered_qty)-1)*100,1) AS over_by_pct\n"
        "FROM received r JOIN ordered o USING (po, consumable_sku)\n"
        "WHERE o.ordered_qty>0 AND ( (o.ordered_uom != r.received_uom)        -- UoM mismatch -> PO_UOM_MISMATCH\n"
        "   OR r.received_qty > o.ordered_qty*1.05 )  -- else over-receipt: <=2x genuine, >2x implausible\n"
        "ORDER BY over_by_pct DESC"
     ), "enabled": True},
    {"id": "TWH-01", "name": "Transfer Warehouse balances", "primitive": "RECON_TRANSFER",
     "error_type": "TRANSFER_WAREHOUSE_IMBALANCE", "target_table": "unified_ledger", "severity": "High",
     "fail_type": "Soft", "owner_group": "Field Ops",
     "params": {"facility": "TW-001"},
     "expression": (
        "-- Catalog rule (framework TWH-01) — WIP: transfer-warehouse shipped-vs-received reconciliation.\n"
        "-- NOT yet wired into the daily finder (needs the full transfer-matching model). A transfer whose\n"
        "-- Out and In legs don't balance leaves aged stock in transit.\n"
        "DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);\n"
        "WITH legs AS (\n"
        "  SELECT ref_order_id AS transfer_id,\n"
        "         SUM(IF(l2_action = 'Transfer Out', -consumable_quantity_change, 0)) AS shipped_qty,\n"
        "         SUM(IF(l2_action = 'Transfer In',   consumable_quantity_change, 0)) AS received_qty\n"
        "  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`\n"
        "  WHERE ref_order_type = 'Transfer Order' AND ref_order_id IS NOT NULL\n"
        "  GROUP BY transfer_id\n"
        ")\n"
        "SELECT transfer_id, shipped_qty, received_qty, (shipped_qty - received_qty) AS imbalance_qty\n"
        "FROM legs\n"
        "WHERE shipped_qty <> received_qty\n"
        "ORDER BY ABS(shipped_qty - received_qty) DESC"
     ), "enabled": True},
    {"id": "COMPLETE-02", "name": "On-hand non-negative", "primitive": "RANGE", "error_type": "NEGATIVE_ON_HAND",
     "target_table": "unified_ledger", "severity": "Urgent", "fail_type": "Soft", "owner_group": "SC Product (IMS)",
     "params": {"column": "running_on_hand", "op": "<", "value": 0},
     "expression": (
        "-- Catalog rule (framework COMPLETE-02) — WIP: needs cross-partition cumulative on-hand. Running\n"
        "-- on-hand per (facility, consumable_sku) over the full ledger; flag rows where it dips below 0.\n"
        "DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);\n"
        "WITH ledger AS (\n"
        "  SELECT facility_name, consumable_sku, datetime_utc, consumable_quantity_change,\n"
        "         SUM(consumable_quantity_change) OVER (\n"
        "           PARTITION BY facility_name, consumable_sku ORDER BY datetime_utc\n"
        "           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_on_hand\n"
        "  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`\n"
        "  WHERE consumable_sku IS NOT NULL\n"
        ")\n"
        "SELECT facility_name, consumable_sku, datetime_utc, consumable_quantity_change, running_on_hand\n"
        "FROM ledger\n"
        "WHERE running_on_hand < 0 AND DATE(datetime_utc) = run_date\n"
        "ORDER BY running_on_hand"
     ), "enabled": True},
    {"id": "WASTE-DAILY", "name": "Daily facility waste within threshold", "primitive": "RANGE",
     "error_type": "WASTE_DAILY_FACILITY", "target_table": "consolidated_inventory_ledger",
     "severity": "High", "fail_type": "Soft", "owner_group": "Field Ops",
     "params": {},  # thresholds come from reference.WASTE_DAILY_THRESHOLDS, banded by facility_type
     # Documentation only; the live console regenerates this from the current allowlist (contract.py).
     "expression": waste_daily_sql(), "enabled": True},
    {"id": "ADJ-DAILY", "name": "Daily facility adjustments within threshold", "primitive": "RANGE",
     "error_type": "ADJ_DAILY_FACILITY", "target_table": "consolidated_inventory_ledger",
     "severity": "High", "fail_type": "Soft", "owner_group": "Field Ops",
     "params": {},  # thresholds come from the facility_threshold table (defaults: reference.ADJ_DAILY_THRESHOLDS)
     "expression": (
        "-- A facility's total ABSOLUTE adjustment $ for a day vs its facility-type threshold, banded\n"
        "-- High/Urgent (editable in Admin; defaults reference.ADJ_DAILY_THRESHOLDS). Same Adjust\n"
        "-- activity + standard cost as Daily Waste, but the magnitude SUM(|net x cost|) per SKU, so a\n"
        "-- same-day loss + offsetting recovery still counts as churn (it does NOT net to ~$0).\n"
        "SELECT facility_name, facility_type, DATE(datetime_utc) AS day,\n"
        "       SUM(ABS(net_consumable_quantity_change * unit_cost)) AS abs_adjust_dollars\n"
        "FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger` JOIN <standard_cost>\n"
        "WHERE l1_action='Adjust' AND l2_action NOT IN ('Move From','Move To','Update Received Order','Shelf Life Extension')\n"
        "GROUP BY facility_name, facility_type, day"
     ), "enabled": True},
    {"id": "COST-01", "name": "Waste SKU has a standard-cost record", "primitive": "RECONCILIATION",
     "error_type": "WASTE_SKU_NO_COST", "target_table": "consolidated_inventory_ledger ⋈ erp standard cost",
     "severity": "High", "fail_type": "Hard", "owner_group": "Accounting (Cost Accountant)",
     "params": {},  # all unmatched waste SKUs (small population)
     "expression": (
        "-- A consumable_sku with waste/adjust activity that has NO row in the ERP standard-cost table\n"
        "-- (ITEMID), so its waste can't be valued. LEFT JOIN waste-active SKUs -> cost; flag the misses.\n"
        "SELECT w.consumable_sku FROM (waste-active consumable_sku) w\n"
        "LEFT JOIN (erp standard cost, ITEMID) c ON CAST(w.consumable_sku AS STRING)=c.ITEMID\n"
        "WHERE c.ITEMID IS NULL"
     ), "enabled": True},
    {"id": "COST-02", "name": "Consumable SKU has a non-zero standard cost", "primitive": "RECONCILIATION",
     "error_type": "CONSUMABLE_ZERO_COST", "target_table": "consolidated_inventory_ledger ⋈ erp standard cost",
     "severity": "High", "fail_type": "Hard", "owner_group": "Accounting (Cost Accountant)",
     "params": {"test_cap": 5},  # 600+ in the backlog; capped to a sample for now (Jira testing)
     "expression": (
        "-- Framework #66: a consumable_sku active in the ledger whose ERP standard cost (PRICE/PRICEUNIT)\n"
        "-- is 0 or NULL — can't be costed. JOIN ledger SKUs -> cost; flag unit_cost IS NULL OR = 0.\n"
        "-- 600+ in the backlog; capped to a small sample while testing the Jira flow.\n"
        "SELECT l.consumable_sku, c.unit_cost FROM (ledger consumable_sku) l\n"
        "JOIN (erp standard cost) c ON CAST(l.consumable_sku AS STRING)=c.ITEMID\n"
        "WHERE c.unit_cost IS NULL OR c.unit_cost = 0"
     ), "enabled": True},
    {"id": "XFER-01", "name": "Picked Transfer Order exists", "primitive": "REFERENTIAL", "error_type": "TRANSFER_ORDER_MISSING",
     "target_table": "consolidated_inventory_ledger ⋈ int_ledger_purchase_orders", "severity": "High", "fail_type": "Hard", "owner_group": "SC Product (IMS)",
     "params": {},
     "expression": (
        "-- Catalog XFER-01: a Transfer Out pick references a Transfer Order id not in the\n"
        "-- transfer-order population (orders table, order_type='Transfer').\n"
        "WITH picks AS (\n"
        "  SELECT DISTINCT ref_order_id AS to_id\n"
        "  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`\n"
        "  WHERE ref_order_type='Transfer Order' AND l2_action='Transfer Out' AND ref_order_id IS NOT NULL),\n"
        "to_pop AS (SELECT DISTINCT po AS to_id FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders` WHERE order_type='Transfer')\n"
        "SELECT p.to_id FROM picks p LEFT JOIN to_pop t USING (to_id) WHERE t.to_id IS NULL"
     ), "enabled": False},   # per Pavel: transfer orders are out of scope for now
    {"id": "PO-14", "name": "Received SKU listed on the PO", "primitive": "REFERENTIAL", "error_type": "PO_SKU_NOT_ON_PO",
     "target_table": "consolidated_inventory_ledger ⋈ int_ledger_purchase_orders", "severity": "High", "fail_type": "Hard", "owner_group": "SC Product (IMS)",
     "params": {},  # BigQuery 3-way-match join; runs via the SQL finder, skipped by the fixtures engine
     "expression": (
        "-- 3-way match (catalog PO-02): a consumable_sku received against an existing PO\n"
        "-- (ledger.ref_order_id = PO.po, order_type='Purchase') that is NOT on the PO's lines.\n"
        "WITH led AS (\n"
        "  SELECT DISTINCT ref_order_id AS po, consumable_sku\n"
        "  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`\n"
        "  WHERE ref_order_type='Purchase Order' AND consumable_sku IS NOT NULL),\n"
        "po_keys AS (SELECT DISTINCT po, consumable_sku FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders` WHERE order_type='Purchase'),\n"
        "po_exists AS (SELECT DISTINCT po FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders` WHERE order_type='Purchase')\n"
        "SELECT l.po, l.consumable_sku FROM led l JOIN po_exists pe USING (po)\n"
        "LEFT JOIN po_keys pk ON l.po=pk.po AND l.consumable_sku=pk.consumable_sku\n"
        "WHERE pk.po IS NULL  -- PO exists, but this received SKU isn't on it"
     ), "enabled": True},
    {"id": "PO-13", "name": "PO number present (master table)", "primitive": "NOT_NULL", "error_type": "PO_MISSING_NUMBER",
     "target_table": "int_ledger_purchase_orders", "severity": "Urgent", "fail_type": "Hard", "owner_group": "SC Product (IMS)",
     "params": {"column": "po", "where": {"order_type": ["Purchase"]}},
     "expression": (
        "-- Master PO table integrity: a Purchase row with no PO number (safety-net; 0 on current data).\n"
        "SELECT _id, supplier_name, supplier_sku, consumable_sku, po_date_utc\n"
        "FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`\n"
        "WHERE order_type = 'Purchase' AND (po IS NULL OR TRIM(po) = '')"
     ), "enabled": True},
    {"id": "PO-09", "name": "Vendor SKU price present", "primitive": "NOT_NULL", "error_type": "PO_MISSING_PRICE",
     "target_table": "int_ledger_purchase_orders", "severity": "Urgent", "fail_type": "Hard", "owner_group": "Procurement",
     "params": {"column": "supplier_price", "where": {"order_type": ["Purchase"]}},
     "expression": (
        "-- Purchase PO lines with no usable vendor (supplier) price — receipts can't be costed.\n"
        "SELECT po, supplier_sku, consumable_sku, supplier_name, status, supplier_price, po_date_utc\n"
        "FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`\n"
        "WHERE order_type = 'Purchase' AND (supplier_price IS NULL OR supplier_price = 0)"
     ), "enabled": True},
]

ROUTING = [
    {"error_type": "NULL_PO_NUMBER", "team": "SC Product (IMS)", "assignee": "Sarah Chen",
     "jira_project": "WIQ", "jira_component": "Ledger Ingest"},
    {"error_type": "PO_RECORD_MISSING", "team": "SC Product (IMS)", "assignee": "Marcus Webb",
     "jira_project": "WIQ", "jira_component": "PO Sync"},
    {"error_type": "PO_OVER_RECEIPT", "team": "Field Ops", "assignee": "Diego Alvarez",
     "jira_project": "WIQ", "jira_component": "Receiving"},
    {"error_type": "PO_IMPLAUSIBLE_QTY", "team": "SC Product (IMS)", "assignee": "Sarah Chen",
     "jira_project": "WIQ", "jira_component": "Data Integrity"},
    {"error_type": "PO_UOM_MISMATCH", "team": "Procurement", "assignee": "Lena Ortiz",
     "jira_project": "WIQ", "jira_component": "UoM / Conversions"},
    {"error_type": "TRANSFER_WAREHOUSE_IMBALANCE", "team": "Field Ops", "assignee": "Priya Nair",
     "jira_project": "WIQ", "jira_component": "Transfers"},
    {"error_type": "NEGATIVE_ON_HAND", "team": "SC Product (IMS)", "assignee": "Pavel Romanov",
     "jira_project": "WIQ", "jira_component": "On-Hand Recon"},
    {"error_type": "PO_MISSING_PRICE", "team": "Procurement", "assignee": "Tom Becker",
     "jira_project": "WIQ", "jira_component": "Vendor Pricing"},
    {"error_type": "PO_MISSING_NUMBER", "team": "SC Product (IMS)", "assignee": "Marcus Webb",
     "jira_project": "WIQ", "jira_component": "PO Master Integrity"},
    {"error_type": "PO_SKU_NOT_ON_PO", "team": "SC Product (IMS)", "assignee": "Marcus Webb",
     "jira_project": "WIQ", "jira_component": "3-Way Match"},
    {"error_type": "TRANSFER_ORDER_MISSING", "team": "SC Product (IMS)", "assignee": "Sarah Chen",
     "jira_project": "WIQ", "jira_component": "Transfer Orders"},
    # Fallback routing; overridden per-finding by facility_type in validate.py (Field Ops IKC/ProdCo).
    {"error_type": "WASTE_DAILY_FACILITY", "team": "Field Ops — ProdCo", "assignee": "Priya Nair",
     "jira_project": "WIQ", "jira_component": "Daily Waste"},
    {"error_type": "ADJ_DAILY_FACILITY", "team": "Field Ops — ProdCo", "assignee": "Priya Nair",
     "jira_project": "WIQ", "jira_component": "Daily Adjustments"},
    {"error_type": "WASTE_SKU_NO_COST", "team": "Accounting (Cost Accountant)", "assignee": "Mike Dietrich",
     "jira_project": "WIQ", "jira_component": "Standard Cost"},
    {"error_type": "CONSUMABLE_ZERO_COST", "team": "Accounting (Cost Accountant)", "assignee": "Mike Dietrich",
     "jira_project": "WIQ", "jira_component": "Standard Cost"},
]

# Owner group -> Jira routing: a group (for permissions / @mentions / filtering by the team
# label) + a default assignee email. assignee_email=None falls back to the JIRA_EMAIL account
# (handy in a single-user sandbox). The `group` value is also applied as a team label on each
# ticket so Jira can be filtered by team.
JIRA_TEAM_MAP = {
    "Field Ops": {"group": "dq-field-ops", "assignee_email": None},
    "Field Ops — IKC": {"group": "dq-field-ops-ikc", "assignee_email": None},
    "Field Ops — ProdCo": {"group": "dq-field-ops-prodco", "assignee_email": None},
    "SC Product (IMS)": {"group": "dq-sc-product-ims", "assignee_email": None},
    "Procurement": {"group": "dq-procurement", "assignee_email": None},
    "Accounting (Cost Accountant)": {"group": "dq-accounting", "assignee_email": None},
    "HDR Field Ops": {"group": "dq-hdr-field-ops", "assignee_email": None},
}
