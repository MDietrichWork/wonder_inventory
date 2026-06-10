"""Deterministic fixture generator standing in for BigQuery.

Produces `history_days` daily ledger partitions + a static PO table, with seeded
defects that exercise every seeded rule and a realistic lifecycle: persistent issues
(rising recurrence), issues fixed mid-window (auto-close earlier), one fixed on the
latest run (auto-closed *today*), and brand-new issues that appear only today.
"""
from typing import List, Dict, Optional

from .base import DataSource
from ..schema_map import LEDGER_TABLE, PO_TABLE
from ..reference import FACILITIES

_FAC_TYPE = {f["id"]: f["type"] for f in FACILITIES}


def _row(date: str, idx: int, **ov) -> Dict:
    base = {
        "txn_id": "L-%s-%03d" % (date.replace("-", ""), idx),
        "txn_date": date,
        "txn_ts": date + "T06:%02d:00Z" % (idx % 60),
        "txn_type": "PO_RECEIPT",
        "sku": None, "facility": None, "facility_type": None, "system_of_origin": None,
        "po_number": "PO-559050", "order_type": "purchase order",
        "qty": 10, "running_on_hand": 100,
        "transfer_id": None, "from_facility": None, "to_facility": None,
        "shipped_qty": None, "received_qty": None, "lot_exp_id": None,
    }
    base.update(ov)
    if base["facility"] and base["facility_type"] is None:
        base["facility_type"] = _FAC_TYPE.get(base["facility"], "")
    return base


# Static PO table (reference data). po_number+sku → ordered_qty. The "PO-900xxx"
# numbers referenced by the ledger are deliberately absent (PO_RECORD_MISSING).
_PO_TABLE = [
    {"po_number": "PO-558120", "sku": "SKU-44821", "supplier": "Atlas Foods", "ordered_qty": 500,
     "unit_price": 2.10, "supplier_uom": "CASE", "wonder_sku": "SKU-44821", "conversion_factor": 1, "status": "Open"},
    {"po_number": "PO-558300", "sku": "SKU-22910", "supplier": "BlueWave Produce", "ordered_qty": 300,
     "unit_price": 0.95, "supplier_uom": "CASE", "wonder_sku": "SKU-22910", "conversion_factor": 1, "status": "Open"},
    {"po_number": "PO-559001", "sku": "SKU-50120", "supplier": "Northwind Dairy", "ordered_qty": 240,
     "unit_price": 1.80, "supplier_uom": "PALLET", "wonder_sku": "SKU-50120", "conversion_factor": 1, "status": "Open"},
    {"po_number": "PO-559050", "sku": "SKU-33820", "supplier": "BlueWave Produce", "ordered_qty": 400,
     "unit_price": 1.20, "supplier_uom": "CASE", "wonder_sku": "SKU-33820", "conversion_factor": 1, "status": "Open"},
    {"po_number": "PO-559075", "sku": "SKU-22999", "supplier": "Atlas Foods", "ordered_qty": 600,
     "unit_price": 2.40, "supplier_uom": "CASE", "wonder_sku": "SKU-22999", "conversion_factor": 1, "status": "Open"},
    {"po_number": "PO-559125", "sku": "SKU-77310", "supplier": "Atlas Foods", "ordered_qty": 1000,
     "unit_price": 1.50, "supplier_uom": "CASE", "wonder_sku": "SKU-77310", "conversion_factor": 1, "status": "Open"},
]

