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
          {"po_number": "PO-2", "sku": "S2", "ordered_qty": 100}]
    ledger = [
        {"txn_type": "PO_RECEIPT", "po_number": "PO-1", "sku": "S1", "qty": 160, "facility": "F1", "system_of_origin": "Sys"},  # 60% over -> Urgent (>50%)
        {"txn_type": "PO_RECEIPT", "po_number": "PO-2", "sku": "S2", "qty": 106, "facility": "F1", "system_of_origin": "Sys"},  # 6%  over -> High (5-50%)
    ]
    r = _rule("PO-03", "OVER_RECEIPT", "PO_OVER_RECEIPT", {})
    sev = {f.entity_key: f.severity for f in run_rules([r], _Stub(ledger, po), "2026-06-09")}
    assert sev["PO-1:S1"] == "Urgent"   # >50% over
    assert sev["PO-2:S2"] == "High"     # 5-50% over


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
