"""Runtime configuration. Reads a local .env (never committed).

The whole point of the adapter design: flip DATA_SOURCE / TICKET_SINK and fill the
BigQuery / Jira slots, and the same validation loop runs against the real services.
With the defaults below it runs fully offline against bundled fixtures.
"""
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App datastore (SQLite locally; swap to Cloud SQL Postgres in prod) ---
    app_db_url: str = "sqlite:///./wonder.db"

    # --- Adapters ---
    data_source: str = "fixtures"   # "fixtures" | "bigquery"
    ticket_sink: str = "memory"     # "memory"   | "jira"

    # --- Validation run ---
    history_days: int = 21          # seed builds this many daily runs ending on run_date
    run_date: Optional[str] = None  # YYYY-MM-DD; default = latest fixture/today
    autoclose_consecutive_runs: int = 1  # close after issue absent for N runs

    # --- Over-receipt thresholds (catalog PO-03 / PO-04) ---
    # Per Pavel: 30-99% over is a supply-chain signal (High), >=100% over (received >=2x ordered)
    # is a likely receiving error (Urgent). The >2x "implausible" tier folds into the Urgent band.
    over_receipt_high_pct: float = 0.30    # flag + High floor: received exceeds ordered by >30%
    over_receipt_urgent_pct: float = 1.00  # over-receipt severity split: 30-99% over -> High, >=100% -> Urgent

    # PO-07: an open Purchase PO with nothing received is flagged once it's this many days past its
    # expected receipt date without being cancelled/closed by Supply Chain.
    po_no_receipt_overdue_days: int = 2
    # Only look back this many days from the expected receipt date, so the rule focuses on recently-
    # overdue POs instead of the full historical backlog (keeps the initial run small). 0 = no floor.
    po_no_receipt_overdue_lookback_days: int = 7

    # PO-08: a Purchase PO that received SOMETHING but less than ordered and hasn't been closed by
    # Supply Chain this many days past its expected receipt date. Same lookback semantics as PO-07.
    po_partial_not_closed_days: int = 3
    po_partial_not_closed_lookback_days: int = 7

    # PO-11: a ledger "Correction" transaction (l1_action LIKE '%correct%') with no correction_ref_id.
    # Only scan the last N days of ledger events (recency window; keeps the initial run small).
    po_correction_missing_ref_lookback_days: int = 7

    # PO-06: a purchased Wonder-family item whose Consumable SKU <> Vendor SKU can't be resolved to a
    # unit conversion in the supply-chain catalog (no catalog record, or the PO's vendor SKU isn't
    # linked). Daily flags items purchased on the run-date; only meaningful when units differ (a
    # conversion is genuinely needed). Backfill sweeps this many days of purchases; keeps the run small.
    po_missing_uom_conversion_lookback_days: int = 7

    # --- Waste thresholds ---
    # Daily facility waste $ thresholds are per-facility-type and live in
    # reference.WASTE_DAILY_THRESHOLDS (banded High/Urgent), not here.

    # --- BigQuery (only used when data_source=bigquery) ---
    gcp_project: Optional[str] = None
    bq_dataset: Optional[str] = None
    bq_ledger_table: Optional[str] = None   # e.g. "unified_inventory_ledger"
    bq_po_table: Optional[str] = None        # e.g. "purchase_order_table"
    # Supply-chain product/UoM catalog (same project, different dataset) — the master unit-conversion
    # source used by PO-06. hdr_product_sku = PO consumable_sku; vendor_product_skus = PO supplier_sku.
    bq_catalog_dataset: str = "supply_chain_catalog"
    bq_products_table: str = "wonder_products"
    google_application_credentials: Optional[str] = None  # path to read-only SA key
    # ERP standard-cost source (Dynamics), cross-project; ITEMID = consumable_sku. See SCHEMA_NOTES.md.
    erp_project: str = "wonder-raw-prod"
    erp_dataset: str = "erp_prod_batch"

    # --- Jira Cloud (only used when ticket_sink=jira) ---
    jira_base_url: Optional[str] = None      # https://your-org.atlassian.net
    jira_email: Optional[str] = None
    jira_api_token: Optional[str] = None
    jira_project_key: str = "WIQ"
    jira_issue_type: str = "Task"
    jira_fingerprint_field: Optional[str] = None  # customfield_xxxxx (else a label is used)
    jira_done_transition: str = "Done"       # transition name used for auto-close

    # --- Dev server ---
    cors_origins: str = "*"

    # --- Daily scheduler (localhost stand-in for Cloud Scheduler) ---
    # Off by default; at go-live leave this off and let Cloud Scheduler drive POST /api/run instead
    # (so the job isn't double-triggered). When on, the backend runs the prior-day validation nightly.
    scheduler_enabled: bool = False
    scheduler_hour: int = 0     # America/Los_Angeles — 00:15 PST = just after the data day closes
    scheduler_minute: int = 15
    scheduler_catchup_on_start: bool = True  # if the latest run is behind yesterday, run once at startup


settings = Settings()
