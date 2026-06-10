"""Rule primitives, evaluated over rows from a DataSource.

Each enabled rule yields zero or more Findings (rule_id, error_type, severity,
entity_key, snapshot). The entity_key is stable across runs so the same logical issue
dedups and accrues recurrence; the job layer turns it into a fingerprint.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from ..schema_map import LEDGER as L, PO as P, LEDGER_TABLE, PO_TABLE
from ..config import settings


@dataclass
class Finding:
    rule_id: str
    error_type: str
    severity: str
    source_table: str
    entity_key: str
    snapshot: Dict[str, Any] = field(default_factory=dict)


def _matches_where(row: Dict, where: Dict) -> bool:
    for logical, allowed in (where or {}).items():
        col = L.get(logical, logical)
        if not isinstance(allowed, (list, tuple)):
            allowed = [allowed]
        if row.get(col) not in allowed:
            return False
    return True


def _ledger_snapshot(row: Dict) -> Dict[str, Any]:
    """Readable, logical-keyed snapshot of the offending ledger row (drop empty cols)."""
    out = {}
    for logical, col in L.items():
        v = row.get(col)
        if v is not None:
            out[logical] = v
    return out


def _ent(*parts) -> str:
    return ":".join("" if p is None else str(p) for p in parts)


# ---- primitive handlers: (rule, ds, run_date) -> List[Finding] ----

def _not_null(rule, ds, run_date) -> List[Finding]:
    col = L.get(rule.params["column"])
    if col is None:
        return []  # BigQuery-only rule (column not in the logical ledger map) — skip in fixtures
    where = rule.params.get("where", {})
    out = []
    for r in ds.fetch_table(rule.target_table, run_date):
        if not _matches_where(r, where):
            continue
        v = r.get(col)
        if v is None or v == "":
            snap = _ledger_snapshot(r)
            snap[rule.params["column"]] = None  # surface the offending NULL
            out.append(Finding(rule.id, rule.error_type, rule.severity, rule.target_table,
                               _ent(r.get(L["facility"]), r.get(L["sku"])), snap))
    return out


def _referential(rule, ds, run_date) -> List[Finding]:
    col = L[rule.params["column"]]
    ref_col = P.get(rule.params["ref_column"], rule.params["ref_column"])
    refset = {r.get(ref_col) for r in ds.fetch_table(rule.params["ref_table"])}
    where = rule.params.get("where", {})
    out = []
    for r in ds.fetch_table(rule.target_table, run_date):
        if not _matches_where(r, where):
            continue
        v = r.get(col)
        if v is None:
            continue  # NULL is a different rule's concern
        if v not in refset:
            snap = _ledger_snapshot(r)
            snap["po_lookup_result"] = "NOT_FOUND"
            out.append(Finding(rule.id, rule.error_type, rule.severity, rule.target_table,
                               _ent(v, r.get(L["sku"])), snap))
    return out


def _range(rule, ds, run_date) -> List[Finding]:
    col = L[rule.params["column"]]
    op, val = rule.params["op"], rule.params["value"]
    out = []
    for r in ds.fetch_table(rule.target_table, run_date):
        x = r.get(col)
        if x is None:
            continue
        bad = (op == "<" and x < val) or (op == ">" and x > val) or \
              (op == "<=" and x <= val) or (op == ">=" and x >= val)
        if bad:
            out.append(Finding(rule.id, rule.error_type, rule.severity, rule.target_table,
                               _ent(r.get(L["facility"]), r.get(L["sku"])), _ledger_snapshot(r)))
    return out


def _over_receipt(rule, ds, run_date) -> List[Finding]:
    """Sum received qty per (po, sku); compare to ordered qty. Severity by overage band."""
    ordered = {}
    for r in ds.fetch_table(PO_TABLE):
        ordered[(r.get(P["po_number"]), r.get(P["sku"]))] = r.get(P["ordered_qty"])
    received = {}
    where = {}  # representative facility/system per (po, sku) for display + charts
    for r in ds.fetch_table(rule.target_table, run_date):
        if r.get(L["txn_type"]) != "PO_RECEIPT":
            continue
        po, sku = r.get(L["po_number"]), r.get(L["sku"])
        if po is None:
            continue
        key = (po, sku)
        received[key] = received.get(key, 0) + (r.get(L["qty"]) or 0)
        where.setdefault(key, (r.get(L["facility"]), r.get(L["system"])))
    high, urgent = settings.over_receipt_high_pct, settings.over_receipt_urgent_pct
    out = []
    for (po, sku), recv in received.items():
        ord_qty = ordered.get((po, sku))
        if not ord_qty:
            continue  # missing PO is a referential concern
        over = (recv - ord_qty) / ord_qty
        if over > high:
            sev = "Urgent" if over > urgent else "High"
            fac, sysn = where.get((po, sku), (None, None))
            out.append(Finding(rule.id, rule.error_type, sev, rule.target_table, _ent(po, sku), {
                "po_number": po, "sku": sku, "facility": fac, "system": sysn,
                "ordered_qty": ord_qty, "received_qty": recv,
                "over_by_pct": round(over * 100, 1), "tolerance_pct": round(high * 100, 1),
            }))
    return out


def _recon_transfer(rule, ds, run_date) -> List[Finding]:
    fac = rule.params.get("facility", "TW-001")
    out = []
    for r in ds.fetch_table(rule.target_table, run_date):
        if r.get(L["txn_type"]) != "TRANSFER" or r.get(L["facility"]) != fac:
            continue
        shipped, recv = r.get(L["shipped_qty"]), r.get(L["received_qty"])
        if shipped is None or recv is None or shipped == recv:
            continue
        snap = _ledger_snapshot(r)
        snap["variance_qty"] = shipped - recv
        out.append(Finding(rule.id, rule.error_type, rule.severity, rule.target_table,
                           _ent(r.get(L["transfer_id"])), snap))
    return out


HANDLERS = {
    "NOT_NULL": _not_null,
    "REFERENTIAL": _referential,
    "RANGE": _range,
    "OVER_RECEIPT": _over_receipt,
    "RECON_TRANSFER": _recon_transfer,
}


def run_rules(rules, ds, run_date: str) -> List[Finding]:
    findings: List[Finding] = []
    for rule in rules:
        if not getattr(rule, "enabled", True):
            continue
        handler = HANDLERS.get(rule.primitive)
        if handler is None:
            continue
        findings.extend(handler(rule, ds, run_date))
    return findings
