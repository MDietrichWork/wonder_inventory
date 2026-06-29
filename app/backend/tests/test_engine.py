"""Engine + lifecycle tests. Uses a throwaway SQLite DB (set before importing wonder)."""
import os
os.environ.setdefault("APP_DB_URL", "sqlite:///./test_wonder.db")
os.environ.setdefault("DATA_SOURCE", "fixtures")
os.environ.setdefault("TICKET_SINK", "memory")

from types import SimpleNamespace  # noqa: E402

from wonder.rules import run_rules  # noqa: E402
from wonder.datasource.base import DataSource  # noqa: E402
from wonder.datasource.fixtures import FixtureDataSource  # noqa: E402
from wonder.schema_map import LEDGER_TABLE, PO_TABLE  # noqa: E402


class _Stub(DataSource):
    def __init__(self, ledger, po):
        self._l, self._p = ledger, po

    def fetch_table(self, table, run_date=None):
        return list(self._l if table == LEDGER_TABLE else self._p)


def _rule(rid, prim, etype, params, sev="High"):
    return SimpleNamespace(id=rid, primitive=prim, error_type=etype, target_table=LEDGER_TABLE,
                           params=params, severity=sev, enabled=True)


def test_not_null_flags_missing_po():
    ds = _Stub([
        {"txn_type": "PO_RECEIPT", "po_number": None, "sku": "S1", "facility": "F1"},
        {"txn_type": "PO_RECEIPT", "po_number": "PO-1", "sku": "S2", "facility": "F1"},
        {"txn_type": "SHIP", "po_number": None, "sku": "S3", "facility": "F1"},  # not a receipt -> ignored
    ], [])
    r = _rule("PO-01", "NOT_NULL", "NULL_PO_NUMBER",
              {"column": "po_number", "where": {"txn_type": ["PO_RECEIPT", "ADD"]}}, "Urgent")
    findings = run_rules([r], ds, "2026-06-09")
    assert len(findings) == 1
    assert findings[0].entity_key == "F1:S1"
    assert findings[0].severity == "Urgent"


def test_over_receipt_severity_bands():
    po = [{"po_number": "PO-1", "sku": "S1", "ordered_qty": 100},
          {"po_number": "PO-2", "sku": "S2", "ordered_qty": 100},
          {"po_number": "PO-3", "sku": "S3", "ordered_qty": 100},
          {"po_number": "PO-4", "sku": "S4", "ordered_qty": 100}]
    ledger = [
        {"txn_type": "PO_RECEIPT", "po_number": "PO-1", "sku": "S1", "qty": 260, "facility": "F1", "system_of_origin": "Sys"},  # 160% over -> Urgent (>=100%)
        {"txn_type": "PO_RECEIPT", "po_number": "PO-2", "sku": "S2", "qty": 160, "facility": "F1", "system_of_origin": "Sys"},  # 60%  over -> High (30-99%)
        {"txn_type": "PO_RECEIPT", "po_number": "PO-3", "sku": "S3", "qty": 200, "facility": "F1", "system_of_origin": "Sys"},  # 100% over exactly -> Urgent (boundary)
        {"txn_type": "PO_RECEIPT", "po_number": "PO-4", "sku": "S4", "qty": 120, "facility": "F1", "system_of_origin": "Sys"},  # 20%  over -> below 30% floor, not flagged
    ]
    r = _rule("PO-03", "OVER_RECEIPT", "PO_OVER_RECEIPT", {})
    sev = {f.entity_key: f.severity for f in run_rules([r], _Stub(ledger, po), "2026-06-09")}
    assert sev["PO-1:S1"] == "Urgent"      # >=100% over
    assert sev["PO-2:S2"] == "High"        # 30-99% over
    assert sev["PO-3:S3"] == "Urgent"      # exactly 100% over (boundary -> Urgent)
    assert "PO-4:S4" not in sev            # 20% over is below the 30% floor


