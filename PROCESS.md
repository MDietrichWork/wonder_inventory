# PROCESS — Wonder Inventory Data-Quality Platform

A living log of the project. **Updated at every step** with what was completed (dated) and what's next. Newest entries on top.

> Process rule (from stakeholder walkthrough): visual mockups are built and socialized for approval **before** any production code. Touchpoint meetings every other day. End every phase by updating this file.

---

## What's next

- **Socialize the three prototypes** ([`prototypes/`](prototypes/README.md)) with Pavel and the wider group at the next touchpoint; gather feedback and pick a direction (or a blend).
- Iterate the chosen direction based on feedback.
- After approval, begin **Phase 1 — Foundation**: initialize/push the `wonder_inventory` GitHub repo, scaffold, Terraform, Cloud SQL, read-only BigQuery access to the specific ledger + PO tables, GitHub Actions CI.
- Open items to confirm with stakeholders/data engineering: exact BigQuery dataset/table names + partitioning; the growing validation rule set; Jira project/issue-type/component taxonomy + fingerprint custom field; which ledger fields drive data-derived routing; Entra app registration + group→role mapping; the precise auto-close condition (issue absent for N consecutive runs vs. immediately).

---

## Completed to date

### 2026-06-08 — Phase 0: Mockups built
- Established the project plan (mockup-first; daily batch validation; BigQuery source; Cloud SQL app DB; Python/FastAPI + React; Entra ID SSO; Jira Cloud with webhook+polling; hybrid routing; auto-close on re-validation). Full plan: `~/.claude/plans/i-will-be-creating-delegated-jellyfish.md`.
- Captured the domain model from the stakeholder walkthrough (unified ledger: systems of origin Pantry/Ship Hero/Fishbowl; facilities Infinite Kitchen/CK/DIS/Transfer Warehouse; location hierarchy; action types incl. Correction; reference order types; Transfer Warehouse balancing; Lot Expiration IDs; PO table + 3-way matching; weighted-avg cost / BOM via Cookbook↔Dynamics).
- Built **three self-contained clickable HTML prototypes** under `prototypes/` (no backend, no build step, no external dependencies — open `index.html` directly, works offline):
  - `variant-a-dense-workbench/` — information-dense data-grid / power-user direction.
  - `variant-b-guided-triage/` — guided, card-based, one-at-a-time triage for occasional/non-expert users.
  - `variant-c-dashboard-led/` — metrics/charts-first with drill-down into exceptions.
  - Each covers all four screens (exception workbench/triage, reporting dashboard, turnaround/SLA, rule & routing admin) with realistic, internally consistent sample data and demonstrates auto-created + auto-closed JIRA tickets, recurrence detection, and SLA tracking.
- Each variant lives in its own folder so the losing options can simply be deleted after selection.
- Wrote `README.md` (project overview), `prototypes/README.md` (how to open + how to choose), and this `PROCESS.md`.
- Validated all prototype JS files parse cleanly (JavaScriptCore) with no external/CDN dependencies and only local asset references.