# Each spec: (start_offset, end_offset) measured in days before the LAST run date.
# end_offset 0 => still active today; >0 => fixed that many days ago (auto-closes).
# `row` holds the defective-ledger overrides emitted on every active day.
_SPECS = [
    # NULL_PO_NUMBER (PO-01)
    {"start": 7, "end": 0, "row": {"txn_type": "PO_RECEIPT", "po_number": None, "sku": "SKU-10233",
        "facility": "DIS-ATL-01", "system_of_origin": "Ship Hero", "qty": 240}},
    {"start": 4, "end": 0, "row": {"txn_type": "PO_RECEIPT", "po_number": None, "sku": "SKU-10888",
        "facility": "DIS-DAL-02", "system_of_origin": "Ship Hero", "qty": 72}},
    {"start": 8, "end": 0, "row": {"txn_type": "ADD", "po_number": None, "sku": "SKU-50120",
        "facility": "CK-CHI-01", "system_of_origin": "Fishbowl", "qty": 80}},
    {"start": 9, "end": 4, "row": {"txn_type": "PO_RECEIPT", "po_number": None, "sku": "SKU-10501",
        "facility": "IK-NYC-01", "system_of_origin": "Pantry", "qty": 96}},          # auto-closed earlier
    {"start": 6, "end": 1, "row": {"txn_type": "PO_RECEIPT", "po_number": None, "sku": "SKU-13990",
        "facility": "IK-LA-02", "system_of_origin": "Pantry", "qty": 60}},           # auto-closed TODAY
    {"start": 0, "end": 0, "row": {"txn_type": "PO_RECEIPT", "po_number": None, "sku": "SKU-10999",
        "facility": "DIS-ATL-01", "system_of_origin": "Ship Hero", "qty": 120}},     # new today

    # PO_RECORD_MISSING (PO-02) — po_number absent from the PO table
    {"start": 5, "end": 0, "row": {"txn_type": "PO_RECEIPT", "po_number": "PO-900001", "sku": "SKU-77410",
        "facility": "DIS-ATL-01", "system_of_origin": "Ship Hero", "qty": 144}},
    {"start": 0, "end": 0, "row": {"txn_type": "PO_RECEIPT", "po_number": "PO-900050", "sku": "SKU-77777",
        "facility": "DIS-DAL-02", "system_of_origin": "Ship Hero", "qty": 60}},       # new today

    # PO_OVER_RECEIPT (PO-03) — received qty exceeds ordered
    {"start": 6, "end": 0, "row": {"txn_type": "PO_RECEIPT", "po_number": "PO-558120", "sku": "SKU-44821",
        "facility": "DIS-ATL-01", "system_of_origin": "Ship Hero", "qty": 560}},      # 12% over -> Urgent
    {"start": 3, "end": 0, "row": {"txn_type": "PO_RECEIPT", "po_number": "PO-558300", "sku": "SKU-22910",
        "facility": "CK-CHI-01", "system_of_origin": "Fishbowl", "qty": 318}},        # 6% over -> High

    # TRANSFER_WAREHOUSE_IMBALANCE (TWH-01)
    {"start": 6, "end": 0, "row": {"txn_type": "TRANSFER", "facility": "TW-001", "system_of_origin": "Ship Hero",
        "transfer_id": "TRF-30150", "from_facility": "DIS-DAL-02", "to_facility": "IK-NYC-01",
        "sku": "SKU-22999", "shipped_qty": 420, "received_qty": 360, "po_number": None, "order_type": "transfer order"}},
    {"start": 3, "end": 0, "row": {"txn_type": "TRANSFER", "facility": "TW-001", "system_of_origin": "Ship Hero",
        "transfer_id": "TRF-30188", "from_facility": "DIS-DAL-02", "to_facility": "IK-LA-02",
        "sku": "SKU-22910", "shipped_qty": 108, "received_qty": 100, "po_number": None, "order_type": "transfer order"}},

    # NEGATIVE_ON_HAND (COMPLETE-02)
    {"start": 5, "end": 0, "row": {"txn_type": "SHIP", "po_number": None, "sku": "SKU-44821",
        "facility": "DIS-ATL-01", "system_of_origin": "Ship Hero", "qty": -42, "running_on_hand": -18,
        "order_type": "customer order"}},
    {"start": 0, "end": 0, "row": {"txn_type": "CONSUME", "po_number": None, "sku": "SKU-44102",
        "facility": "IK-LA-02", "system_of_origin": "Pantry", "qty": -30, "running_on_hand": -5,
        "order_type": "production order"}},                                           # new today
]

# Clean PO receipts emitted every day (valid PO, received <= ordered) for realistic scan volume.
_CLEAN = [
    {"po_number": "PO-559050", "sku": "SKU-33820", "facility": "IK-NYC-01", "system_of_origin": "Pantry", "qty": 120},
    {"po_number": "PO-559075", "sku": "SKU-22999", "facility": "DIS-ATL-01", "system_of_origin": "Ship Hero", "qty": 300},
    {"po_number": "PO-559125", "sku": "SKU-77310", "facility": "DIS-DAL-02", "system_of_origin": "Ship Hero", "qty": 500},
    {"po_number": "PO-559050", "sku": "SKU-33820", "facility": "CK-CHI-01", "system_of_origin": "Fishbowl", "qty": 90},
    {"po_number": "PO-559075", "sku": "SKU-22999", "facility": "IK-LA-02", "system_of_origin": "Pantry", "qty": 150},
]


class FixtureDataSource(DataSource):
    def __init__(self, run_dates: List[str]):
        self.run_dates = list(run_dates)
        n = len(self.run_dates)
        self._ledger: Dict[str, List[Dict]] = {d: [] for d in self.run_dates}
        for i, date in enumerate(self.run_dates):
            rows: List[Dict] = []
            idx = 1
            for c in _CLEAN:
                rows.append(_row(date, idx, running_on_hand=200, **c)); idx += 1
            for spec in _SPECS:
                start_idx = n - 1 - spec["start"]
                end_idx = n - 1 - spec["end"]
                if start_idx <= i <= end_idx:
                    rows.append(_row(date, idx, **spec["row"])); idx += 1
            self._ledger[date] = rows

    def fetch_table(self, table: str, run_date: Optional[str] = None) -> List[Dict]:
        if table == PO_TABLE:
            return [dict(r) for r in _PO_TABLE]
        if table == LEDGER_TABLE:
            return [dict(r) for r in self._ledger.get(run_date, [])]
        return []