def test_over_receipt_nets_corrections():
    """Received qty is a NET: a later negative correction on the SAME PO cancels an over-log.

    A receiver double-logs (or fat-fingers) a receipt, then a correction is booked back
    against the PO — auto as a negative receipt, or manually (e.g. 'Update Received Order').
    Both arrive as PO_RECEIPT rows, so summing them must net to the true quantity. Without
    netting, PO-5 below would falsely flag at 60% over; with netting it lands exactly on the
    ordered qty and must NOT flag. PO-6 stays Urgent because the correction only partly offsets.
    """
    po = [{"po_number": "PO-5", "sku": "S5", "ordered_qty": 100},
          {"po_number": "PO-6", "sku": "S6", "ordered_qty": 100}]
    ledger = [
        # PO-5: received 160, then a -60 correction tied to the PO -> net 100 (not over)
        {"txn_type": "PO_RECEIPT", "po_number": "PO-5", "sku": "S5", "qty": 160, "facility": "F1", "system_of_origin": "Sys"},
        {"txn_type": "PO_RECEIPT", "po_number": "PO-5", "sku": "S5", "qty": -60, "facility": "F1", "system_of_origin": "Sys"},
        # PO-6: received 260, then a -30 correction -> net 230 (still >=100% over -> Urgent)
        {"txn_type": "PO_RECEIPT", "po_number": "PO-6", "sku": "S6", "qty": 260, "facility": "F1", "system_of_origin": "Sys"},
        {"txn_type": "PO_RECEIPT", "po_number": "PO-6", "sku": "S6", "qty": -30, "facility": "F1", "system_of_origin": "Sys"},
    ]
    r = _rule("PO-03", "OVER_RECEIPT", "PO_OVER_RECEIPT", {})
    found = {f.entity_key: f for f in run_rules([r], _Stub(ledger, po), "2026-06-09")}
    assert "PO-5:S5" not in found            # 160 - 60 = 100 net -> not over, correction netted out
    assert found["PO-6:S6"].severity == "Urgent"   # 260 - 30 = 230 net -> still 130% over
    assert found["PO-6:S6"].snapshot["received_qty"] == 230


def test_over_receipt_facility_routing():
    from wonder import reference
    assert reference.over_receipt_route("HDR") == ("Field Ops — IKC", "Diego Alvarez")
    assert reference.over_receipt_route("CK")[0] == "Field Ops — ProdCo"
    assert reference.over_receipt_route("DISH")[0] == "Field Ops — ProdCo"
    assert reference.over_receipt_route("PRODUCTION")[0] == "Field Ops — ProdCo"
    assert reference.over_receipt_route(None)[0] == "Field Ops — ProdCo"   # unknown -> ProdCo
    assert reference.field_ops_facility_route is reference.over_receipt_route  # shared helper


def test_waste_daily_threshold_by_facility_type():
    from wonder import reference
    hdr = reference.waste_daily_threshold("HDR")           # selling units: small
    ck = reference.waste_daily_threshold("CK")             # central kitchen: large
    assert hdr["high"] < ck["high"] and hdr["urgent"] < ck["urgent"]
    assert reference.waste_daily_threshold("dish")["high"] == reference.waste_daily_threshold("DISH")["high"]  # case-insensitive
    assert reference.waste_daily_threshold("nope") == reference.waste_daily_threshold(None)   # unknown -> default


def test_lifecycle_autoclose_and_idempotent():
    from wonder.db import reset_db, SessionLocal
    from wonder.models import Rule, RoutingMap, Error
    from wonder import reference
    from wonder.jobs import run_validation
    from wonder.tickets import get_ticket_sink

    reset_db()
    db = SessionLocal()
    try:
        for rr in reference.RULES:
            db.add(Rule(id=rr["id"], name=rr["name"], primitive=rr["primitive"], error_type=rr["error_type"],
                        target_table=rr["target_table"], params=rr["params"], severity=rr["severity"],
                        fail_type=rr["fail_type"], owner_group=rr["owner_group"], expression=rr["expression"],
                        enabled=rr["enabled"]))
        for rr in reference.ROUTING:
            db.add(RoutingMap(error_type=rr["error_type"], team=rr["team"], assignee=rr["assignee"],
                              jira_project=rr["jira_project"], jira_component=rr["jira_component"]))
        db.commit()

        dates = ["2026-06-01", "2026-06-02", "2026-06-03"]
        ds = FixtureDataSource(dates)
        sink = get_ticket_sink()
        for d in dates:
            run_validation(db, d, ds, sink)

        errors = db.query(Error).all()
        assert errors, "should have detected errors"
        assert all(e.jira_issue_key for e in errors), "every error gets a ticket key"
        assert any(e.status == "Auto-Closed" for e in errors), "a fixed issue auto-closes"

        # idempotent: re-running the latest date creates no new errors
        before = db.query(Error).count()
        run_validation(db, dates[-1], ds, sink)
        assert db.query(Error).count() == before
    finally:
        db.close()
