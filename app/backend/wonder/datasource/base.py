"""DataSource interface. Both fixtures and BigQuery return plain list[dict] rows
keyed by the column names in schema_map, so the rules engine is source-agnostic."""
from typing import List, Dict, Optional


class DataSource:
    def fetch_table(self, table: str, run_date: Optional[str] = None) -> List[Dict]:
        """Return rows for a logical table (schema_map.LEDGER_TABLE / PO_TABLE).

        For the ledger, run_date selects the prior-day partition being validated.
        The PO table is reference data and ignores run_date.
        """
        raise NotImplementedError
