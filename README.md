# Wonder Inventory Data-Quality & JIRA Automation Platform

An internal application for Wonder Group's accounting team that validates the company's inventory data daily, automatically files and tracks JIRA tickets for data errors, and reports on how quickly those errors get resolved.

## Why this exists

Wonder Group has **no centralized ERP**. A synthetic **unified inventory ledger** and a companion **purchase-order (PO) table** — assembled in BigQuery by a data engineer joining many upstream systems (Pantry, Ship Hero, Fishbowl) — serve as the **sub-ledger** the accounting team uses to book debits/credits in the general ledger at month-end. Because that assembly can introduce errors (bad joins, wrong unit conversions), data integrity is mission-critical: a bad row flows straight into inaccurate accounting.

## What it does

- **Daily batch validation** of the prior day's BigQuery data against a configurable set of rules (e.g. missing PO number, PO not found in the PO table, Transfer Warehouse imbalance, 3-way-match variance).
- **Auto-creates JIRA tickets** for each flagged error, routed to the right team and person (derived from the data where possible, otherwise from a configurable mapping).
- **Auto-closes** tickets when the next day's run shows data engineering has fixed the underlying issue — and never creates duplicates.
- **Tracks turnaround / SLA** so the company can see where time is lost, who is falling behind, and which errors recur.
- **Reporting dashboard + exception workbench** built for ease of use, since people across the company will use it.

## Tech stack (planned)

- **Backend:** Python (FastAPI), SQLAlchemy + Alembic
- **Frontend:** React + TypeScript
- **App database:** Cloud SQL for PostgreSQL (errors, tickets, SLA timers, history)
- **Data source:** BigQuery (read-only) — unified ledger + PO tables
- **Hosting:** GCP-native (Cloud Run + Cloud Run Jobs + Cloud Scheduler)
- **Auth:** Microsoft Entra ID (Azure AD) SSO via OIDC
- **Ticketing:** Jira Cloud (REST v3) with webhook + polling reconciliation

## Project status

**Phase 0 — UI mockups (current).** Per stakeholder process, visual mockups are built and socialized for approval **before** any production code. Three competing clickable prototypes live in [`prototypes/`](prototypes/README.md) — open any `index.html` to try them.

See [`PROCESS.md`](PROCESS.md) for the running log of what's done and what's next, and the full plan referenced there.

## Repository

`https://github.com/MDietrichWork/wonder_inventory.git`

## Layout

```
prototypes/            Clickable HTML mockups (Phase 0) — three UI directions to choose from
README.md              This file
PROCESS.md             Living project log: completed-to-date + what's next
```
