# Wonder Inventory DQ — running application (prototype)

A working vertical slice of the platform: a **validation engine** runs the seeded rules
against inventory data, **fingerprints + dedups** each issue, **opens/auto-closes tickets**,
tracks **turnaround vs SLA**, and serves the **approved console** (Dashboard / Exception
Workbench / Turnaround-SLA / read-only Admin) from real data.

By default it runs **fully offline** on bundled fixtures + an in-memory ticket store, so it
demos with zero external setup. Point it at the real services by filling in `.env`.

## Run it

```bash
cd app
./run.sh            # creates venv, installs, seeds 21 daily runs, serves on :8000
```

Open **http://127.0.0.1:8000**. Use **↻ Run validation** (top bar) to re-run the latest
partition; click any KPI/chart to drill into the workbench; open a row for the snapshot,
ownership/sub-assignment, and JIRA timeline. `./run.sh --seed` forces a fresh re-seed.

Requirements: Python 3.9+. (No Node needed — the approved console is wired directly to the API.)

## How it's wired

```
DataSource (fixtures | BigQuery)  ──►  Rules engine (NOT_NULL, REFERENTIAL, RANGE,
                                        OVER_RECEIPT, RECON_TRANSFER)
        │                                        │ findings
        ▼                                        ▼
   Validation job  ──►  fingerprint → dedup → route → TicketSink (memory | Jira Cloud)
        │  detect / recurrence / auto-close-on-non-reproduction
        ▼
   SQLite (SQLAlchemy; swap APP_DB_URL for Cloud SQL Postgres)
        │
        ▼
   FastAPI  ──  /api/bootstrap (+ run / assign / subassign / resolve)  ──►  console (static)
```

Everything the engine reads goes through one **column map** (`wonder/schema_map.py`) and the
adapters are swappable — so going live is configuration, not a rewrite.

## Going live (what to provide)

Copy `.env.example` → `app/backend/.env` and fill in:

- **BigQuery** (read-only): `DATA_SOURCE=bigquery`, `GCP_PROJECT`, `BQ_DATASET`,
  `BQ_LEDGER_TABLE`, `BQ_PO_TABLE`, and either `GOOGLE_APPLICATION_CREDENTIALS` (SA key path)
  or `gcloud auth application-default login`. Then edit `wonder/schema_map.py` so the column
  names match the real ledger/PO schema, and `pip install "google-cloud-bigquery>=3.17"`.
- **Jira Cloud**: `TICKET_SINK=jira`, `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`,
  `JIRA_PROJECT_KEY`, `JIRA_ISSUE_TYPE`, optional `JIRA_FINGERPRINT_FIELD`, `JIRA_DONE_TRANSITION`.

## Tests

```bash
cd app/backend && ./.venv/bin/python -m pytest tests/ -q
```

## Known prototype simplifications (not yet production)

- Rules evaluate in Python over fetched rows; pushing SQL into BigQuery (PLAN Phase 6) is the
  performance step for large partitions.
- Auth (Entra SSO / role-based views), the Jira webhook + polling reconciliation, and a
  write-through Admin screen are not built yet.
- The **sub-assignment / ownership-transfer** model is implemented as designed (primary stays
  accountable, SLA does not reset, transitions audited) but the exact rules are still pending
  stakeholder confirmation.
