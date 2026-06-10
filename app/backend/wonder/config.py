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
    over_receipt_high_pct: float = 0.05    # flag + High floor: received exceeds ordered by >5%
    over_receipt_urgent_pct: float = 0.50  # over-receipt severity split: 5-50% over -> High, >50% -> Urgent

    # --- BigQuery (only used when data_source=bigquery) ---
    gcp_project: Optional[str] = None
    bq_dataset: Optional[str] = None
    bq_ledger_table: Optional[str] = None   # e.g. "unified_inventory_ledger"
    bq_po_table: Optional[str] = None        # e.g. "purchase_order_table"
    google_application_credentials: Optional[str] = None  # path to read-only SA key

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


settings = Settings()
