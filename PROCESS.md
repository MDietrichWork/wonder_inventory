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

### 2026-06-08 — Phase 0: Feedback iteration (pre-socialization)
- **Variant A:** clarified the Exception Workbench "Recur" column — renamed to **Recurrence**, added header + per-cell tooltips explaining it (times the same error recurred in 30 days), and added right padding so it isn't flush to the edge.
- **Variant B fully reworked.** The earlier guided-triage design read as too "cartoony" (emoji, warm playful theme). Replaced it with a new **light, professional 3-pane Inbox + Detail** design in `prototypes/variant-b-inbox/` (folders → exception list → full detail panel; monochrome inline-SVG icons; **no emoji**). Old `variant-b-guided-triage/` removed.
  - Fixed a runtime bug (`data.js` declared `const DATA` but `app.js` read `window.DATA`) by exposing `window.DATA`.
  - Made the **Auto-closed** folder showcase the flagship auto-close feature: added 3 recently-auto-closed exception records linked to their tickets (WIQ-1027/1031/1002); kept dashboard run-breakdowns and folder counts consistent (open 21, auto-closed 3) by excluding historical auto-closed from the current-run breakdowns and making My-team/Recurring folders open-only.
- Re-verified both variants with the Playwright harness: all screens render, **zero console/runtime errors**.
- Set up a headless QA workflow (Playwright/Chromium via `~/.wonder-tools-venv`) used to click through and screenshot prototypes.

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
- Set up a headless-browser QA harness (Python venv at `~/.wonder-tools-venv` + Playwright/Chromium; driver script at `tooling/shoot.py`) and drove all three prototypes end-to-end — clicking through every nav screen, screenshotting each, and capturing console/runtime errors.
  - Result: **all four screens render in every variant with zero console errors and zero runtime errors.**
  - **Bug found & fixed in Variant B:** three modal overlays were rendering on load and intercepting all clicks because `.modal-overlay { display:flex }` overrode the `hidden` attribute. Fixed with a global `[hidden] { display: none !important; }` rule in `variant-b-guided-triage/styles.css`; re-verified clean.
