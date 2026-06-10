# Wonder Group — Inventory Data-Quality & JIRA Automation Platform

## Context

Wonder Group has **no centralized ERP**. The accounting team relies on a **synthetic unified inventory ledger** (and a companion **PO table**), both built by a data engineer who joins/maps upstream systems — a process that can introduce **erroneous data** (bad joins, wrong conversion math). Because this ledger is the **sub-ledger** used to book debits/credits in the general ledger at month-end, data integrity is mission-critical: errors flow straight into inaccurate accounting.

This application will run a **daily batch** validation of the **prior day's** data, flag inconsistencies, **auto-create JIRA tickets** routed to the right team and person, and **track turnaround** so the company can see where time is lost, who is behind, and which errors recur. When data engineering later fixes the underlying table, the next daily run must **automatically close** the resolved ticket — and never create duplicates.

A very large number of people across the company will use this in some capacity, so **ease of use is a first-class requirement**: the exception-handling experience must be intuitive and must not overwhelm staff.

### Hard process decision (from stakeholder walkthrough)
**Visual mockups must be built and socialized for stakeholder approval BEFORE any production code is written.** The first deliverable is a **clickable HTML prototype**, not an application. Touchpoint meetings every other day.

### Decisions locked in
| Area | Decision |
|---|---|
| First deliverable | **2–3 clickable HTML prototypes** (distinct UI directions, all 4 core screens) for stakeholders to compare and choose, approved before code. **✅ Approved 2026-06-09: Variant A (dense workbench) base + Variant C dashboard-as-home, condensed, darker-blue — consolidated in `prototypes/approved-console/`** (this is the React styling/UX reference). |
| Data source | **BigQuery** — synthetic unified ledger + PO tables (read-only), high volume |
| Cadence | **Daily batch** validating the previous day's complete data |
| Re-validation | Re-check open issues each run; **auto-close** JIRA ticket if the issue is gone; update (not duplicate) if still present |
| Hosting | **GCP-native** (co-located with the data) |
| App database | **Cloud SQL for PostgreSQL** (errors, tickets, SLA timers, history) |
| Validation rules | **Configurable rules engine** (start simple: null PO #, record-exists-in-PO-table) |
| Routing | **Hybrid**: derived from ledger fields + configurable mapping table |
| Dashboard | **Custom web app UI**, ease-of-use paramount |
| JIRA | **Jira Cloud** (REST v3); webhook + polling reconciliation |
| Backend / Frontend | **Python (FastAPI)** + **React + TypeScript** |
| Auth | **Microsoft Entra ID (Azure AD) SSO** via OIDC |
| Git repository | **https://github.com/MDietrichWork/wonder_inventory.git** |

---

## Domain model (from the stakeholder walkthrough)

### Unified Inventory Ledger
A date/timestamped record of systemically generated inventory movements. Key attributes:
- **Timestamps** in both Eastern and UTC; **Grid ID** for internal tracking.
- **System of origin:** Pantry (selling locations), Ship Hero (distribution facilities), Fishbowl (production facilities).
- **Movement categories:** PO receipts, transfers, production consumption, expiration activity, cycle-count discrepancies, sales.
- **Facility:** Facility ID + type — High Density Restaurants (aka **Infinite Kitchens**), Central Kitchens (**CK**), Distribution (**DIS**), and a synthetic **Transfer Warehouse**.
- **Location hierarchy:** zone → aisle → rack → shelf → bin.
- **Location quality:** first-quality, damaged, quarantine. Damaged/quarantine are assigned **zero cost** (conservative costing).
- **Action classifications:** Add (PO receipt, production), Move, Remove (sales, consumption), Adjust (cycle counts, loss/damage), **Correction** (fixes an erroneous entry by *referencing* the original record without altering the original factual log).
- **Reference order types:** purchase order, move order (intra-facility), transfer order (inter-facility), production order, customer order. Some transactions (e.g. manual damage adjustments) have **null** order type/ID.
- **Lot Expiration ID** (not a hard-coded date) — points to a subsidiary table so expiration can be adjusted without touching the primary transaction.
- **Inventory on hand** = cumulative sum of change quantities through a given date.

### Synthetic Transfer Warehouse logic
For cross-state moves taking >1 day, the system writes **two balancing record pairs**: reduce source / increase Transfer Warehouse, then increase destination / reduce Transfer Warehouse — so month-end inventory stays balanced. Discrepancies (e.g. 108 shipped, 100 received) leave **aged inventory** stranded in the Transfer Warehouse → a validation target.

### PO table & 3-way matching
- Drives **3-way matching**: invoice ↔ purchase order ↔ inventory log.
- Holds supplier SKU, price, quantity in the **supplier's unit of measure**, plus a **conversion factor** to the internal **Wonder SKU** nomenclature (so received qty can be matched to invoices).
- **Purchased items:** weighted-average cost over the trailing **180 days** of processed invoices.
- **Manufactured items:** standard cost from **BOM** in **Cookbook**, which syncs with **Microsoft Dynamics**.

---

## Validation rules engine

The rules engine is **configurable and extensible**; it is seeded from the stakeholder **validation framework** (`docs/framework.xlsx`, kept internal/git-ignored) and grown via the every-other-day touchpoints.

- Rules stored in Postgres (`rule` table): `rule_key`, name/test text, primitive type, target table/columns, params (JSONB for the X/Y/Z thresholds), `fail_type` (Hard/Soft), severity, `owner_group` (routing hint), enabled flag.
- **Rule primitives** (extensible), compiled to BigQuery SQL: `NOT_NULL`, `REFERENTIAL` (value must exist in / be listed on another table), `RANGE` (threshold / variance %, $ limits), `RECONCILIATION` (balance / matched-pair / on-hand sum checks), `FRESHNESS` (aging / no-activity-after-N-days), and a `CUSTOM_SQL` escape hatch (mappings, BOM 1:1).
- Each test is a **Hard fail** (deterministic error) or **Soft fail** (diagnostic exception requiring review before it's classified as an error vs. a valid business exception). *Hard/Soft below is inferred and pending stakeholder confirmation.*
- Push rule logic into **BigQuery SQL** (scan the prior-day partition, return only offending rows) — the warehouse does the heavy lifting; only failures come back.

### Operating model

Detect → Classify → Assign → Ticket → Remediate → Measure → Prevent Recurrence.

### Severity & SLA (business days)

| Severity | Meaning | SLA |
|---|---|---|
| **Urgent** | Likely financial-statement / margin impact; urgent correction | 0 — same day |
| **High** | Operationally material issue or recurring data defect | 1 day |
| **Medium** | Needs review but limited immediate impact | 2 days |
| **Low** | Informational / trend-monitoring / cleanup (no current seed test; kept available) | 3–5 days |

### Root-cause classification (ticket taxonomy)

Each ticket is classified into one of: Source system · Integration/pipeline · Data transformation · Master data · Unit-of-measure · Costing · User process · Timing/cutoff · Valid business exception · Unknown/under review.

### Owner groups (routing targets)

**SC Product (IMS)** (11) · **Field Ops** (21) · **Procurement** (5) · **Accounting (Cost Accountant)** (6) · **HDR Field Ops** (4)

### Seed validation tests — full catalog

**47 tests across 11 transaction classes.** `X/Y/Z`, `$X`, `A%–B%` are thresholds still to be set with stakeholders. `rule_key` is the stable identifier used in tickets, the `rule` table, and at touchpoints.

**1. PO Receiving, 3P**

| Key | Test | Primitive | Type | Severity | Owner group |
|---|---|---|---|---|---|
| `PO-01` | PO receipt log has a NULL PO number, or the PO number does not exist in the Unified PO Table | `NOT_NULL` | Hard | Urgent | SC Product (IMS) |
| `PO-02` | PO receipt log includes a SKU that is not listed on the corresponding PO in the Unified PO Table | `REFERENTIAL` | Hard | High | SC Product (IMS) |
| `PO-03` | PO receipt quantity exceeds the ordered quantity by more than X% | `RANGE` | Soft | Urgent | Field Ops |
| `PO-04` | PO receipt quantity exceeds the ordered quantity by more than Y% | `RANGE` | Soft | High | Field Ops |
| `PO-05` | Missing or incorrect mapping between Consumable SKU <> Wonder SKU <> Vendor SKU | `RECONCILIATION` | Hard | Urgent | Procurement |
| `PO-06` | Missing or incorrect unit conversions between Consumable SKU <> Wonder SKU <> Vendor SKU | `RECONCILIATION` | Hard | Urgent | Procurement |
| `PO-07` | PO has no receipt and has not been marked as Cancelled by Supply Chain after X days | `FRESHNESS` | Soft | Medium | Procurement |
| `PO-08` | PO has been partially received but has not been closed by Supply Chain after Y days | `FRESHNESS` | Soft | Medium | Procurement |
| `PO-09` | PO has a $0.00 or NULL Vendor SKU price | `NOT_NULL` | Hard | Urgent | Procurement |
| `PO-10` | Consumable SKU has a $0.00 or NULL standard cost | `NOT_NULL` | Hard | Urgent | Accounting (Cost Accountant) |
| `PO-11` | “Correct receiving” transaction is missing a correction_ref_id | `CUSTOM_SQL` | Hard | High | SC Product (IMS) |
| `PO-12` | “Correct receiving” transaction is processed more than Z days after the receipt (i.e. too late) | `FRESHNESS` | Soft | High | Field Ops |

**2. Production & Consumption for Production**

| Key | Test | Primitive | Type | Severity | Owner group |
|---|---|---|---|---|---|
| `PROD-01` | Quantity of items produced, per production logs, differs from the quantity requested on the production order by more than X% | `RECONCILIATION` | Soft | High | Field Ops |
| `PROD-02` | Production log is missing a reference to a production order | `CUSTOM_SQL` | Hard | High | SC Product (IMS) |
| `PROD-03` | Production log references a production order that does not exist in the production order population | `REFERENTIAL` | Hard | High | SC Product (IMS) |
| `PROD-04` | Production log includes items that are not listed on the referenced production order | `REFERENTIAL` | Hard | Medium | Field Ops |
| `PROD-05` | Production order has no production activity after Y days | `FRESHNESS` | Soft | Medium | Field Ops |
| `PROD-06` | Dollar value of items produced differs from the dollar value of components used in production by more than Y% | `RECONCILIATION` | Soft | High | Field Ops |

**3. Expiration, Damages & Other Waste**

| Key | Test | Primitive | Type | Severity | Owner group |
|---|---|---|---|---|---|
| `WASTE-01` | Daily Waste at a facility value exceeds $X | `RANGE` | Soft | High | Field Ops |

**4. Adjustments**

| Key | Test | Primitive | Type | Severity | Owner group |
|---|---|---|---|---|---|
| `ADJ-01` | Daily Adjustment at a facility value exceeds $Y (absolute value) | `RANGE` | Soft | High | Field Ops |

**5. Inter-network Transfers In & Out**

| Key | Test | Primitive | Type | Severity | Owner group |
|---|---|---|---|---|---|
| `XFER-01` | Items picked against a transfer order reference a Transfer Order that does not exist | `REFERENTIAL` | Hard | High | SC Product (IMS) |
| `XFER-02` | Items picked against a transfer order are not listed on the corresponding Transfer Order | `REFERENTIAL` | Hard | High | Field Ops |
| `XFER-03` | Quantity of items picked against a transfer order differs from the quantity requested on the Transfer Order by more than X% | `RECONCILIATION` | Soft | High | Field Ops |
| `XFER-04` | Transfer order has no pick activity after Y days | `FRESHNESS` | Soft | Medium | Field Ops |
| `XFER-05` | Items received against a transfer order are not listed on the corresponding Transfer Order | `REFERENTIAL` | Hard | High | SC Product (IMS) |
| `XFER-06` | Quantity of items received against a transfer order differs from the quantity picked on the Transfer Order by more than X% | `RECONCILIATION` | Soft | High | Field Ops |
| `XFER-07` | Transfer order has been picked but not received after Z days | `FRESHNESS` | Soft | Medium | Field Ops |

**6. Sales, B2B**

| Key | Test | Primitive | Type | Severity | Owner group |
|---|---|---|---|---|---|
| `SALEB2B-01` | Items picked against a sales order reference a Sales Order that does not exist | `REFERENTIAL` | Hard | High | SC Product (IMS) |
| `SALEB2B-02` | Items picked against a sales order are not listed on the corresponding Sales Order | `REFERENTIAL` | Hard | High | Field Ops |
| `SALEB2B-03` | Quantity of items picked against a Sales Order differs from the quantity requested on the Sales Order by more than X% | `RECONCILIATION` | Soft | High | Field Ops |
| `SALEB2B-04` | Sales Order has no pick activity after Y days | `FRESHNESS` | Soft | Medium | Field Ops |

**7. Sales, HDR**

| Key | Test | Primitive | Type | Severity | Owner group |
|---|---|---|---|---|---|
| `SALEHDR-01` | Menu Items cooked reference a Customer Order that does not exist | `REFERENTIAL` | Hard | High | SC Product (IMS) |
| `SALEHDR-02` | Menu Items cooked reference a Customer Order that has been cancelled BEFORE cooking has started | `REFERENTIAL` | Soft | High | HDR Field Ops |
| `SALEHDR-03` | Menu Items cooked against a Customer Order are not listed on the corresponding Customer Order | `REFERENTIAL` | Hard | High | HDR Field Ops |
| `SALEHDR-04` | Quantity of Menu Items cooked against a Customer Order differs from the quantity requested on the Customer Order by more than X% | `RECONCILIATION` | Soft | High | HDR Field Ops |
| `SALEHDR-05` | A non-cancelled Customer Order has no cook activity after Y days | `FRESHNESS` | Soft | Medium | HDR Field Ops |

**8. Intra-warehouse movement**

| Key | Test | Primitive | Type | Severity | Owner group |
|---|---|---|---|---|---|
| `MOVE-01` | A "move from" transaction does not have a matching "move to" transaction & vice-versa | `RECONCILIATION` | Soft | High | Field Ops |
| `MOVE-02` | An item on the "move from" transaction is not on the "move to" transaction & vice-versa | `REFERENTIAL` | Hard | High | Field Ops |
| `MOVE-03` | Quantity of an item on the "move from" transaction <> quantity of that item on the "move to" transaction | `RECONCILIATION` | Soft | High | Field Ops |

**9. Standard Costing & BOM Structure**

| Key | Test | Primitive | Type | Severity | Owner group |
|---|---|---|---|---|---|
| `COST-01` | A Menu Item's margin exceeds Y% | `RANGE` | Soft | High | Accounting (Cost Accountant) |
| `COST-02` | A Menu Item's margin is outside (A%...B%) margin range for the category | `RANGE` | Soft | Medium | Accounting (Cost Accountant) |
| `COST-03` | A Menu Item's margin is negative | `RANGE` | Soft | High | Accounting (Cost Accountant) |
| `COST-04` | Raw material items (lowest level of the BOM) have a $0.00 or NULL standard cost | `NOT_NULL` | Hard | High | Accounting (Cost Accountant) |
| `COST-05` | Latest BOM in Cookbook does not match 1:1 (components and QTY) to the latest Costed BOM in D365 | `RECONCILIATION` | Hard | High | Accounting (Cost Accountant) |

**10. Completeness of Inventory Logs**

| Key | Test | Primitive | Type | Severity | Owner group |
|---|---|---|---|---|---|
| `COMPLETE-01` | Calculated On-Hand (using logs) by Item, by Facility does not match the On-hand Snapshot | `RECONCILIATION` | Soft | High | SC Product (IMS) |
| `COMPLETE-02` | Calculated On-Hand (using logs) by Item, by Facility has negative balances | `RECONCILIATION` | Soft | High | SC Product (IMS) |

**11. Accuracy of On-hand balances (see more on cycle-counting below)**

| Key | Test | Primitive | Type | Severity | Owner group |
|---|---|---|---|---|---|
| `ONHAND-01` | A combination of {Item, Facility, Location ID} hasn't been cycle-counted over X days | `FRESHNESS` | Soft | Medium | Field Ops |

### Leadership metrics (Aging & SLA)

Open by owner group · Open by age · New created daily/weekly · Closed · Average days to close · Repeat exceptions by validation test · Estimated financial impact.

---

## Error → ticket → turnaround lifecycle

1. **Detect:** daily job runs rules against the prior-day partition; each failure → an `error` row with a stable **fingerprint** (hash of rule + entity key) for dedup and recurrence counting.
2. **Route (hybrid):** owner derived from ledger fields where available (system of origin, facility, order type), else from the configurable `routing_map` (error type → team → assignee), else a default team.
3. **Create JIRA:** if no open ticket with that fingerprint exists, create a Jira Cloud issue (summary, error detail + offending data + run date, assignee, team/component, fingerprint custom field/label); store `jira_issue_key`. If one already exists, **comment/update instead of duplicating**.
4. **Re-validate & auto-close:** each subsequent daily run re-checks open fingerprints; if the issue **no longer reproduces** (data engineering fixed the table), **automatically transition the ticket to closed/resolved** with an audit note. This prevents staff from investigating stale issues.
5. **Turnaround:** a secured **Jira webhook** receiver timestamps status transitions, with a **polling job** reconciling missed events. Compute time-to-first-response and time-to-resolution per ticket/team/assignee/error-type, plus aging vs SLA targets and recurrence counts.

---

## Architecture overview

```
   BigQuery (read-only: unified ledger + PO tables)
        │  BQ Storage Read API / pushed-down SQL
        ▼  (daily, Cloud Scheduler)
   VALIDATION BATCH JOB (Python, Cloud Run Job)
   • prior-day partition → rules engine → offending rows
   • detect/route errors, create/update/auto-close JIRA, write history
        │ writes                         │ create/close/comment
        ▼                                ▼
   Cloud SQL (Postgres) ◄────────────►  Jira Cloud (REST v3)
   runs, rules, mappings, errors,        │ webhook (status change)
   tickets, ticket_events, SLA, audit    ▼
        │                          webhook receiver + poller
        ▼
   FastAPI backend (Cloud Run) ◄────► React dashboard (Cloud Run)
        ▲
   Microsoft Entra ID (OIDC SSO)
```

---

## Core screens (mockup round 1 — all four prioritized)

1. **Exception / error workbench** — the daily flagged-error list with strong filtering (facility, system of origin, error type, severity, status), a clear detail view showing the offending ledger/PO data, linked live JIRA status, and flag/override actions. Designed to **not overwhelm** — sane defaults, grouping, bulk actions.
2. **Reporting dashboard** — inventory-movement views, error trends, recurring-error leaderboard, team/person scorecards.
3. **Ticket turnaround / SLA view** — per-team and per-person turnaround, aging/overdue tickets, where time is lost.
4. **Rule & routing admin** — manage validation rules, error→team→person mappings, and SLA targets (the configurable layer).

---

## Proposed Postgres schema (initial)

- `validation_run` — id, run_date, table, started/finished, status, rows_scanned, error_count
- `rule` — id, name, type, target_table, params (JSONB), severity, routing_hint (JSONB), enabled
- `routing_map` — id, error_type/team, assignee, jira_project, jira_component, active
- `error` — id, run_id, rule_id, error_type, source_table, entity_key, data_snapshot (JSONB), severity, fingerprint, routed_team, routed_assignee, status, detected_at, resolved_at, jira_issue_key
- `ticket_event` — id, error_id, jira_issue_key, from_status, to_status, occurred_at
- `sla_target` — id, error_type/severity, response_target, resolution_target
- `audit_log` — id, actor, action, entity, before/after (JSONB), at

(Fingerprint = stable hash over rule_id + entity key, so the same logical issue dedups, recurs countably, and can be auto-closed when it stops reproducing.)

---

## Tech stack & infrastructure

- **Backend:** Python 3.12, FastAPI, SQLAlchemy + Alembic, `google-cloud-bigquery` + `-bigquery-storage`, `httpx`/`jira` for Jira REST.
- **Frontend:** React + TypeScript + Vite, charting lib (Recharts/ECharts), MSAL for Entra SSO. (The approved HTML prototype becomes the styling/UX reference.)
- **Data store:** Cloud SQL for PostgreSQL.
- **Compute:** Cloud Run (API + frontend), Cloud Run Jobs (validation + poller), Cloud Scheduler (daily + reconciliation).
- **Secrets/identity:** Secret Manager (Jira token, DB creds); least-privilege service account with **read-only** access to the specific BQ datasets.
- **IaC:** Terraform. **Observability:** Cloud Logging/Monitoring; alert on failed runs or anomalous error counts.

### Performance
Workload is a once-daily scan of large tables, so "performance" = efficient large-batch processing, not low latency: push rule logic into BigQuery SQL (return only failures), read via the Storage Read API, process partitions in parallel, and keep the dashboard fast with **pre-aggregated summary tables** in Postgres rather than recomputing from raw data.

---

## Documentation deliverables

Two docs live in the repo root and are maintained throughout:

- **`README.md`** — project overview, architecture summary, how to run the prototypes / app, tech stack, setup/onboarding instructions. Kept current as the project evolves.
- **`PROCESS.md`** — a **living process-documentation log**. It is **updated at every step** of the project with each new thing implemented. It always reflects:
  - **Completed to date** — a running, dated log of what has been built/decided (newest at top or clearly sectioned).
  - **What's next** — the immediate next step(s), if any.
  This doc is a standing obligation: **every phase below ends by updating `PROCESS.md`** (and the README where relevant) before moving on, so the project history and current state are always self-documented.

---

## Roadmap (mockup-first)

**Phase 0 — Mockups (✅ direction approved 2026-06-09; consolidated prototype = `prototypes/approved-console/`. NO production code):**
1. Build **2–3 distinct clickable HTML prototypes** with realistic fake data, each covering all four core screens. Each represents a different UI direction so the stakeholder can review options with others in the organization and pick a winner (or a blend). Likely directions to contrast:
   - **A — Dense workbench / data-grid first:** information-dense tables and filters for power users who triage many exceptions quickly.
   - **B — Guided / card-based triage:** a cleaner, more guided exception-by-exception flow optimized for occasional/non-expert users (minimizes overwhelm).
   - **C — Dashboard-led / summary-first:** metrics and charts up front, drilling down into exceptions — good for managers/accounting leadership.

   **Each variant lives in its own self-contained folder** (no shared files between variants) so picking one is trivial — keep its folder and delete the others. Proposed layout:
   ```
   prototypes/
     variant-a-dense-workbench/    (its own index.html + assets, fully standalone)
     variant-b-guided-triage/      (its own index.html + assets, fully standalone)
     variant-c-dashboard-led/      (its own index.html + assets, fully standalone)
     README.md                     (how to open each + a one-line summary of each direction)
   ```
2. Bake the ease-of-use principles into all variants (clear exception triage, no overwhelm).
3. Socialize the variants with stakeholders (Pavel + group) at the every-other-day touchpoints; iterate until one direction is approved. **✅ Done — approved direction is Variant A + Variant C dashboard-as-home, consolidated into `prototypes/approved-console/` (the three original variants are retained as reference). Next touchpoint: walk Pavel through the approved console for polish notes.**
4. Create the initial **`README.md`** and **`PROCESS.md`**; record the prototype work and the "what's next" (stakeholder selection).

> **Standing rule for every phase:** end the phase by updating **`PROCESS.md`** (completed-to-date + what's next) and the **`README.md`** where relevant.

**Phase 1 — Foundation (after mockup approval):** initialize and push to the **`wonder_inventory`** GitHub repo (https://github.com/MDietrichWork/wonder_inventory.git), repo scaffold, Terraform, Cloud SQL, read-only BQ access to the **specific ledger + PO tables**, CI (GitHub Actions). Obtain table names/partitioning + sample data.

> Note: the prototypes from Phase 0 can also live in this repo (e.g. a `prototypes/` directory) so stakeholders and contributors can access them via git.

**Phase 2 — Validation core:** batch job + rules engine seeded with null-PO, PO-exists, and Transfer-Warehouse-balance checks; write errors to Postgres; idempotent re-runs.

**Phase 3 — JIRA automation:** create with hybrid routing, dedup by fingerprint, store keys, **auto-close on re-validation**.

**Phase 4 — Turnaround tracking:** webhook receiver + poller, `ticket_event` timeline, SLA metrics, recurrence analytics.

**Phase 5 — Dashboard & admin UI:** build the React app from the approved prototype; Entra SSO; role-based access.

**Phase 6 — Hardening:** alerting, performance tuning, audit log, broaden rules (3-way match, conversion sanity) via touchpoints.

---

## Open items to confirm during build
- **Sub-assignment / ownership-transfer mechanism** (from the 2026-06-09 walkthrough; shown as a concept in the approved prototype, **not yet finalized — Mike researching**): the **primary owner stays accountable** but can hand work to the root-cause team. Pavel's lean: on hand-off the **SLA clock moves to the secondary holder** and the **original SLA does not reset**; every transition is recorded in an **ownership audit log** (who → whom, when, SLA remaining) to prevent last-minute ping-pong. Decide the exact model and how per-person turnaround is attributed across a hand-off.
- **In-app assignment → Jira sync:** team leaders assign a ticket to an individual inside the app, which updates the Jira assignee (so staff don't work across two systems).
- **Facility → manager auto-routing:** e.g. a Field Ops PO over-receipt auto-assigns to that facility's manager — needs a facility→manager mapping (extends the routing/user-group table).
- **Role-based / hierarchy views:** build the app "big" (all features visible) first, then trim per user group via a backend user-group table (role → which views/teams are visible). Deferred until after the overloaded version is validated.
- **Dashboard "by inventory movement type" breakout** (added to the approved prototype) — confirm it stays and which movement categories matter most.
- Exact **BigQuery dataset/table names** for the unified ledger + PO tables, and their partitioning.
- **Validation-test thresholds** (the `X/Y/Z`, `$X`, `A%–B%` placeholders in the seed catalog) — set with accounting/ops at touchpoints; the rule set continues to grow.
- **Confirm Hard vs. Soft fail per test** — the framework defines the two types but doesn't tag each test; the catalog's Hard/Soft column is currently inferred.
- Map each **owner group** (SC Product (IMS), Field Ops, HDR Field Ops, Procurement, Accounting/Cost Accountant) to a concrete Jira assignee/component and an SSO/group identity.
- **Jira project(s)**, issue type, component/team taxonomy, and the custom field carrying the fingerprint.
- Which **ledger fields** drive data-derived routing vs. what comes from the mapping table.
- Entra **app registration** + group → role mapping.
- The precise condition for **auto-close** (issue no longer reproduces in N consecutive runs vs. immediately).

---

## Verification

- **Prototypes:** click through all four screens in each of the 2–3 UI directions; confirm with stakeholders that the chosen direction's exception-handling flow is intuitive and not overwhelming. Approval gate (one winning direction, or a blend) before any code.
- **Validation job:** run against a known prior-day partition with seeded rules; assert expected errors in Postgres; re-run is idempotent (fingerprint dedup).
- **Rules engine:** unit-test each primitive (pass/fail fixtures) incl. null-PO, PO-exists, Transfer-Warehouse balance; verify `CUSTOM_SQL` rules execute.
- **JIRA (sandbox project):** new error → correctly routed/assigned ticket; duplicate error → comment not new ticket; fixed data on next run → **ticket auto-closes** with audit note; status change (webhook + poll) updates `ticket_event` and recomputes turnaround.
- **API/auth:** endpoints reject unauthenticated requests and enforce Entra role mapping.
- **Dashboard:** seed errors+tickets; verify trend/turnaround/recurrence views and workbench reflect data; flag/override persists and audits.
- **Performance:** time a full daily run against a representative large partition; confirm dashboard queries hit summary tables (sub-second).
